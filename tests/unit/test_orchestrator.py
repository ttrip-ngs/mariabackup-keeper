import dataclasses
from datetime import datetime, timezone
from pathlib import Path

from fakes import failing_mariabackup, succeeding_mariabackup
from mariabackup_keeper.config import (
    BackupConfig,
    Config,
    DestinationConfig,
    HooksConfig,
    LockConfig,
    LoggingConfig,
    ReplicationConfig,
    RetentionConfig,
    TransferConfig,
)
from mariabackup_keeper.exit_codes import ExitCode
from mariabackup_keeper.logging_setup import setup_logging
from mariabackup_keeper.orchestrator import run

_NOW = datetime(2026, 7, 2, 18, 0, 0, tzinfo=timezone.utc)
_EXPECTED_BACKUP_ID = "full-20260702T180000Z"


def _build_config(tmp_path: Path, mariabackup_path: str, keep: int = 5) -> Config:
    return Config(
        schema_version=1,
        backup=BackupConfig(work_dir=tmp_path / "work", mariabackup_path=mariabackup_path),
        destinations=(
            DestinationConfig(name="local", type="local", path=str(tmp_path / "store"), keep=keep),
        ),
        replication=ReplicationConfig(),
        transfer=TransferConfig(),
        retention=RetentionConfig(),
        logging=LoggingConfig(),
        lock=LockConfig(file=tmp_path / "mbkeeper.lock"),
        hooks=HooksConfig(),
    )


def test_run_success_stores_to_local_destination_and_cleans_work_dir(tmp_path: Path):
    config = _build_config(tmp_path, succeeding_mariabackup(tmp_path))
    setup_logging(config.logging)

    summary = run(config, now=_NOW)

    assert summary.exit_code == ExitCode.SUCCESS
    assert summary.backup_id == _EXPECTED_BACKUP_ID
    assert (tmp_path / "store" / _EXPECTED_BACKUP_ID / "meta.json").is_file()
    assert not (tmp_path / "work" / _EXPECTED_BACKUP_ID).exists()


def test_run_backup_failure_returns_backup_failed_and_writes_nothing_to_destination(
    tmp_path: Path,
):
    config = _build_config(tmp_path, failing_mariabackup(tmp_path))
    setup_logging(config.logging)

    summary = run(config, now=_NOW)

    assert summary.exit_code == ExitCode.BACKUP_FAILED
    assert not (tmp_path / "store" / _EXPECTED_BACKUP_ID).exists()


def test_run_all_destinations_failed_preserves_work_dir(tmp_path: Path):
    config = _build_config(tmp_path, succeeding_mariabackup(tmp_path))
    unwritable_parent = tmp_path / "unwritable"
    unwritable_parent.mkdir()
    config = dataclasses.replace(
        config,
        destinations=(
            DestinationConfig(
                name="local", type="local", path=str(unwritable_parent / "store"), keep=5
            ),
        ),
    )
    unwritable_parent.chmod(0o500)
    setup_logging(config.logging)

    try:
        summary = run(config, now=_NOW)
    finally:
        unwritable_parent.chmod(0o700)

    assert summary.exit_code == ExitCode.ALL_DESTINATIONS_FAILED
    assert (tmp_path / "work" / _EXPECTED_BACKUP_ID).exists()


def test_run_cleans_stale_work_dir_entries_from_a_previous_crashed_run(tmp_path: Path):
    config = _build_config(tmp_path, succeeding_mariabackup(tmp_path))
    setup_logging(config.logging)
    run(config, now=_NOW)

    stale = config.backup.work_dir / "full-stale-leftover"
    stale.mkdir(parents=True)
    (stale / "junk").write_bytes(b"x")

    later = datetime(2026, 7, 2, 19, 0, 0, tzinfo=timezone.utc)
    run(config, now=later)

    assert not stale.exists()
