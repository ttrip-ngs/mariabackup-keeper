"""The `run` pipeline: lock -> backup+prepare -> store -> purge.

Replication preconditions and hooks (M4) are added on top of this pipeline
in a later milestone without changing this module's contract.
"""

from __future__ import annotations

import shutil
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from mariabackup_keeper import __version__
from mariabackup_keeper.backup import MariabackupRunner
from mariabackup_keeper.config import Config, DestinationConfig
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
from mariabackup_keeper.retention import select_purge


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


@dataclass(frozen=True)
class DestinationPurgeResult:
    name: str
    deleted: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class PurgeSummary:
    exit_code: ExitCode
    results: tuple[DestinationPurgeResult, ...] = ()


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

        purge_had_error = _purge_stored_destinations(config, succeeded, backup_id, now, logger)

        if failed:
            exit_code = ExitCode.PARTIAL_DESTINATION_FAILURE
        elif purge_had_error:
            exit_code = ExitCode.PURGE_FAILED
        else:
            exit_code = ExitCode.SUCCESS

        logger.info(f"run complete backup_id={backup_id} exit_code={int(exit_code)}")
        return RunSummary(
            backup_id=backup_id, exit_code=exit_code, destination_outcomes=tuple(outcomes)
        )


def purge(
    config: Config,
    destination_names: set[str] | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> PurgeSummary:
    logger = get_logger()
    now = now or datetime.now(timezone.utc)

    with acquire_lock(config.lock.file):
        results = []
        had_error = False

        for dest_config in config.destinations:
            if destination_names is not None and dest_config.name not in destination_names:
                continue

            result, error = _purge_one_destination(config, dest_config, now, dry_run, logger)
            results.append(result)
            had_error = had_error or error

        exit_code = ExitCode.PURGE_FAILED if had_error else ExitCode.SUCCESS
        return PurgeSummary(exit_code=exit_code, results=tuple(results))


def _purge_one_destination(
    config: Config,
    dest_config: DestinationConfig,
    now: datetime,
    dry_run: bool,
    logger,
    in_progress_id: str | None = None,
) -> tuple[DestinationPurgeResult, bool]:
    destination = build_destination(dest_config, config.transfer)

    try:
        stored = destination.list_backups()
    except DestinationError as exc:
        logger.error(
            f"destination '{dest_config.name}': cannot list backups, skipping purge: {exc}"
        )
        return DestinationPurgeResult(name=dest_config.name, error=str(exc)), True

    plan = select_purge(
        stored,
        dest_config.keep,
        config.retention.incomplete_grace_hours,
        now,
        in_progress_id=in_progress_id,
    )

    deleted: list[str] = []
    had_error = False
    for backup_id in plan.delete:
        if dry_run:
            deleted.append(backup_id)
            continue
        try:
            destination.delete(backup_id)
            deleted.append(backup_id)
            logger.info(f"purged backup_id={backup_id} from destination={dest_config.name}")
        except DestinationError as exc:
            logger.error(f"destination '{dest_config.name}': failed to delete {backup_id}: {exc}")
            had_error = True

    return (
        DestinationPurgeResult(name=dest_config.name, deleted=tuple(deleted), kept=plan.keep),
        had_error,
    )


def _purge_stored_destinations(
    config: Config,
    succeeded: list[DestinationOutcome],
    backup_id: str,
    now: datetime,
    logger,
) -> bool:
    """Purge only the destinations that just received this run's backup.

    A destination this run failed to write to keeps its existing generations
    untouched -- deleting from an already-degraded destination would reduce
    redundancy further.
    """
    destinations_by_name = {d.name: d for d in config.destinations}
    had_error = False

    for outcome in succeeded:
        dest_config = destinations_by_name[outcome.name]
        _, error = _purge_one_destination(
            config, dest_config, now, dry_run=False, logger=logger, in_progress_id=backup_id
        )
        had_error = had_error or error

    return had_error


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
