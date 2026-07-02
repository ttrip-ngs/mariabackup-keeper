from pathlib import Path

import pytest
from fakes import null_logger
from mariabackup_keeper.errors import PreconditionError
from mariabackup_keeper.hooks import run_hook


def test_empty_command_is_a_no_op():
    run_hook("", null_logger())  # must not raise


def test_successful_hook_runs_and_does_not_raise(tmp_path: Path):
    marker = tmp_path / "ran"
    run_hook(f"touch {marker}", null_logger())

    assert marker.exists()


def test_failing_hook_logs_but_does_not_raise_by_default():
    run_hook("false", null_logger())  # fail_fast defaults to False


def test_failing_hook_raises_precondition_error_when_fail_fast():
    with pytest.raises(PreconditionError):
        run_hook("false", null_logger(), fail_fast=True)


def test_missing_binary_does_not_raise_by_default(tmp_path: Path):
    run_hook(str(tmp_path / "does-not-exist"), null_logger())


def test_missing_binary_raises_when_fail_fast(tmp_path: Path):
    with pytest.raises(PreconditionError):
        run_hook(str(tmp_path / "does-not-exist"), null_logger(), fail_fast=True)


def test_stdin_data_is_passed_to_hook(tmp_path: Path):
    output_file = tmp_path / "captured.txt"
    script = tmp_path / "capture.sh"
    script.write_text(f"#!/bin/sh\ncat > {output_file}\n")
    script.chmod(0o755)

    run_hook(str(script), null_logger(), stdin_data='{"backup_id": "full-1"}')

    assert output_file.read_text() == '{"backup_id": "full-1"}'


def test_unparseable_command_does_not_raise_by_default():
    run_hook("unterminated 'quote", null_logger())


def test_unparseable_command_raises_when_fail_fast():
    with pytest.raises(PreconditionError):
        run_hook("unterminated 'quote", null_logger(), fail_fast=True)
