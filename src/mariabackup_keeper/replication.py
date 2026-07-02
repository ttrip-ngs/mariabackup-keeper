"""Replica-state preconditions: `require_replica` mode and lag ceiling.

Scope is deliberately narrow (see docs/design.md): no replica auto-selection,
no failover, no independent GTID bookkeeping -- mariabackup already writes
that into the generation itself.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from mariabackup_keeper.config import BackupConfig, ReplicationConfig
from mariabackup_keeper.errors import PreconditionError

_CLIENT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class ReplicationState:
    is_replica: bool
    lag_seconds: int | None
    server_version: str


def check_replication(backup: BackupConfig, replication: ReplicationConfig) -> ReplicationState:
    """Query SHOW REPLICA STATUS and enforce config.mode / config.max_lag_seconds.

    Raises PreconditionError if a configured requirement is not met.
    """
    status_output = _run_client(backup, replication, "SHOW REPLICA STATUS\\G")
    fields = _parse_status_block(status_output)
    is_replica = bool(fields)

    if replication.mode == "require_replica" and not is_replica:
        raise PreconditionError(
            "replication.mode=require_replica but SHOW REPLICA STATUS returned no rows "
            "(this node is not configured as a replica)"
        )

    lag_seconds = None
    if is_replica:
        raw_lag = fields.get("Seconds_Behind_Master", "")
        if raw_lag.isdigit():
            lag_seconds = int(raw_lag)

    if is_replica and replication.max_lag_seconds > 0:
        if lag_seconds is None:
            raise PreconditionError(
                "replication.max_lag_seconds is set but Seconds_Behind_Master is NULL "
                "(replication is stopped or lag is unknown)"
            )
        if lag_seconds > replication.max_lag_seconds:
            raise PreconditionError(
                f"replication lag {lag_seconds}s exceeds "
                f"max_lag_seconds={replication.max_lag_seconds}"
            )

    return ReplicationState(
        is_replica=is_replica,
        lag_seconds=lag_seconds,
        server_version=_query_server_version(backup, replication),
    )


def _query_server_version(backup: BackupConfig, replication: ReplicationConfig) -> str:
    try:
        output = _run_client(backup, replication, "SELECT VERSION()")
    except PreconditionError:
        return ""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _run_client(backup: BackupConfig, replication: ReplicationConfig, sql: str) -> str:
    argv = [replication.client_path]
    if backup.defaults_file:
        argv.append(f"--defaults-file={backup.defaults_file}")
    if backup.defaults_extra_file:
        argv.append(f"--defaults-extra-file={backup.defaults_extra_file}")
    argv.extend(["-e", sql])

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=_CLIENT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreconditionError(f"failed to run {replication.client_path}: {exc}") from exc
    if proc.returncode != 0:
        raise PreconditionError(
            f"{replication.client_path} failed (returncode={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return proc.stdout


def _parse_status_block(output: str) -> dict[str, str]:
    fields = {}
    for line in output.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields
