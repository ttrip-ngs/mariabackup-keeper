"""SSHDestination tests.

Uses a fake `ssh` on PATH that runs the "remote" command locally (see
fakes.make_fake_ssh_bin_dir), so these exercise the mkdir/test/rm/mv command
wiring portably without real network or a Linux-only `stat -c` dependency.
Full data-transfer coverage against a real sshd + rsync lives in
tests/integration (Docker), per the design's unit/integration split.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fakes import make_fake_ssh_bin_dir
from mariabackup_keeper.config import DestinationConfig, TransferConfig
from mariabackup_keeper.destinations.base import StoredBackup
from mariabackup_keeper.destinations.ssh import SSHDestination, parse_list_output
from mariabackup_keeper.errors import DestinationError


@pytest.fixture
def fake_ssh_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = make_fake_ssh_bin_dir(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


def _make_destination(remote_path: Path, keep: int = 5) -> SSHDestination:
    return SSHDestination(
        name="remote",
        host="localhost",
        port=22,
        user=os.environ.get("USER", "test"),
        remote_path=str(remote_path),
        ssh_key="/dev/null",
        ssh_options=(),
        bwlimit_kbps=0,
        rsync_path="rsync",
        retries=0,
        keep=keep,
    )


def test_from_config_builds_destination_from_ssh_fields(tmp_path: Path):
    config = DestinationConfig(
        name="remote",
        type="ssh",
        path=str(tmp_path / "backups"),
        keep=14,
        host="db-master.example.com",
        user="backup",
        ssh_key="/etc/mbkeeper/id_ed25519",
        port=2222,
        ssh_options=("-o", "StrictHostKeyChecking=accept-new"),
        bwlimit_kbps=5000,
    )
    transfer = TransferConfig(retries=3, rsync_path="/usr/local/bin/rsync")

    dest = SSHDestination.from_config(config, transfer)

    assert dest.name == "remote"
    assert dest.keep == 14
    assert dest._host == "db-master.example.com"
    assert dest._port == 2222
    assert dest._retries == 3
    assert dest._rsync_path == "/usr/local/bin/rsync"


def test_check_succeeds_when_remote_path_is_writable(fake_ssh_path, tmp_path: Path):
    remote_path = tmp_path / "backups"
    dest = _make_destination(remote_path)

    dest.check()

    assert remote_path.is_dir()
    assert not (remote_path / ".mbkeeper-check").exists()


def test_check_raises_destination_error_when_remote_command_fails(fake_ssh_path, tmp_path: Path):
    readonly_parent = tmp_path / "readonly"
    readonly_parent.mkdir()
    readonly_parent.chmod(0o500)
    dest = _make_destination(readonly_parent / "backups")

    try:
        with pytest.raises(DestinationError):
            dest.check()
    finally:
        readonly_parent.chmod(0o700)


def test_delete_is_idempotent_when_generation_absent(fake_ssh_path, tmp_path: Path):
    remote_path = tmp_path / "backups"
    remote_path.mkdir()
    dest = _make_destination(remote_path)

    dest.delete("does-not-exist")  # rm -rf on a missing path must not raise


def test_delete_removes_complete_and_partial_directories(fake_ssh_path, tmp_path: Path):
    remote_path = tmp_path / "backups"
    (remote_path / "full-1").mkdir(parents=True)
    (remote_path / "full-2.partial").mkdir(parents=True)
    dest = _make_destination(remote_path)

    dest.delete("full-1")
    dest.delete("full-2")

    assert not (remote_path / "full-1").exists()
    assert not (remote_path / "full-2.partial").exists()


def test_store_is_idempotent_when_already_complete(fake_ssh_path, tmp_path: Path):
    remote_path = tmp_path / "backups"
    complete_dir = remote_path / "full-1"
    complete_dir.mkdir(parents=True)
    (complete_dir / "meta.json").write_text('{"marker": "untouched"}')
    dest = _make_destination(remote_path)

    dest.store(tmp_path / "irrelevant-local-dir", "full-1")

    assert (complete_dir / "meta.json").read_text() == '{"marker": "untouched"}'


def test_parse_list_output_distinguishes_complete_and_partial():
    stdout = "COMPLETE full-2 1700000200\nPARTIAL full-3 1700000300\n"

    backups = parse_list_output(stdout)

    assert backups == [
        StoredBackup(
            backup_id="full-2",
            complete=True,
            stored_at=datetime.fromtimestamp(1700000200, tz=timezone.utc),
        ),
        StoredBackup(
            backup_id="full-3",
            complete=False,
            stored_at=datetime.fromtimestamp(1700000300, tz=timezone.utc),
        ),
    ]


def test_parse_list_output_ignores_malformed_lines():
    assert parse_list_output("not a valid line\n\n") == []


def test_parse_list_output_empty_string_returns_empty_list():
    assert parse_list_output("") == []
