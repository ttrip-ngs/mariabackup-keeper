from pathlib import Path

import pytest
from mariabackup_keeper.config import DestinationConfig, TransferConfig
from mariabackup_keeper.destinations.local import LocalDestination
from mariabackup_keeper.errors import DestinationError


def _make_generation(base: Path, backup_id: str, with_meta: bool = True) -> Path:
    gen_dir = base / backup_id
    gen_dir.mkdir(parents=True)
    (gen_dir / "ibdata1").write_bytes(b"data")
    if with_meta:
        (gen_dir / "meta.json").write_text("{}")
    return gen_dir


def test_from_config_builds_destination_with_path_and_keep(tmp_path: Path):
    config = DestinationConfig(name="local", type="local", path=str(tmp_path / "store"), keep=5)

    dest = LocalDestination.from_config(config, TransferConfig())

    assert dest.name == "local"
    assert dest.keep == 5
    assert dest.path == tmp_path / "store"


def test_store_copies_generation_and_commits_atomically(tmp_path: Path):
    gen_dir = _make_generation(tmp_path / "work", "full-1")
    store_dir = tmp_path / "store"
    dest = LocalDestination("local", store_dir, keep=5)

    dest.store(gen_dir, "full-1")

    assert (store_dir / "full-1" / "meta.json").is_file()
    assert (store_dir / "full-1" / "ibdata1").is_file()
    assert not (store_dir / "full-1.partial").exists()


def test_store_is_idempotent_when_already_complete(tmp_path: Path):
    gen_dir = _make_generation(tmp_path / "work", "full-1")
    store_dir = tmp_path / "store"
    dest = LocalDestination("local", store_dir, keep=5)
    dest.store(gen_dir, "full-1")
    (store_dir / "full-1" / "ibdata1").write_bytes(b"untouched-marker")

    dest.store(gen_dir, "full-1")

    assert (store_dir / "full-1" / "ibdata1").read_bytes() == b"untouched-marker"


def test_store_replaces_stale_partial_directory(tmp_path: Path):
    gen_dir = _make_generation(tmp_path / "work", "full-1")
    store_dir = tmp_path / "store"
    dest = LocalDestination("local", store_dir, keep=5)
    stale_partial = store_dir / "full-1.partial"
    stale_partial.mkdir(parents=True)
    (stale_partial / "leftover.tmp").write_bytes(b"junk")

    dest.store(gen_dir, "full-1")

    assert (store_dir / "full-1" / "meta.json").is_file()
    assert not stale_partial.exists()


def test_list_backups_distinguishes_complete_and_partial(tmp_path: Path):
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "full-1").mkdir()
    (store_dir / "full-1" / "meta.json").write_text("{}")
    (store_dir / "full-2.partial").mkdir()
    dest = LocalDestination("local", store_dir, keep=5)

    backups = {b.backup_id: b for b in dest.list_backups()}

    assert backups["full-1"].complete is True
    assert backups["full-2"].complete is False


def test_list_backups_raises_when_path_missing(tmp_path: Path):
    dest = LocalDestination("local", tmp_path / "missing", keep=5)

    with pytest.raises(DestinationError):
        dest.list_backups()


def test_delete_removes_complete_and_partial_variants(tmp_path: Path):
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "full-1").mkdir()
    (store_dir / "full-2.partial").mkdir()
    dest = LocalDestination("local", store_dir, keep=5)

    dest.delete("full-1")
    dest.delete("full-2")

    assert not (store_dir / "full-1").exists()
    assert not (store_dir / "full-2.partial").exists()


def test_delete_is_idempotent_when_absent(tmp_path: Path):
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    dest = LocalDestination("local", store_dir, keep=5)

    dest.delete("does-not-exist")  # must not raise


def test_check_creates_path_and_leaves_no_probe_file(tmp_path: Path):
    store_dir = tmp_path / "store"
    dest = LocalDestination("local", store_dir, keep=5)

    dest.check()

    assert store_dir.is_dir()
    assert not (store_dir / ".mbkeeper-check").exists()


def test_check_raises_destination_error_when_path_not_writable(tmp_path: Path):
    readonly_parent = tmp_path / "readonly"
    readonly_parent.mkdir()
    readonly_parent.chmod(0o500)
    dest = LocalDestination("local", readonly_parent / "store", keep=5)

    try:
        with pytest.raises(DestinationError):
            dest.check()
    finally:
        readonly_parent.chmod(0o700)
