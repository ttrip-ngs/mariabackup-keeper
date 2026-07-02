"""Backup generation naming and the per-generation meta.json manifest.

The backup_id embeds a UTC timestamp so lexicographic sort order equals time
order without depending on any destination's filesystem mtimes.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_SCHEMA_VERSION = 1
META_FILENAME = "meta.json"

_ID_TIME_FORMAT = "%Y%m%dT%H%M%SZ"


def generate_backup_id(prefix: str, now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware (UTC)")
    return f"{prefix}-{now.astimezone(timezone.utc).strftime(_ID_TIME_FORMAT)}"


@dataclass(frozen=True)
class BackupMeta:
    schema_version: int
    backup_id: str
    type: str
    status: str
    started_at: str
    finished_at: str
    hostname: str
    mariadb_version: str
    mariabackup_version: str
    prepared: bool
    size_bytes: int
    tool_version: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> BackupMeta:
        data = json.loads(text)
        known_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


def write_meta(target_dir: Path, meta: BackupMeta) -> None:
    (target_dir / META_FILENAME).write_text(meta.to_json())


def read_meta(target_dir: Path) -> BackupMeta | None:
    meta_path = target_dir / META_FILENAME
    if not meta_path.is_file():
        return None
    try:
        return BackupMeta.from_json(meta_path.read_text())
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def directory_size_bytes(path: Path) -> int:
    return sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())
