from datetime import datetime, timezone
from pathlib import Path

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
from mariabackup_keeper.orchestrator import purge

_NOW = datetime(2026, 7, 2, 18, 0, 0, tzinfo=timezone.utc)


def _seed_generation(store_dir: Path, backup_id: str) -> None:
    gen_dir = store_dir / backup_id
    gen_dir.mkdir(parents=True)
    (gen_dir / "meta.json").write_text("{}")


def _build_config(tmp_path: Path, keep: int = 2, destinations=None) -> Config:
    return Config(
        schema_version=1,
        backup=BackupConfig(work_dir=tmp_path / "work", mariabackup_path="mariabackup"),
        destinations=destinations
        or (
            DestinationConfig(name="local", type="local", path=str(tmp_path / "store"), keep=keep),
        ),
        replication=ReplicationConfig(),
        transfer=TransferConfig(),
        retention=RetentionConfig(),
        logging=LoggingConfig(),
        lock=LockConfig(file=tmp_path / "mbkeeper.lock"),
        hooks=HooksConfig(),
    )


def test_purge_deletes_generations_beyond_keep(tmp_path: Path):
    store_dir = tmp_path / "store"
    for i in range(1, 6):
        _seed_generation(store_dir, f"full-0{i}")
    config = _build_config(tmp_path, keep=2)
    setup_logging(config.logging)

    summary = purge(config, now=_NOW)

    assert summary.exit_code == ExitCode.SUCCESS
    result = summary.results[0]
    assert set(result.deleted) == {"full-01", "full-02", "full-03"}
    assert set(result.kept) == {"full-04", "full-05"}
    assert not (store_dir / "full-01").exists()
    assert (store_dir / "full-05").exists()


def test_purge_dry_run_reports_without_deleting(tmp_path: Path):
    store_dir = tmp_path / "store"
    for i in range(1, 4):
        _seed_generation(store_dir, f"full-0{i}")
    config = _build_config(tmp_path, keep=1)
    setup_logging(config.logging)

    summary = purge(config, dry_run=True, now=_NOW)

    assert summary.exit_code == ExitCode.SUCCESS
    assert set(summary.results[0].deleted) == {"full-01", "full-02"}
    assert (store_dir / "full-01").exists()  # dry-run: nothing actually removed
    assert (store_dir / "full-02").exists()


def test_purge_destination_filter_limits_scope(tmp_path: Path):
    store_a = tmp_path / "store-a"
    store_b = tmp_path / "store-b"
    for i in range(1, 4):
        _seed_generation(store_a, f"full-0{i}")
        _seed_generation(store_b, f"full-0{i}")
    config = _build_config(
        tmp_path,
        destinations=(
            DestinationConfig(name="a", type="local", path=str(store_a), keep=1),
            DestinationConfig(name="b", type="local", path=str(store_b), keep=1),
        ),
    )
    setup_logging(config.logging)

    summary = purge(config, destination_names={"a"}, now=_NOW)

    assert len(summary.results) == 1
    assert summary.results[0].name == "a"
    assert not (store_a / "full-01").exists()
    assert (store_b / "full-01").exists()  # untouched: filtered out


def test_purge_returns_purge_failed_when_listing_fails(tmp_path: Path):
    config = _build_config(tmp_path, keep=1)  # store dir is never created
    setup_logging(config.logging)

    summary = purge(config, now=_NOW)

    assert summary.exit_code == ExitCode.PURGE_FAILED
    assert summary.results[0].error != ""


def test_purge_returns_purge_failed_when_delete_fails(tmp_path: Path):
    store_dir = tmp_path / "store"
    for i in range(1, 4):
        _seed_generation(store_dir, f"full-0{i}")
    config = _build_config(tmp_path, keep=1)
    setup_logging(config.logging)
    store_dir.chmod(0o500)  # readable+listable, but entries cannot be unlinked

    try:
        summary = purge(config, now=_NOW)
    finally:
        store_dir.chmod(0o700)

    assert summary.exit_code == ExitCode.PURGE_FAILED
    assert summary.results[0].error == ""  # listing succeeded; only delete() failed
    assert summary.results[0].deleted == ()
