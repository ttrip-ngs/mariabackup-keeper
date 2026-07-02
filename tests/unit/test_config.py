from pathlib import Path

import pytest
from mariabackup_keeper.config import parse_config
from mariabackup_keeper.errors import ConfigError


def _minimal_raw(**overrides):
    raw = {
        "schema_version": 1,
        "backup": {"work_dir": "/var/lib/mbkeeper/work"},
        "destinations": [
            {"name": "local", "type": "local", "path": "/var/backups/store", "keep": 7}
        ],
    }
    raw.update(overrides)
    return raw


def test_minimal_config_parses_with_defaults():
    config = parse_config(_minimal_raw())

    assert config.schema_version == 1
    assert config.backup.work_dir == Path("/var/lib/mbkeeper/work")
    assert config.backup.name_prefix == "full"
    assert config.backup.prepare is True
    assert config.replication.mode == "off"
    assert config.transfer.on_destination_failure == "continue"
    assert config.retention.incomplete_grace_hours == 24
    assert len(config.destinations) == 1
    assert config.destinations[0].name == "local"
    assert config.destinations[0].keep == 7
    assert config.logging.level == "info"
    assert config.logging.format == "text"
    assert config.lock.file == Path("/run/mbkeeper/mbkeeper.lock")


def test_missing_work_dir_is_rejected():
    raw = _minimal_raw()
    del raw["backup"]["work_dir"]

    with pytest.raises(ConfigError, match="work_dir"):
        parse_config(raw)


def test_missing_backup_section_is_rejected():
    raw = _minimal_raw()
    del raw["backup"]

    with pytest.raises(ConfigError, match="backup"):
        parse_config(raw)


def test_unknown_top_level_key_is_rejected():
    raw = _minimal_raw()
    raw["totally_unknown"] = "value"

    with pytest.raises(ConfigError, match="unknown key 'totally_unknown'"):
        parse_config(raw)


def test_unknown_key_in_backup_section_is_rejected():
    raw = _minimal_raw()
    raw["backup"]["typo_field"] = "oops"

    with pytest.raises(ConfigError, match="typo_field"):
        parse_config(raw)


def test_wrong_type_is_rejected():
    raw = _minimal_raw()
    raw["backup"]["timeout_seconds"] = "not-an-int"

    with pytest.raises(ConfigError, match="timeout_seconds"):
        parse_config(raw)


def test_invalid_schema_version_is_rejected():
    raw = _minimal_raw(schema_version=99)

    with pytest.raises(ConfigError, match="schema_version"):
        parse_config(raw)


def test_no_destinations_is_rejected():
    raw = _minimal_raw(destinations=[])

    with pytest.raises(ConfigError, match="at least one"):
        parse_config(raw)


def test_duplicate_destination_name_is_rejected():
    raw = _minimal_raw(
        destinations=[
            {"name": "dup", "type": "local", "path": "/a", "keep": 1},
            {"name": "dup", "type": "local", "path": "/b", "keep": 1},
        ]
    )

    with pytest.raises(ConfigError, match="duplicate destination name 'dup'"):
        parse_config(raw)


def test_keep_zero_is_rejected():
    raw = _minimal_raw(destinations=[{"name": "local", "type": "local", "path": "/a", "keep": 0}])

    with pytest.raises(ConfigError, match="keep"):
        parse_config(raw)


def test_ssh_destination_requires_host_user_ssh_key():
    raw = _minimal_raw(destinations=[{"name": "remote", "type": "ssh", "path": "/a", "keep": 1}])

    with pytest.raises(ConfigError) as exc_info:
        parse_config(raw)

    message = str(exc_info.value)
    assert "host" in message
    assert "user" in message
    assert "ssh_key" in message


def test_ssh_destination_full_spec_parses():
    raw = _minimal_raw(
        destinations=[
            {
                "name": "remote",
                "type": "ssh",
                "path": "/backups",
                "keep": 14,
                "host": "db-master.example.com",
                "user": "backup",
                "ssh_key": "/etc/mbkeeper/id_ed25519",
                "port": 2222,
                "ssh_options": ["-o", "StrictHostKeyChecking=accept-new"],
                "bwlimit_kbps": 5000,
            }
        ]
    )

    config = parse_config(raw)

    dest = config.destinations[0]
    assert dest.host == "db-master.example.com"
    assert dest.port == 2222
    assert dest.ssh_options == ("-o", "StrictHostKeyChecking=accept-new")
    assert dest.bwlimit_kbps == 5000


def test_work_dir_colliding_with_local_destination_path_is_rejected():
    raw = _minimal_raw(
        backup={"work_dir": "/shared/path"},
        destinations=[{"name": "local", "type": "local", "path": "/shared/path", "keep": 1}],
    )

    with pytest.raises(ConfigError, match="work_dir"):
        parse_config(raw)


def test_reserved_mariabackup_arg_in_extra_args_is_rejected():
    raw = _minimal_raw()
    raw["backup"]["extra_args"] = ["--parallel=4", "--target-dir=/tmp/evil"]

    with pytest.raises(ConfigError, match="target-dir"):
        parse_config(raw)


def test_multiple_errors_are_collected_together():
    raw = _minimal_raw()
    del raw["backup"]["work_dir"]
    raw["logging"] = {"level": "not-a-level"}

    with pytest.raises(ConfigError) as exc_info:
        parse_config(raw)

    message = str(exc_info.value)
    assert "work_dir" in message
    assert "level" in message


def test_invalid_replication_mode_is_rejected():
    raw = _minimal_raw(replication={"mode": "bogus"})

    with pytest.raises(ConfigError, match="mode"):
        parse_config(raw)


def test_invalid_on_destination_failure_is_rejected():
    raw = _minimal_raw(transfer={"on_destination_failure": "bogus"})

    with pytest.raises(ConfigError, match="on_destination_failure"):
        parse_config(raw)
