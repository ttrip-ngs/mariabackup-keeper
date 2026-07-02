from pathlib import Path

import pytest
from fakes import make_fake_mariabackup
from mariabackup_keeper.config import BackupConfig, ReplicationConfig
from mariabackup_keeper.errors import PreconditionError
from mariabackup_keeper.replication import check_replication

_VERSION_OUTPUT = "VERSION()\n11.4.2-MariaDB\n"


def _fake_client(tmp_path: Path, sql_responses: dict, exit_code: int = 0) -> str:
    """sql_responses maps a substring of the executed SQL to the stdout to emit.
    The SQL text is always the last argv element (see replication._run_client).
    """
    body = f"""
import sys
sql = sys.argv[-1]
responses = {sql_responses!r}
for key, output in responses.items():
    if key in sql:
        sys.stdout.write(output)
        break
sys.exit({exit_code})
"""
    return make_fake_mariabackup(tmp_path, body, name="fake-mariadb-client.py")


def _backup_config(tmp_path: Path) -> BackupConfig:
    return BackupConfig(work_dir=tmp_path / "work", mariabackup_path="mariabackup")


def test_not_a_replica_returns_is_replica_false(tmp_path: Path):
    client = _fake_client(tmp_path, {"REPLICA STATUS": "", "VERSION()": _VERSION_OUTPUT})

    state = check_replication(_backup_config(tmp_path), ReplicationConfig(client_path=client))

    assert state.is_replica is False
    assert state.lag_seconds is None
    assert state.server_version == "11.4.2-MariaDB"


def test_require_replica_mode_raises_when_not_a_replica(tmp_path: Path):
    client = _fake_client(tmp_path, {"REPLICA STATUS": "", "VERSION()": _VERSION_OUTPUT})

    with pytest.raises(PreconditionError, match="require_replica"):
        check_replication(
            _backup_config(tmp_path),
            ReplicationConfig(client_path=client, mode="require_replica"),
        )


def test_require_replica_mode_succeeds_when_replica_status_present(tmp_path: Path):
    status = "Slave_IO_State: Waiting for master to send event\nSeconds_Behind_Master: 0\n"
    client = _fake_client(tmp_path, {"REPLICA STATUS": status, "VERSION()": _VERSION_OUTPUT})

    state = check_replication(
        _backup_config(tmp_path), ReplicationConfig(client_path=client, mode="require_replica")
    )

    assert state.is_replica is True
    assert state.lag_seconds == 0


def test_max_lag_seconds_raises_when_lag_exceeds_threshold(tmp_path: Path):
    status = "Seconds_Behind_Master: 120\n"
    client = _fake_client(tmp_path, {"REPLICA STATUS": status, "VERSION()": _VERSION_OUTPUT})

    with pytest.raises(PreconditionError, match="lag"):
        check_replication(
            _backup_config(tmp_path), ReplicationConfig(client_path=client, max_lag_seconds=60)
        )


def test_max_lag_seconds_passes_when_within_threshold(tmp_path: Path):
    status = "Seconds_Behind_Master: 10\n"
    client = _fake_client(tmp_path, {"REPLICA STATUS": status, "VERSION()": _VERSION_OUTPUT})

    state = check_replication(
        _backup_config(tmp_path), ReplicationConfig(client_path=client, max_lag_seconds=60)
    )

    assert state.lag_seconds == 10


def test_max_lag_seconds_raises_when_lag_is_null(tmp_path: Path):
    status = "Seconds_Behind_Master: NULL\n"
    client = _fake_client(tmp_path, {"REPLICA STATUS": status, "VERSION()": _VERSION_OUTPUT})

    with pytest.raises(PreconditionError, match="NULL"):
        check_replication(
            _backup_config(tmp_path), ReplicationConfig(client_path=client, max_lag_seconds=60)
        )


def test_client_nonzero_exit_raises_precondition_error(tmp_path: Path):
    client = _fake_client(tmp_path, {}, exit_code=1)

    with pytest.raises(PreconditionError):
        check_replication(_backup_config(tmp_path), ReplicationConfig(client_path=client))


def test_missing_client_binary_raises_precondition_error(tmp_path: Path):
    missing = str(tmp_path / "does-not-exist")

    with pytest.raises(PreconditionError):
        check_replication(_backup_config(tmp_path), ReplicationConfig(client_path=missing))


def test_defaults_extra_file_is_passed_to_client(tmp_path: Path):
    marker = tmp_path / "argv.txt"
    body = f"""
import sys
with open({str(marker)!r}, "w") as f:
    f.write(" ".join(sys.argv))
sys.exit(0)
"""
    client = make_fake_mariabackup(tmp_path, body, name="fake-client-argv.py")
    backup = BackupConfig(
        work_dir=tmp_path / "work",
        mariabackup_path="mariabackup",
        defaults_extra_file="/etc/mbkeeper/creds.cnf",
    )

    check_replication(backup, ReplicationConfig(client_path=client))

    assert "--defaults-extra-file=/etc/mbkeeper/creds.cnf" in marker.read_text()
