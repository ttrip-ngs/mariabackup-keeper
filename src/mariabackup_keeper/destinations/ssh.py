"""rsync-over-SSH destination for cross-backup (replica -> master/DR node).

Commit protocol mirrors local.py: rsync data into "<id>.partial" (excluding
meta.json), rsync meta.json in, then `mv` remotely to commit atomically.
Argv-building is split into pure functions (build_ssh_argv/build_rsync_argv)
so the command lines can be unit tested without a real ssh/rsync round trip.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from mariabackup_keeper.config import DestinationConfig, TransferConfig
from mariabackup_keeper.destinations import register
from mariabackup_keeper.destinations.base import Destination, StoredBackup
from mariabackup_keeper.errors import DestinationError
from mariabackup_keeper.manifest import META_FILENAME

PARTIAL_SUFFIX = ".partial"
_CHECK_PROBE_FILENAME = ".mbkeeper-check"
_SSH_COMMAND_TIMEOUT_SECONDS = 30

# POSIX sh; runs on the remote node via `ssh user@host <script>`. Lists each
# top-level entry as "COMPLETE <id> <mtime>" or "PARTIAL <id> <mtime>".
_LIST_SCRIPT_TEMPLATE = (
    'set -e; cd "{path}" 2>/dev/null || exit 0; '
    "for entry in */; do "
    'name="${{entry%/}}"; '
    'mtime=$(stat -c %Y "$name" 2>/dev/null || echo 0); '
    'if [ -f "$name/{meta}" ]; then echo "COMPLETE $name $mtime"; '
    'elif [ "${{name%{suffix}}}" != "$name" ]; then '
    'echo "PARTIAL ${{name%{suffix}}} $mtime"; '
    "fi; "
    "done"
)


def build_ssh_argv(ssh_key: str, port: int, ssh_options: tuple[str, ...]) -> list[str]:
    return ["ssh", "-i", ssh_key, "-p", str(port), "-o", "BatchMode=yes", *ssh_options]


def build_rsync_argv(
    rsync_path: str,
    ssh_argv: list[str],
    src: Path,
    dst: str,
    bwlimit_kbps: int = 0,
    exclude: list[str] | None = None,
) -> list[str]:
    argv = [rsync_path, "-a", "--partial", "--delete"]
    if bwlimit_kbps:
        argv.append(f"--bwlimit={bwlimit_kbps}")
    for pattern in exclude or []:
        argv.append(f"--exclude={pattern}")
    argv.append("-e")
    argv.append(" ".join(ssh_argv))
    argv.append(f"{src}/")
    argv.append(dst)
    return argv


def build_rsync_file_argv(rsync_path: str, ssh_argv: list[str], src: Path, dst: str) -> list[str]:
    return [rsync_path, "-a", "-e", " ".join(ssh_argv), str(src), dst]


def parse_list_output(stdout: str) -> list[StoredBackup]:
    results = []
    for line in stdout.splitlines():
        parts = line.split(" ")
        if len(parts) != 3:
            continue
        status, backup_id, mtime = parts
        results.append(
            StoredBackup(
                backup_id=backup_id,
                complete=(status == "COMPLETE"),
                stored_at=datetime.fromtimestamp(int(mtime), tz=timezone.utc),
            )
        )
    return results


@register("ssh")
class SSHDestination(Destination):
    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        user: str,
        remote_path: str,
        ssh_key: str,
        ssh_options: tuple[str, ...],
        bwlimit_kbps: int,
        rsync_path: str,
        retries: int,
        keep: int,
    ) -> None:
        self.name = name
        self.keep = keep
        self._host = host
        self._port = port
        self._user = user
        self._remote_path = remote_path
        self._ssh_key = ssh_key
        self._ssh_options = ssh_options
        self._bwlimit_kbps = bwlimit_kbps
        self._rsync_path = rsync_path
        self._retries = retries

    @classmethod
    def from_config(cls, config: DestinationConfig, transfer: TransferConfig) -> SSHDestination:
        return cls(
            name=config.name,
            host=config.host,
            port=config.port,
            user=config.user,
            remote_path=config.path,
            ssh_key=config.ssh_key,
            ssh_options=config.ssh_options,
            bwlimit_kbps=config.bwlimit_kbps,
            rsync_path=transfer.rsync_path,
            retries=transfer.retries,
            keep=config.keep,
        )

    def store(self, local_dir: Path, backup_id: str) -> None:
        if self._remote_file_exists(f"{self._remote_path}/{backup_id}/{META_FILENAME}"):
            return  # already stored and complete: idempotent no-op

        self._remote_run(f'mkdir -p "{self._remote_path}"')
        partial_remote = f"{self._remote_path}/{backup_id}{PARTIAL_SUFFIX}"
        self._rsync_directory(local_dir, partial_remote, exclude=[META_FILENAME])

        meta_src = local_dir / META_FILENAME
        if meta_src.is_file():
            self._rsync_meta_file(meta_src, f"{partial_remote}/{META_FILENAME}")

        self._remote_run(f'mv "{partial_remote}" "{self._remote_path}/{backup_id}"')

    def list_backups(self) -> list[StoredBackup]:
        script = _LIST_SCRIPT_TEMPLATE.format(
            path=self._remote_path, meta=META_FILENAME, suffix=PARTIAL_SUFFIX
        )
        proc = self._remote_run(script)
        return parse_list_output(proc.stdout)

    def delete(self, backup_id: str) -> None:
        self._remote_run(
            f'rm -rf "{self._remote_path}/{backup_id}" '
            f'"{self._remote_path}/{backup_id}{PARTIAL_SUFFIX}"'
        )

    def check(self) -> None:
        probe = f"{self._remote_path}/{_CHECK_PROBE_FILENAME}"
        self._remote_run(f'mkdir -p "{self._remote_path}" && touch "{probe}" && rm -f "{probe}"')

    def _ssh_argv(self) -> list[str]:
        return build_ssh_argv(self._ssh_key, self._port, self._ssh_options)

    def _user_host(self) -> str:
        return f"{self._user}@{self._host}"

    def _remote_run(self, command: str) -> subprocess.CompletedProcess:
        argv = [*self._ssh_argv(), self._user_host(), command]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=_SSH_COMMAND_TIMEOUT_SECONDS
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DestinationError(f"destination '{self.name}': ssh command failed: {exc}") from exc
        if proc.returncode != 0:
            raise DestinationError(
                f"destination '{self.name}': remote command failed "
                f"(returncode={proc.returncode}): {proc.stderr.strip()}"
            )
        return proc

    def _remote_file_exists(self, path: str) -> bool:
        argv = [*self._ssh_argv(), self._user_host(), f'test -f "{path}"']
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=_SSH_COMMAND_TIMEOUT_SECONDS
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DestinationError(f"destination '{self.name}': ssh command failed: {exc}") from exc
        return proc.returncode == 0

    def _rsync_directory(self, src: Path, remote_dir: str, exclude: list[str]) -> None:
        argv = build_rsync_argv(
            rsync_path=self._rsync_path,
            ssh_argv=self._ssh_argv(),
            src=src,
            dst=f"{self._user_host()}:{remote_dir}",
            bwlimit_kbps=self._bwlimit_kbps,
            exclude=exclude,
        )
        self._run_with_retries(argv)

    def _rsync_meta_file(self, src_file: Path, remote_file: str) -> None:
        argv = build_rsync_file_argv(
            rsync_path=self._rsync_path,
            ssh_argv=self._ssh_argv(),
            src=src_file,
            dst=f"{self._user_host()}:{remote_file}",
        )
        self._run_with_retries(argv)

    def _run_with_retries(self, argv: list[str]) -> None:
        last_error = "unknown error"
        for _ in range(self._retries + 1):
            try:
                proc = subprocess.run(argv, capture_output=True, text=True)
            except (OSError, subprocess.SubprocessError) as exc:
                last_error = str(exc)
                continue
            if proc.returncode == 0:
                return
            last_error = proc.stderr.strip() or f"rsync exited {proc.returncode}"
        raise DestinationError(
            f"destination '{self.name}': rsync failed after retries: {last_error}"
        )
