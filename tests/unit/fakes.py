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


def make_fake_ssh_bin_dir(tmp_path: Path) -> Path:
    """A fake `ssh` that runs the "remote" command locally instead of over the
    network. Prepend the returned directory to PATH so subprocess.run(["ssh", ...])
    resolves to it. Only exercises the ssh-invocation wiring (mkdir/test/rm/mv,
    and rsync's own -e transport); it is not a substitute for the real
    ssh+rsync integration coverage in tests/integration.
    """
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "ssh"
    script.write_text(f"""#!{sys.executable}
import subprocess
import sys

argv = sys.argv[1:]
host_idx = next(i for i, a in enumerate(argv) if "@" in a)
remote = argv[host_idx + 1:]
if len(remote) == 1:
    result = subprocess.run(remote[0], shell=True)
else:
    result = subprocess.run(remote)
sys.exit(result.returncode)
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return bin_dir
