from pathlib import Path

from fakes import make_fake_mariabackup, succeeding_mariabackup
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
from mariabackup_keeper.orchestrator import check


def _build_config(tmp_path: Path, mariabackup_path: str, replication: ReplicationConfig) -> Config:
    return Config(
        schema_version=1,
        backup=BackupConfig(work_dir=tmp_path / "work", mariabackup_path=mariabackup_path),
        destinations=(
            DestinationConfig(name="local", type="local", path=str(tmp_path / "store"), keep=5),
        ),
        replication=replication,
        transfer=TransferConfig(),
        retention=RetentionConfig(),
        logging=LoggingConfig(),
        lock=LockConfig(file=tmp_path / "mbkeeper.lock"),
        hooks=HooksConfig(),
    )


def _fake_client(
    tmp_path: Path, status_output: str = "", version_output: str = "VERSION()\n11.4.2-MariaDB\n"
) -> str:
    body = f"""
import sys
sql = sys.argv[-1]
if "REPLICA STATUS" in sql:
    sys.stdout.write({status_output!r})
elif "VERSION" in sql:
    sys.stdout.write({version_output!r})
sys.exit(0)
"""
    return make_fake_mariabackup(tmp_path, body, name="fake-check-client.py")


def test_check_reports_ok_when_everything_is_reachable(tmp_path: Path):
    client = _fake_client(tmp_path)
    config = _build_config(
        tmp_path, succeeding_mariabackup(tmp_path), ReplicationConfig(client_path=client)
    )

    summary = check(config)

    assert summary.ok is True
    names = {item.name for item in summary.items}
    assert names == {"mariabackup", "replication", "destination:local"}
    assert all(item.ok for item in summary.items)


def test_check_reports_failure_when_mariabackup_binary_missing(tmp_path: Path):
    client = _fake_client(tmp_path)
    config = _build_config(
        tmp_path, str(tmp_path / "does-not-exist"), ReplicationConfig(client_path=client)
    )

    summary = check(config)

    assert summary.ok is False
    mariabackup_item = next(item for item in summary.items if item.name == "mariabackup")
    assert mariabackup_item.ok is False


def test_check_reports_failure_when_destination_unwritable(tmp_path: Path):
    client = _fake_client(tmp_path)
    unwritable_parent = tmp_path / "unwritable"
    unwritable_parent.mkdir()
    config = _build_config(
        tmp_path, succeeding_mariabackup(tmp_path), ReplicationConfig(client_path=client)
    )
    import dataclasses

    config = dataclasses.replace(
        config,
        destinations=(
            DestinationConfig(
                name="local", type="local", path=str(unwritable_parent / "store"), keep=5
            ),
        ),
    )
    unwritable_parent.chmod(0o500)

    try:
        summary = check(config)
    finally:
        unwritable_parent.chmod(0o700)

    assert summary.ok is False
    dest_item = next(item for item in summary.items if item.name == "destination:local")
    assert dest_item.ok is False


def test_check_reports_failure_when_replication_client_unreachable(tmp_path: Path):
    config = _build_config(
        tmp_path,
        succeeding_mariabackup(tmp_path),
        ReplicationConfig(client_path=str(tmp_path / "does-not-exist"), mode="require_replica"),
    )

    summary = check(config)

    assert summary.ok is False
    replication_item = next(item for item in summary.items if item.name == "replication")
    assert replication_item.ok is False
