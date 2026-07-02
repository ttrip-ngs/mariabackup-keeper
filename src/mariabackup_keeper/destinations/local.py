"""Local filesystem destination.

Uses a plain filesystem copy (not rsync) so single-node setups have zero
external process dependency. Commit protocol still mirrors the ssh backend:
copy into "<id>.partial", copy meta.json last, then atomically rename.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from mariabackup_keeper.config import DestinationConfig, TransferConfig
from mariabackup_keeper.destinations import register
from mariabackup_keeper.destinations.base import Destination, StoredBackup
from mariabackup_keeper.errors import DestinationError
from mariabackup_keeper.manifest import META_FILENAME

PARTIAL_SUFFIX = ".partial"
_CHECK_PROBE_FILENAME = ".mbkeeper-check"


@register("local")
class LocalDestination(Destination):
    def __init__(self, name: str, path: Path, keep: int) -> None:
        self.name = name
        self.path = Path(path)
        self.keep = keep

    @classmethod
    def from_config(cls, config: DestinationConfig, transfer: TransferConfig) -> LocalDestination:
        return cls(name=config.name, path=Path(config.path), keep=config.keep)

    def store(self, local_dir: Path, backup_id: str) -> None:
        final_dir = self.path / backup_id
        if (final_dir / META_FILENAME).is_file():
            return  # already complete: idempotent no-op

        try:
            self.path.mkdir(parents=True, exist_ok=True)
            partial_dir = self.path / f"{backup_id}{PARTIAL_SUFFIX}"
            if partial_dir.exists():
                shutil.rmtree(partial_dir)

            shutil.copytree(local_dir, partial_dir, ignore=shutil.ignore_patterns(META_FILENAME))
            meta_src = local_dir / META_FILENAME
            if meta_src.is_file():
                shutil.copy2(meta_src, partial_dir / META_FILENAME)
            partial_dir.rename(final_dir)
        except OSError as exc:
            raise DestinationError(f"destination '{self.name}': store failed: {exc}") from exc

    def list_backups(self) -> list[StoredBackup]:
        if not self.path.is_dir():
            raise DestinationError(f"destination '{self.name}': path does not exist: {self.path}")

        results = []
        for entry in self.path.iterdir():
            if not entry.is_dir():
                continue
            if entry.name.endswith(PARTIAL_SUFFIX):
                backup_id = entry.name[: -len(PARTIAL_SUFFIX)]
                complete = False
            else:
                backup_id = entry.name
                complete = (entry / META_FILENAME).is_file()
            stored_at = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            results.append(
                StoredBackup(backup_id=backup_id, complete=complete, stored_at=stored_at)
            )
        return results

    def delete(self, backup_id: str) -> None:
        for name in (backup_id, f"{backup_id}{PARTIAL_SUFFIX}"):
            target = self.path / name
            if target.exists():
                try:
                    shutil.rmtree(target)
                except OSError as exc:
                    raise DestinationError(
                        f"destination '{self.name}': delete failed: {exc}"
                    ) from exc

    def check(self) -> None:
        try:
            self.path.mkdir(parents=True, exist_ok=True)
            probe = self.path / _CHECK_PROBE_FILENAME
            probe.write_text("ok")
            probe.unlink()
        except OSError as exc:
            raise DestinationError(f"destination '{self.name}': check failed: {exc}") from exc
