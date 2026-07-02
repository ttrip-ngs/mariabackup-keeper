# Design

This document explains the architecture and the reasoning behind it. For
the full config schema see [configuration.md](configuration.md), for exit
codes see [exit-codes.md](exit-codes.md), for deployment see
[operations.md](operations.md).

## Scope

`mariabackup-keeper` orchestrates `mariabackup`; it does not replace it.
Its responsibilities are everything *around* taking a backup:

- a scheduling entry point for cron/systemd timers (`mbkeeper run`)
- generation retention / purge
- placing a generation on multiple destinations, including a remote node
  over SSH (cross-backup)
- declarative TOML configuration
- structured logging and unambiguous exit codes

MVP scope stops at full backups. Incremental backups, cloud storage
destinations, and monitoring integrations are explicitly out of scope for
now (see [Extension points](#extension-points)), to avoid building
generality the project doesn't need yet.

## Module map

Backup acquisition, destination placement, and retention are deliberately
decoupled -- none of `backup.py`, `destinations/*.py`, or `retention.py`
import each other. `orchestrator.py` is the only module that wires them
together into the `run`/`purge`/`check` pipelines.

| Module | Responsibility |
|---|---|
| `cli.py` | argparse only: parse args, load config, dispatch to orchestrator, map exceptions to exit codes. No pipeline logic. |
| `config.py` | TOML -> validated, frozen dataclasses. Unknown keys are rejected; all validation errors are collected and reported together, not one at a time. |
| `orchestrator.py` | Pipeline sequencing (`run`, `purge`, `check`) and exit-code decisions. The only module allowed to import backup + destinations + retention + replication + hooks together. |
| `backup.py` | `MariabackupRunner`: builds `mariabackup` argv, runs it, decides success/failure, handles timeouts. |
| `manifest.py` | Generation ID naming (`{prefix}-{UTC timestamp}`, lexicographic sort = chronological) and `meta.json` read/write. |
| `destinations/base.py` | The `Destination` ABC and `StoredBackup` dataclass every backend implements. |
| `destinations/local.py`, `destinations/ssh.py` | Concrete backends. Registered into `destinations/__init__.py`'s `DESTINATION_TYPES` via `@register("type")`. |
| `retention.py` | `select_purge()`: a pure function, no I/O, deciding what to keep/delete given a destination's own listing. |
| `replication.py` | `SHOW REPLICA STATUS` / lag check, enforcing `[replication].mode` and `max_lag_seconds`. |
| `hooks.py` | Runs the four optional hook commands. |
| `locking.py` | `flock`-based single-instance lock. |
| `logging_setup.py`, `exit_codes.py`, `errors.py` | Cross-cutting: structured logging, the `ExitCode` enum, and the `KeeperError` hierarchy that maps 1:1 onto it. |

## The `Destination` abstraction

```python
class Destination(ABC):
    name: str
    keep: int

    def store(self, local_dir: Path, backup_id: str) -> None: ...
    def list_backups(self) -> list[StoredBackup]: ...
    def delete(self, backup_id: str) -> None: ...
    def check(self) -> None: ...
```

`local` and `ssh` are the two backends today; a future cloud storage backend
(S3/GCS/etc.) implements the same four methods and registers itself the
same way -- no other module needs to change.

### Placement protocol

Both backends commit the same way, so purge's completeness check works
identically everywhere:

1. If `<backup_id>/meta.json` already exists at the destination, `store()`
   is a no-op (idempotent -- safe to retry a whole run).
2. Copy everything except `meta.json` into `<backup_id>.partial/`.
3. Copy `meta.json` in last.
4. Rename `<backup_id>.partial` -> `<backup_id>` (atomic on both a local
   filesystem and over SSH, since `mv`/`rename()` within one filesystem is
   atomic).

A generation is "complete" if and only if its directory doesn't end in
`.partial` and contains `meta.json`. This is the single completeness check
used everywhere (retention, `list`, `check`) -- there's no separate ledger
tracking what's been transferred, which means the ledger can never drift
out of sync with what's actually on disk.

`local.py` uses plain `shutil` (no external process) so a single-node setup
has zero extra dependencies. `ssh.py` uses `rsync -a --partial --delete`
over `ssh` for the data, then a single-file `rsync` for `meta.json`, then a
remote `mv`; retries are `[transfer].retries` rsync re-runs, which resume
via `--partial`.

## Retention / purge

`retention.select_purge(stored, keep, grace_hours, now, in_progress_id)` is
a pure function: sort complete generations by `backup_id` (newest first),
keep the first `keep`, delete the rest. Incomplete generations
(`.partial` or missing `meta.json`) are deleted once `grace_hours` has
passed since they were last touched, unless they're the generation
currently being written.

Purge is per-destination and independent -- each destination has its own
`keep`, and there's no cross-destination bookkeeping. If a destination's
`list_backups()` fails, purge is skipped for that destination entirely
(never delete what you can't currently see). A destination this run failed
to *store* to is also skipped for purge -- don't shrink an already-degraded
copy further.

## Cross-backup and failure policy

The acquiring node and its destinations are decoupled by design: `[[destinations]]`
is just a list, and `local` is treated as "a destination" like any other
(same placement protocol, same purge logic) rather than special-cased.

Replication is handled narrowly on purpose:

- `[replication].mode = "require_replica"` refuses to run if `SHOW REPLICA
  STATUS` is empty (guards against accidentally cron'ing this on a
  primary).
- `[replication].max_lag_seconds` refuses to run if lag exceeds the
  threshold or is unknown (replication stopped).
- `safe_slave_backup` passes `--safe-slave-backup` to `mariabackup`.

Explicitly not attempted: replica auto-selection, failover, or independent
GTID bookkeeping (mariabackup already writes that into the generation).

`[transfer].on_destination_failure` defaults to `"continue"`
(best-effort): every destination is attempted regardless of earlier
failures, since cross-backup's whole point is redundancy -- a remote outage
shouldn't take the local copy down with it. `"abort"` stops at the first
failure for operators who prefer fail-fast. Exit codes distinguish "all
destinations failed" (7, work_dir preserved so the only copy isn't lost)
from "some destinations failed" (8, a warning, not a page).

## Extension points

| Future feature | What's already in place |
|---|---|
| Incremental backups | `meta.json`'s `type`/`schema_version` fields; `type: "incr"` + a `base_id` field is additive. `retention.select_purge`'s signature (list of `StoredBackup` -> a plan) stays the same; a chain-aware policy (never delete a base before its children) replaces the body, not the interface. |
| Cloud storage destinations | The `Destination` ABC. A new backend implements the same four methods; the placement protocol (partial -> commit marker) maps onto object storage the same way (`meta.json` PUT last). |
| Monitoring integrations | Three things already exist: the `ExitCode` enum, `[logging].format = "json"`, and `[hooks].post_run` (receives a JSON run summary on stdin). No plugin system needed for a first integration. |
| Destination plugin loading | Today `DESTINATION_TYPES` is a plain dict populated by `@register`. Swapping in an `entry_points`-based loader later only touches `destinations/__init__.py`. |
