from datetime import datetime, timedelta, timezone

from mariabackup_keeper.destinations.base import StoredBackup
from mariabackup_keeper.retention import select_purge

_NOW = datetime(2026, 7, 2, 18, 0, 0, tzinfo=timezone.utc)


def _complete(backup_id: str) -> StoredBackup:
    return StoredBackup(backup_id=backup_id, complete=True, stored_at=_NOW)


def _partial(backup_id: str, stored_at: datetime) -> StoredBackup:
    return StoredBackup(backup_id=backup_id, complete=False, stored_at=stored_at)


def test_keeps_newest_n_complete_generations():
    stored = [_complete(f"full-{i:02d}") for i in range(1, 6)]  # full-01..full-05

    plan = select_purge(stored, keep=3, grace_hours=24, now=_NOW)

    assert set(plan.keep) == {"full-05", "full-04", "full-03"}
    assert set(plan.delete) == {"full-02", "full-01"}


def test_safety_valve_deletes_nothing_when_complete_count_at_or_below_keep():
    stored = [_complete("full-01"), _complete("full-02")]

    plan = select_purge(stored, keep=5, grace_hours=24, now=_NOW)

    assert plan.delete == ()
    assert set(plan.keep) == {"full-01", "full-02"}


def test_exact_keep_boundary_deletes_nothing():
    stored = [_complete("full-01"), _complete("full-02"), _complete("full-03")]

    plan = select_purge(stored, keep=3, grace_hours=24, now=_NOW)

    assert plan.delete == ()


def test_incomplete_generation_kept_within_grace_period():
    stored = [_partial("full-99", stored_at=_NOW - timedelta(hours=1))]

    plan = select_purge(stored, keep=5, grace_hours=24, now=_NOW)

    assert plan.keep == ("full-99",)
    assert plan.delete == ()


def test_incomplete_generation_deleted_after_grace_period():
    stored = [_partial("full-99", stored_at=_NOW - timedelta(hours=25))]

    plan = select_purge(stored, keep=5, grace_hours=24, now=_NOW)

    assert plan.delete == ("full-99",)
    assert plan.keep == ()


def test_incomplete_generation_at_exact_grace_boundary_is_deleted():
    stored = [_partial("full-99", stored_at=_NOW - timedelta(hours=24))]

    plan = select_purge(stored, keep=5, grace_hours=24, now=_NOW)

    assert plan.delete == ("full-99",)


def test_in_progress_generation_is_never_deleted_even_past_grace():
    stored = [_partial("full-current", stored_at=_NOW - timedelta(hours=100))]

    plan = select_purge(stored, keep=5, grace_hours=24, now=_NOW, in_progress_id="full-current")

    assert plan.keep == ("full-current",)
    assert plan.delete == ()


def test_mixed_complete_and_incomplete_generations():
    stored = [
        _complete("full-05"),
        _complete("full-04"),
        _complete("full-03"),
        _complete("full-02"),
        _partial("full-06", stored_at=_NOW - timedelta(hours=1)),  # in-progress, within grace
        _partial("full-01-stale", stored_at=_NOW - timedelta(hours=48)),  # stale leftover
    ]

    plan = select_purge(stored, keep=2, grace_hours=24, now=_NOW, in_progress_id="full-06")

    assert set(plan.keep) == {"full-05", "full-04", "full-06"}
    assert set(plan.delete) == {"full-03", "full-02", "full-01-stale"}


def test_empty_stored_list_produces_empty_plan():
    plan = select_purge([], keep=5, grace_hours=24, now=_NOW)

    assert plan.keep == ()
    assert plan.delete == ()
