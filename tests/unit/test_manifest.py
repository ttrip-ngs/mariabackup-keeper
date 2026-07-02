import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from mariabackup_keeper.manifest import (
    MANIFEST_SCHEMA_VERSION,
    BackupMeta,
    directory_size_bytes,
    generate_backup_id,
    read_meta,
    write_meta,
)


def test_generate_backup_id_format():
    now = datetime(2026, 7, 2, 18, 0, 0, tzinfo=timezone.utc)
    assert generate_backup_id("full", now) == "full-20260702T180000Z"


def test_generate_backup_id_requires_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        generate_backup_id("full", datetime(2026, 7, 2, 18, 0, 0))


def test_generate_backup_id_sorts_lexicographically_by_time():
    earlier = generate_backup_id("full", datetime(2026, 7, 2, 18, 0, 0, tzinfo=timezone.utc))
    later = generate_backup_id("full", datetime(2026, 7, 2, 19, 0, 0, tzinfo=timezone.utc))
    assert sorted([later, earlier]) == [earlier, later]


def _sample_meta(backup_id: str = "full-20260702T180000Z") -> BackupMeta:
    return BackupMeta(
        schema_version=MANIFEST_SCHEMA_VERSION,
        backup_id=backup_id,
        type="full",
        status="complete",
        started_at="2026-07-02T18:00:00+00:00",
        finished_at="2026-07-02T18:05:00+00:00",
        hostname="db-replica-1",
        mariadb_version="",
        mariabackup_version="mariabackup 11.4.0",
        prepared=True,
        size_bytes=123,
        tool_version="mariabackup-keeper 0.1.0",
    )


def test_write_and_read_meta_roundtrip(tmp_path: Path):
    meta = _sample_meta()

    write_meta(tmp_path, meta)
    loaded = read_meta(tmp_path)

    assert loaded == meta


def test_read_meta_returns_none_when_missing(tmp_path: Path):
    assert read_meta(tmp_path) is None


def test_read_meta_returns_none_on_corrupt_json(tmp_path: Path):
    (tmp_path / "meta.json").write_text("{not valid json")

    assert read_meta(tmp_path) is None


def test_read_meta_ignores_unknown_future_fields(tmp_path: Path):
    meta = _sample_meta()
    write_meta(tmp_path, meta)
    data = json.loads((tmp_path / "meta.json").read_text())
    data["future_field_from_newer_schema"] = "value"
    (tmp_path / "meta.json").write_text(json.dumps(data))

    assert read_meta(tmp_path) == meta


def test_directory_size_bytes_sums_files_recursively(tmp_path: Path):
    (tmp_path / "a.ibd").write_bytes(b"x" * 100)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.ibd").write_bytes(b"y" * 50)

    assert directory_size_bytes(tmp_path) == 150
