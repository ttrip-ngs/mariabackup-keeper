from pathlib import Path

import pytest
from fakes import make_fake_mariabackup, succeeding_mariabackup
from mariabackup_keeper.cli import main


def _write_config(
    tmp_path: Path, mariabackup_path: str, keep: int = 5, replication_client: str = ""
) -> Path:
    config_path = tmp_path / "config.toml"
    replication_section = (
        f'\n[replication]\nclient_path = "{replication_client}"\n' if replication_client else ""
    )
    config_path.write_text(f"""
schema_version = 1

[backup]
work_dir = "{tmp_path / "work"}"
mariabackup_path = "{mariabackup_path}"
{replication_section}
[[destinations]]
name = "local"
type = "local"
path = "{tmp_path / "store"}"
keep = {keep}

[lock]
file = "{tmp_path / "mbkeeper.lock"}"
""")
    return config_path


def _fake_replication_client(tmp_path: Path) -> str:
    return make_fake_mariabackup(
        tmp_path,
        "import sys\n"
        "sql = sys.argv[-1]\n"
        "if 'VERSION' in sql: print('11.4.2-MariaDB')\n"
        "sys.exit(0)\n",
        name="fake-check-client.py",
    )


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


def test_main_list_reports_generations(tmp_path: Path, capsys):
    config_path = _write_config(tmp_path, succeeding_mariabackup(tmp_path))
    main(["run", "-c", str(config_path)])

    exit_code = main(["list", "-c", str(config_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "[local]" in output
    assert "complete" in output


def test_main_list_unknown_destination_filter_shows_nothing(tmp_path: Path, capsys):
    config_path = _write_config(tmp_path, succeeding_mariabackup(tmp_path))

    exit_code = main(["list", "-c", str(config_path), "--destination", "does-not-exist"])

    assert exit_code == 0
    assert capsys.readouterr().out == ""


def test_main_purge_deletes_beyond_keep(tmp_path: Path, capsys):
    config_path = _write_config(tmp_path, succeeding_mariabackup(tmp_path), keep=1)
    main(["run", "-c", str(config_path)])
    (tmp_path / "store" / "full-00000101T000000Z").mkdir(parents=True)
    (tmp_path / "store" / "full-00000101T000000Z" / "meta.json").write_text("{}")

    exit_code = main(["purge", "-c", str(config_path)])

    assert exit_code == 0
    assert not (tmp_path / "store" / "full-00000101T000000Z").exists()
    assert "deleted" in capsys.readouterr().out


def test_main_purge_dry_run_does_not_delete(tmp_path: Path, capsys):
    config_path = _write_config(tmp_path, succeeding_mariabackup(tmp_path), keep=1)
    main(["run", "-c", str(config_path)])
    (tmp_path / "store" / "full-00000101T000000Z").mkdir(parents=True)
    (tmp_path / "store" / "full-00000101T000000Z" / "meta.json").write_text("{}")

    exit_code = main(["purge", "-c", str(config_path), "--dry-run"])

    assert exit_code == 0
    assert (tmp_path / "store" / "full-00000101T000000Z").exists()
    assert "would delete" in capsys.readouterr().out


def test_main_check_reports_ok_and_returns_zero(tmp_path: Path, capsys):
    config_path = _write_config(
        tmp_path,
        succeeding_mariabackup(tmp_path),
        replication_client=_fake_replication_client(tmp_path),
    )

    exit_code = main(["check", "-c", str(config_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "[OK] mariabackup" in output
    assert "[OK] replication" in output
    assert "[OK] destination:local" in output


def test_main_check_returns_precondition_failed_when_mariabackup_missing(tmp_path: Path, capsys):
    config_path = _write_config(tmp_path, str(tmp_path / "does-not-exist"))

    exit_code = main(["check", "-c", str(config_path)])

    assert exit_code == 5
    assert "[FAIL] mariabackup" in capsys.readouterr().out
