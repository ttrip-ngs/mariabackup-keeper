"""Runs the optional pre_backup/post_backup/pre_purge/post_run hook commands.

Only pre_backup aborts the run on failure (pass fail_fast=True at that call
site); a broken notification hook elsewhere must not block backups or purges.
"""

from __future__ import annotations

import logging
import shlex
import subprocess

from mariabackup_keeper.errors import PreconditionError

_HOOK_TIMEOUT_SECONDS = 60


def run_hook(
    command: str,
    logger: logging.Logger,
    stdin_data: str | None = None,
    fail_fast: bool = False,
) -> None:
    if not command:
        return

    try:
        argv = shlex.split(command)
    except ValueError as exc:
        _handle_failure(f"hook command could not be parsed: {command!r}: {exc}", logger, fail_fast)
        return

    try:
        proc = subprocess.run(
            argv, input=stdin_data, capture_output=True, text=True, timeout=_HOOK_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _handle_failure(f"hook '{command}' failed to execute: {exc}", logger, fail_fast)
        return

    if proc.returncode != 0:
        _handle_failure(
            f"hook '{command}' exited with code {proc.returncode}: {proc.stderr.strip()}",
            logger,
            fail_fast,
        )
    else:
        logger.debug(f"hook '{command}' completed")


def _handle_failure(message: str, logger: logging.Logger, fail_fast: bool) -> None:
    logger.error(message)
    if fail_fast:
        raise PreconditionError(message)
