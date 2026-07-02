"""The `run` pipeline: lock -> backup+prepare -> store to destinations.

Purge (M3), replication preconditions, and hooks (M4) are added on top of
this pipeline in later milestones without changing this module's contract.
"""

from __future__ import annotations

import shutil
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from mariabackup_keeper import __version__
from mariabackup_keeper.backup import MariabackupRunner
from mariabackup_keeper.config import Config
from mariabackup_keeper.destinations import build_destination
from mariabackup_keeper.errors import BackupError, DestinationError
from mariabackup_keeper.exit_codes import ExitCode
from mariabackup_keeper.locking import acquire_lock
from mariabackup_keeper.logging_setup import get_logger
from mariabackup_keeper.manifest import (
    MANIFEST_SCHEMA_VERSION,
    BackupMeta,
    directory_size_bytes,
    generate_backup_id,
    write_meta,
)


@dataclass(frozen=True)
class DestinationOutcome:
    name: str
    stored: bool
    error: str = ""


@dataclass(frozen=True)
class RunSummary:
    backup_id: str
    exit_code: ExitCode
    destination_outcomes: tuple[DestinationOutcome, ...] = field(default_factory=tuple)
    error: str = ""


def run(config: Config, now: datetime | None = None) -> RunSummary:
    logger = get_logger()
    now = now or datetime.now(timezone.utc)

    with acquire_lock(config.lock.file):
        backup_id = generate_backup_id(config.backup.name_prefix, now)
        logger.info(f"starting run backup_id={backup_id}")

        _cleanup_stale_work_dir(config.backup.work_dir, keep_id=backup_id, logger=logger)
        target_dir = config.backup.work_dir / backup_id
        target_dir.mkdir(parents=True, exist_ok=True)

        runner = MariabackupRunner(config.backup, config.replication, logger)
        started_at = datetime.now(timezone.utc)
        try:
            runner.run_backup(target_dir)
            if config.backup.prepare:
                runner.run_prepare(target_dir)
        except BackupError as exc:
            logger.error(f"backup failed: {exc}")
            return RunSummary(backup_id=backup_id, exit_code=ExitCode.BACKUP_FAILED, error=str(exc))
        finished_at = datetime.now(timezone.utc)

        write_meta(
            target_dir,
            BackupMeta(
                schema_version=MANIFEST_SCHEMA_VERSION,
                backup_id=backup_id,
                type="full",
                status="complete",
                started_at=started_at.isoformat(),
                finished_at=finished_at.isoformat(),
                hostname=socket.gethostname(),
                mariadb_version="",
                mariabackup_version=runner.get_version(),
                prepared=config.backup.prepare,
                size_bytes=directory_size_bytes(target_dir),
                tool_version=f"mariabackup-keeper {__version__}",
            ),
        )

        outcomes = _store_to_destinations(config, target_dir, backup_id, logger)
        succeeded = [o for o in outcomes if o.stored]
        failed = [o for o in outcomes if not o.stored]

        if failed and not succeeded:
            logger.error(
                f"all destinations failed for backup_id={backup_id}; "
                f"work_dir preserved: {target_dir}"
            )
            return RunSummary(
                backup_id=backup_id,
                exit_code=ExitCode.ALL_DESTINATIONS_FAILED,
                destination_outcomes=tuple(outcomes),
            )

        shutil.rmtree(target_dir, ignore_errors=True)

        exit_code = ExitCode.PARTIAL_DESTINATION_FAILURE if failed else ExitCode.SUCCESS
        logger.info(f"run complete backup_id={backup_id} exit_code={int(exit_code)}")
        return RunSummary(
            backup_id=backup_id, exit_code=exit_code, destination_outcomes=tuple(outcomes)
        )


def _store_to_destinations(config: Config, target_dir: Path, backup_id: str, logger):
    outcomes: list[DestinationOutcome] = []
    abort_on_failure = config.transfer.on_destination_failure == "abort"

    for dest_config in config.destinations:
        destination = build_destination(dest_config, config.transfer)
        try:
            destination.store(target_dir, backup_id)
        except DestinationError as exc:
            logger.error(
                f"failed to store backup_id={backup_id} to destination={dest_config.name}: {exc}"
            )
            outcomes.append(DestinationOutcome(name=dest_config.name, stored=False, error=str(exc)))
            if abort_on_failure:
                break
        else:
            logger.info(f"stored backup_id={backup_id} to destination={dest_config.name}")
            outcomes.append(DestinationOutcome(name=dest_config.name, stored=True))

    return outcomes


def _cleanup_stale_work_dir(work_dir: Path, keep_id: str, logger) -> None:
    if not work_dir.is_dir():
        return
    for entry in work_dir.iterdir():
        if entry.is_dir() and entry.name != keep_id:
            logger.warning(f"removing stale work_dir entry from a previous run: {entry}")
            shutil.rmtree(entry, ignore_errors=True)
