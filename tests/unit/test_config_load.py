from pathlib import Path

import pytest
from mariabackup_keeper.config import load_config
from mariabackup_keeper.errors import ConfigError

VALID_TOML = """
schema_version = 1

[backup]
work_dir = "/var/lib/mbkeeper/work"

[[destinations]]
name = "local"
type = "local"
path = "/var/backups/store"
keep = 7
"""


def test_load_config_reads_and_parses_valid_toml(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(VALID_TOML)

    config = load_config(config_path)

    assert config.schema_version == 1
    assert config.destinations[0].name == "local"


def test_load_config_missing_file_raises_config_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "does-not-exist.toml")


def test_load_config_malformed_toml_raises_config_error(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("this is not [valid toml")

    with pytest.raises(ConfigError, match="parse"):
        load_config(config_path)
