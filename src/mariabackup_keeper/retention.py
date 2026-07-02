"""Purge decision logic. Pure functions only -- no I/O, no destination calls.

Decisions are made per destination (each has its own `keep`), never against a
central ledger: the destination's own directory listing is the only source
of truth, so a ledger can never drift out of sync with reality.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from mariabackup_keeper.destinations.base import StoredBackup


@dataclass(frozen=True)
class PurgePlan:
    keep: tuple[str, ...]
    delete: tuple[str, ...]


def select_purge(
    stored: list[StoredBackup],
    keep: int,
    grace_hours: int,
    now: datetime,
    in_progress_id: str | None = None,
) -> PurgePlan:
    """Decide which backup_ids to delete at one destination.

    Complete generations: newest `keep` (by backup_id, which sorts
    lexicographically = chronologically) are kept; the rest are deleted.
    Incomplete generations (no meta.json / still ".partial"): deleted once
    `grace_hours` has elapsed since they were last touched, unless they are
    the generation currently being written (`in_progress_id`).
    """
    complete = sorted((b for b in stored if b.complete), key=lambda b: b.backup_id, reverse=True)
    incomplete = [b for b in stored if not b.complete]

    keep_ids = [b.backup_id for b in complete[:keep]]
    delete_ids = [b.backup_id for b in complete[keep:]]

    grace = timedelta(hours=grace_hours)
    for backup in incomplete:
        if backup.backup_id == in_progress_id or now - backup.stored_at < grace:
            keep_ids.append(backup.backup_id)
        else:
            delete_ids.append(backup.backup_id)

    return PurgePlan(keep=tuple(keep_ids), delete=tuple(delete_ids))
