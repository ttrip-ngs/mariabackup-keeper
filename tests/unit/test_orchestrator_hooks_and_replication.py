import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fakes import failing_mariabackup, make_fake_mariabackup, succeeding_mariabackup
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
from mariabackup_keeper.errors import PreconditionError
from mariabackup_keeper.exit_codes import ExitCode
from mariabackup_keeper.logging_setup import setup_logging
from mariabackup_keeper.orchestrator import run

_NOW = datetime(2026, 7, 2, 18, 0, 0, tzinfo=timezone.utc)


def _build_config(tmp_path: Path, mariabackup_path: str, hooks: HooksConfig, **overrides) -> Config:
    return Config(
        schema_version=1,
        backup=BackupConfig(work_dir=tmp_path / "work", mariabackup_path=mariabackup_path),
        destinations=(
            DestinationConfig(name="local", type="local", path=str(tmp_path / "store"), keep=5),
        ),
        replication=overrides.get("replication", ReplicationConfig()),
        transfer=TransferConfig(),
        retention=RetentionConfig(),
        logging=LoggingConfig(),
        lock=LockConfig(file=tmp_path / "mbkeeper.lock"),
        hooks=hooks,
    )


def _capture_script(tmp_path: Path, output_file: Path) -> str:
    return make_fake_mariabackup(
        tmp_path,
        f"import sys; open({str(output_file)!r}, 'w').write(sys.stdin.read())",
        name="capture-stdin.py",
    )


def test_pre_backup_hook_failure_aborts_before_any_backup_attempt(tmp_path: Path):
    config = _build_config(
        tmp_path, succeeding_mariabackup(tmp_path), HooksConfig(pre_backup="false")
    )
    setup_logging(config.logging)

    with pytest.raises(PreconditionError):
        run(config, now=_NOW)

    assert not (tmp_path / "store").exists()


def test_post_backup_hook_runs_after_successful_backup(tmp_path: Path):
    marker = tmp_path / "post-backup-ran"
    config = _build_config(
        tmp_path,
        succeeding_mariabackup(tmp_path),
        HooksConfig(post_backup=f"touch {marker}"),
    )
    setup_logging(config.logging)

    run(config, now=_NOW)

    assert marker.exists()


def test_post_backup_hook_does_not_run_when_backup_fails(tmp_path: Path):
    marker = tmp_path / "post-backup-ran"
    config = _build_config(
        tmp_path, failing_mariabackup(tmp_path), HooksConfig(post_backup=f"touch {marker}")
    )
    setup_logging(config.logging)

    run(config, now=_NOW)

    assert not marker.exists()


def test_pre_purge_hook_runs_before_purge(tmp_path: Path):
    marker = tmp_path / "pre-purge-ran"
    config = _build_config(
        tmp_path, succeeding_mariabackup(tmp_path), HooksConfig(pre_purge=f"touch {marker}")
    )
    setup_logging(config.logging)

    run(config, now=_NOW)

    assert marker.exists()


def test_post_run_hook_receives_summary_json_on_success(tmp_path: Path):
    output_file = tmp_path / "post-run-summary.json"
    script = _capture_script(tmp_path, output_file)
    config = _build_config(tmp_path, succeeding_mariabackup(tmp_path), HooksConfig(post_run=script))
    setup_logging(config.logging)

    summary = run(config, now=_NOW)

    payload = json.loads(output_file.read_text())
    assert payload["backup_id"] == summary.backup_id
    assert payload["exit_code"] == int(ExitCode.SUCCESS)


def test_post_run_hook_runs_even_when_backup_fails(tmp_path: Path):
    output_file = tmp_path / "post-run-summary.json"
    script = _capture_script(tmp_path, output_file)
    config = _build_config(tmp_path, failing_mariabackup(tmp_path), HooksConfig(post_run=script))
    setup_logging(config.logging)

    run(config, now=_NOW)

    payload = json.loads(output_file.read_text())
    assert payload["exit_code"] == int(ExitCode.BACKUP_FAILED)


def test_require_replica_mode_aborts_run_when_not_a_replica(tmp_path: Path):
    client = make_fake_mariabackup(
        tmp_path, "import sys; sys.exit(0)", name="fake-mariadb-empty.py"
    )
    config = _build_config(
        tmp_path,
        succeeding_mariabackup(tmp_path),
        HooksConfig(),
        replication=ReplicationConfig(mode="require_replica", client_path=client),
    )
    setup_logging(config.logging)

    with pytest.raises(PreconditionError, match="require_replica"):
        run(config, now=_NOW)


def test_replication_mode_off_never_invokes_the_client(tmp_path: Path):
    config = _build_config(
        tmp_path,
        succeeding_mariabackup(tmp_path),
        HooksConfig(),
        replication=ReplicationConfig(mode="off", client_path=str(tmp_path / "does-not-exist")),
    )
    setup_logging(config.logging)

    summary = run(config, now=_NOW)

    assert summary.exit_code == ExitCode.SUCCESS
