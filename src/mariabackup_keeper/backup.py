"""Abstraction over invoking the mariabackup binary.

mariabackup can return exit code 0 even on some failure paths, so success is
determined by return code AND the presence of its "completed OK!" marker in
stderr. Credentials never appear on argv; they are passed only via
--defaults-extra-file.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from mariabackup_keeper.config import BackupConfig, ReplicationConfig
from mariabackup_keeper.errors import BackupError

LOG_FILENAME = "mariabackup.log"
SUCCESS_MARKER = "completed OK!"
_TERMINATE_GRACE_SECONDS = 10
_TAIL_LOG_LINES = 20
_VERSION_TIMEOUT_SECONDS = 10


class MariabackupRunner:
    def __init__(
        self,
        config: BackupConfig,
        replication: ReplicationConfig,
        logger: logging.Logger,
    ) -> None:
        self._config = config
        self._replication = replication
        self._logger = logger

    def run_backup(self, target_dir: Path) -> None:
        self._execute(self._backup_argv(target_dir), target_dir / LOG_FILENAME, phase="backup")

    def run_prepare(self, target_dir: Path) -> None:
        self._execute(self._prepare_argv(target_dir), target_dir / LOG_FILENAME, phase="prepare")

    def get_version(self) -> str:
        try:
            proc = subprocess.run(
                [self._config.mariabackup_path, "--version"],
                capture_output=True,
                text=True,
                timeout=_VERSION_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"unknown ({exc})"
        return (proc.stdout or "").strip() or (proc.stderr or "").strip()

    def _backup_argv(self, target_dir: Path) -> list[str]:
        argv = [self._config.mariabackup_path, *self._defaults_args()]
        argv.append("--backup")
        argv.append(f"--target-dir={target_dir}")
        if self._replication.mode != "off" and self._replication.safe_slave_backup:
            argv.append("--safe-slave-backup")
        argv.extend(self._config.extra_args)
        return argv

    def _prepare_argv(self, target_dir: Path) -> list[str]:
        argv = [self._config.mariabackup_path]
        if self._config.defaults_file:
            argv.append(f"--defaults-file={self._config.defaults_file}")
        argv.append("--prepare")
        argv.append(f"--target-dir={target_dir}")
        return argv

    def _defaults_args(self) -> list[str]:
        args = []
        if self._config.defaults_file:
            args.append(f"--defaults-file={self._config.defaults_file}")
        if self._config.defaults_extra_file:
            args.append(f"--defaults-extra-file={self._config.defaults_extra_file}")
        return args

    def _execute(self, argv: list[str], log_path: Path, phase: str) -> None:
        self._logger.info(f"running mariabackup {phase}: {' '.join(argv)}")

        try:
            proc = subprocess.Popen(
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
            )
        except OSError as exc:
            raise BackupError(f"failed to launch mariabackup for {phase}: {exc}") from exc

        timeout = self._config.timeout_seconds or None
        timed_out = False
        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.terminate()
            try:
                _, stderr = proc.communicate(timeout=_TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                _, stderr = proc.communicate()

        stderr = stderr or ""
        with open(log_path, "a") as log_file:
            log_file.write(f"--- mariabackup {phase} ---\n{stderr}\n")

        for line in stderr.splitlines()[-_TAIL_LOG_LINES:]:
            self._logger.debug(f"mariabackup {phase}: {line}")

        if timed_out:
            raise BackupError(
                f"mariabackup {phase} timed out after {self._config.timeout_seconds}s "
                f"and was killed; see {log_path}"
            )

        if proc.returncode != 0 or SUCCESS_MARKER not in stderr:
            raise BackupError(
                f"mariabackup {phase} failed (returncode={proc.returncode}); see {log_path}"
            )
