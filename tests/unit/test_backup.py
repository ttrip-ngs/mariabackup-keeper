from pathlib import Path

import pytest
from fakes import (
    failing_mariabackup,
    hanging_mariabackup,
    make_fake_mariabackup,
    null_logger,
    succeeding_mariabackup,
)
from mariabackup_keeper.backup import MariabackupRunner
from mariabackup_keeper.config import BackupConfig, ReplicationConfig
from mariabackup_keeper.errors import BackupError


def test_backup_argv_includes_defaults_extra_file_and_target_dir(tmp_path: Path):
    fake = succeeding_mariabackup(tmp_path)
    config = BackupConfig(
        work_dir=tmp_path,
        mariabackup_path=fake,
        defaults_extra_file="/etc/mbkeeper/creds.cnf",
        extra_args=("--parallel=4",),
    )
    runner = MariabackupRunner(config, ReplicationConfig(), null_logger())

    argv = runner._backup_argv(tmp_path / "gen1")

    assert argv[0] == fake
    assert "--defaults-extra-file=/etc/mbkeeper/creds.cnf" in argv
    assert "--backup" in argv
    assert f"--target-dir={tmp_path / 'gen1'}" in argv
    assert argv[-1] == "--parallel=4"


def test_backup_argv_adds_safe_slave_backup_when_replica_mode_on(tmp_path: Path):
    config = BackupConfig(work_dir=tmp_path, mariabackup_path="mariabackup")
    replication = ReplicationConfig(mode="require_replica", safe_slave_backup=True)
    runner = MariabackupRunner(config, replication, null_logger())

    argv = runner._backup_argv(tmp_path / "gen1")

    assert "--safe-slave-backup" in argv


def test_backup_argv_omits_safe_slave_backup_when_disabled(tmp_path: Path):
    config = BackupConfig(work_dir=tmp_path, mariabackup_path="mariabackup")
    replication = ReplicationConfig(mode="require_replica", safe_slave_backup=False)
    runner = MariabackupRunner(config, replication, null_logger())

    argv = runner._backup_argv(tmp_path / "gen1")

    assert "--safe-slave-backup" not in argv


def test_backup_argv_off_mode_never_adds_safe_slave_backup(tmp_path: Path):
    config = BackupConfig(work_dir=tmp_path, mariabackup_path="mariabackup")
    replication = ReplicationConfig(mode="off", safe_slave_backup=True)
    runner = MariabackupRunner(config, replication, null_logger())

    argv = runner._backup_argv(tmp_path / "gen1")

    assert "--safe-slave-backup" not in argv


def test_run_backup_success_writes_log(tmp_path: Path):
    fake = succeeding_mariabackup(tmp_path)
    config = BackupConfig(work_dir=tmp_path, mariabackup_path=fake)
    runner = MariabackupRunner(config, ReplicationConfig(), null_logger())
    target_dir = tmp_path / "gen1"
    target_dir.mkdir()

    runner.run_backup(target_dir)

    assert "completed OK!" in (target_dir / "mariabackup.log").read_text()


def test_run_backup_raises_on_nonzero_exit(tmp_path: Path):
    fake = failing_mariabackup(tmp_path)
    config = BackupConfig(work_dir=tmp_path, mariabackup_path=fake)
    runner = MariabackupRunner(config, ReplicationConfig(), null_logger())
    target_dir = tmp_path / "gen1"
    target_dir.mkdir()

    with pytest.raises(BackupError):
        runner.run_backup(target_dir)


def test_run_backup_raises_when_success_marker_missing_despite_rc0(tmp_path: Path):
    fake = make_fake_mariabackup(tmp_path, "import sys; sys.stderr.write('no marker here\\n')")
    config = BackupConfig(work_dir=tmp_path, mariabackup_path=fake)
    runner = MariabackupRunner(config, ReplicationConfig(), null_logger())
    target_dir = tmp_path / "gen1"
    target_dir.mkdir()

    with pytest.raises(BackupError):
        runner.run_backup(target_dir)


def test_run_backup_timeout_kills_process_and_raises(tmp_path: Path):
    fake = hanging_mariabackup(tmp_path)
    config = BackupConfig(work_dir=tmp_path, mariabackup_path=fake, timeout_seconds=1)
    runner = MariabackupRunner(config, ReplicationConfig(), null_logger())
    target_dir = tmp_path / "gen1"
    target_dir.mkdir()

    with pytest.raises(BackupError, match="timed out"):
        runner.run_backup(target_dir)


def test_get_version_returns_stdout(tmp_path: Path):
    fake = make_fake_mariabackup(tmp_path, "print('mariabackup 11.4.0')")
    config = BackupConfig(work_dir=tmp_path, mariabackup_path=fake)
    runner = MariabackupRunner(config, ReplicationConfig(), null_logger())

    assert "11.4.0" in runner.get_version()


def test_get_version_handles_missing_binary_gracefully(tmp_path: Path):
    config = BackupConfig(work_dir=tmp_path, mariabackup_path=str(tmp_path / "does-not-exist"))
    runner = MariabackupRunner(config, ReplicationConfig(), null_logger())

    assert "unknown" in runner.get_version()
