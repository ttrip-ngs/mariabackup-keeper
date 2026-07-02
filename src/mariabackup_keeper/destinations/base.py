"""Destination contract shared by local, ssh, and future (cloud) backends.

store() must be idempotent and commit atomically (partial dir -> rename) so
interrupted transfers can be safely retried without corrupting a prior
complete generation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mariabackup_keeper.config import DestinationConfig, TransferConfig


@dataclass(frozen=True)
class StoredBackup:
    backup_id: str
    complete: bool
    stored_at: datetime


class Destination(ABC):
    name: str
    keep: int

    @classmethod
    @abstractmethod
    def from_config(cls, config: DestinationConfig, transfer: TransferConfig) -> Destination: ...

    @abstractmethod
    def store(self, local_dir: Path, backup_id: str) -> None: ...

    @abstractmethod
    def list_backups(self) -> list[StoredBackup]: ...

    @abstractmethod
    def delete(self, backup_id: str) -> None: ...

    @abstractmethod
    def check(self) -> None: ...
