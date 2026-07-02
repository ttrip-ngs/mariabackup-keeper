"""Shared test doubles: a fake mariabackup executable, no real DB required."""

import logging
import stat
import sys
from pathlib import Path


def make_fake_mariabackup(tmp_path: Path, body: str, name: str = "fake-mariabackup.py") -> str:
    script = tmp_path / name
    script.write_text(f"#!{sys.executable}\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def succeeding_mariabackup(tmp_path: Path) -> str:
    return make_fake_mariabackup(tmp_path, "import sys; sys.stderr.write('completed OK!\\n')")


def failing_mariabackup(tmp_path: Path) -> str:
    return make_fake_mariabackup(tmp_path, "import sys; sys.stderr.write('boom\\n'); sys.exit(1)")


def hanging_mariabackup(tmp_path: Path) -> str:
    return make_fake_mariabackup(tmp_path, "import time; time.sleep(5)")


def null_logger() -> logging.Logger:
    logger = logging.getLogger(f"test-{id(object())}")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger
