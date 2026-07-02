"""Single-instance execution lock via non-blocking flock.

Guards against overlapping cron/systemd-timer invocations on the same node.
"""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mariabackup_keeper.errors import LockError


@contextmanager
def acquire_lock(lock_path: Path) -> Iterator[None]:
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    fd = open(lock_path, "w")
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LockError(f"Another mbkeeper run holds the lock: {lock_path}") from exc
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
