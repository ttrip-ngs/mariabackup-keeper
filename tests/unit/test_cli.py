from pathlib import Path

import pytest
from fakes import succeeding_mariabackup
from mariabackup_keeper.cli import main


def _write_config(tmp_path: Path, mariabackup_path: str) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(f"""
schema_version = 1

[backup]
work_dir = "{tmp_path / "work"}"
mariabackup_path = "{mariabackup_path}"

[[destinations]]
name = "local"
type = "local"
path = "{tmp_path / "store"}"
keep = 5

[lock]
file = "{tmp_path / "mbkeeper.lock"}"
""")
    return config_path


def test_main_run_success_returns_zero(tmp_path: Path):
    config_path = _write_config(tmp_path, succeeding_mariabackup(tmp_path))

    exit_code = main(["run", "-c", str(config_path)])

    assert exit_code == 0
    assert (tmp_path / "store").is_dir()


def test_main_missing_config_returns_config_error_exit_code(tmp_path: Path):
    exit_code = main(["run", "-c", str(tmp_path / "missing.toml")])

    assert exit_code == 3


def test_main_version_flag_prints_version_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert "mbkeeper" in capsys.readouterr().out


def test_main_no_subcommand_is_usage_error(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 2
