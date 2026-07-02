import multiprocessing
import time
from pathlib import Path

import pytest
from mariabackup_keeper.errors import LockError
from mariabackup_keeper.locking import acquire_lock


def test_acquire_lock_creates_parent_dir_and_succeeds(tmp_path: Path):
    lock_file = tmp_path / "nested" / "mbkeeper.lock"

    with acquire_lock(lock_file):
        assert lock_file.exists()


def test_acquire_lock_is_reentrant_after_release(tmp_path: Path):
    lock_file = tmp_path / "mbkeeper.lock"

    with acquire_lock(lock_file):
        pass
    with acquire_lock(lock_file):
        pass


def _hold_lock_for(lock_file: str, seconds: float) -> None:
    with acquire_lock(Path(lock_file)):
        time.sleep(seconds)


def test_acquire_lock_rejects_concurrent_holder(tmp_path: Path):
    lock_file = tmp_path / "mbkeeper.lock"

    holder = multiprocessing.Process(target=_hold_lock_for, args=(str(lock_file), 2))
    holder.start()
    try:
        time.sleep(0.5)
        with pytest.raises(LockError):
            with acquire_lock(lock_file):
                pass
    finally:
        holder.join(timeout=5)
