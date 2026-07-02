# mariabackup-keeper

`mariabackup-keeper` (CLI: `mbkeeper`) orchestrates [MariaDB's
`mariabackup`](https://mariadb.com/kb/en/mariabackup/) for scheduled backups.
It does not take backups itself -- `mariabackup` does that -- its job is
everything around it: a scheduling entry point for cron/systemd timers,
generation retention (purge), structured logging, explicit exit codes, and
**cross-backup**: taking a backup on a replica while placing copies on both
the local node and a remote node (e.g. the master, or a separate site), so a
single node failure never means losing your only backup copy.

> This project is an independent, unofficial tool and is not affiliated
> with, endorsed by, or sponsored by MariaDB plc. See
> [Trademark notice](#trademark-notice) below.

## Status

Early-stage / MVP. Full backups, generation retention, and cross-backup are
implemented and unit-tested. The Docker-based integration test suite
(`tests/integration/`) exists but has not yet been run end-to-end in an
environment with a working Docker daemon -- see
[`memo/history/005-m5-integration-tests-and-ci.md`](memo/history/005-m5-integration-tests-and-ci.md)
for exactly what to verify first. Incremental backups, cloud storage
destinations, and monitoring integrations are intentionally out of scope for
now; see [`docs/design.md`](docs/design.md) for the extension points that
keep those additions non-breaking later.

## Why

Existing backup-scheduling tools for MariaDB/MySQL (e.g. Holland) are solid
at "run mariabackup, keep N generations locally," but weak at treating
*where a backup is stored* as a first-class, pluggable concern. In an HA
replication setup, you want to back up on a replica (to avoid load on the
primary) while still ending up with a copy on the primary's site or a DR
site -- without hand-rolling rsync/cron glue for it. That's the one thing
this tool is built around.

## Installation

Requires Python 3.9+ and a working `mariabackup` (or `mariadb-backup`)
installation. `rsync` and an SSH client are required only if you use an
`ssh`-type destination.

```bash
pip install mariabackup-keeper
```

Or from source:

```bash
git clone https://github.com/ttrip/mariabackup-keeper.git
cd mariabackup-keeper
pip install .
```

## Quick start

Write a config file (default path `/etc/mbkeeper/config.toml`, override with
`-c`):

```toml
schema_version = 1

[backup]
work_dir = "/var/lib/mbkeeper/work"
defaults_extra_file = "/etc/mbkeeper/client.cnf"  # [client] user/password for mariabackup

[[destinations]]
name = "local"
type = "local"
path = "/var/backups/mbkeeper/local"
keep = 7

[[destinations]]
name = "master-dr"
type = "ssh"
host = "db-master.example.com"
user = "backup"
path = "/var/backups/mbkeeper/from-replica"
ssh_key = "/etc/mbkeeper/id_ed25519"
keep = 14

[lock]
file = "/run/mbkeeper/mbkeeper.lock"
```

Then:

```bash
mbkeeper check -c /etc/mbkeeper/config.toml   # validate config, probe mariabackup/replication/destinations
mbkeeper run -c /etc/mbkeeper/config.toml     # backup -> store to every destination -> purge
```

Wire `mbkeeper run` into cron or a systemd timer for scheduled backups. See
[`docs/operations.md`](docs/operations.md) for a full example, including SSH
key setup for cross-backup.

Full config schema: [`docs/configuration.md`](docs/configuration.md).
Exit codes (useful for monitoring cron/timer failures):
[`docs/exit-codes.md`](docs/exit-codes.md).

## CLI commands

| Command | What it does |
|---|---|
| `mbkeeper run -c CONFIG` | Full pipeline: acquire lock, precondition checks, backup, store to every destination, purge |
| `mbkeeper purge -c CONFIG [--destination NAME] [--dry-run]` | Purge only, without taking a new backup |
| `mbkeeper list -c CONFIG [--destination NAME]` | List generations known to each destination |
| `mbkeeper check -c CONFIG` | Validate config and probe mariabackup / replication / each destination -- run this before wiring up cron |

## Architecture, briefly

- **Backup** (`mariabackup` invocation), **placement** (destinations), and
  **retention** (purge) are deliberately decoupled: none of them import each
  other. `orchestrator.py` is the only module that wires them together.
- A `Destination` is an abstraction over "where a generation ends up" --
  `local` and `ssh` today, with the same interface ready for a future cloud
  storage backend. Placement is atomic (write to `<id>.partial`, commit by
  rename) and idempotent, so an interrupted transfer can simply be retried.
- Retention decisions are a pure function (`retention.select_purge`) over
  what a destination reports it holds -- there is no separate ledger that
  can drift out of sync with what's actually on disk.

Full design rationale: [`docs/design.md`](docs/design.md).

## Testing

Three layers, kept from diverging:

- **Unit** (`tests/unit/`, no real DB): `make test`. Fakes a `mariabackup`
  binary via a throwaway Python script so retention/config/orchestration
  logic can be tested without any database.
- **Local integration** (`tests/integration/`, Docker required, disposable):
  `make integration`. Spins up a primary/replica pair plus an SSH
  destination node, runs real `mariabackup`/`rsync`/`ssh`, and tears
  everything down afterwards.
- **CI** (`.github/workflows/ci.yml`): runs the unit matrix across
  supported Python versions and calls the *exact same*
  `tests/integration/run.sh` across a MariaDB version matrix (10.11, 11.4)
  -- so local and CI integration testing never drift into two different
  test suites.

## Responsibility split

This project's CI verifies backup -> cross-backup -> restore -> checksum
correctness against representative configurations (single node,
primary/replica, MariaDB 10.11 and 11.4). **It cannot verify your specific
data, schema, or environment.** Restore-testing your production backups,
on your own infrastructure, on a schedule you're comfortable with, is your
responsibility as the operator -- this tool getting backups onto disk is
necessary but not sufficient for a working disaster-recovery plan.

## License

MIT. See [`LICENSE`](LICENSE). Provided as-is, without warranty -- see the
license text for the full disclaimer.

## Trademark notice

This project is an independent, community-maintained tool and is **not
affiliated with, endorsed by, or sponsored by MariaDB plc**. "MariaDB" is a
registered trademark of MariaDB plc; its use in this project's name and
documentation is solely descriptive, to indicate interoperability with
`mariabackup`/MariaDB Server, and does not imply any official relationship.
This project does not use MariaDB's logo or trade dress, and does not
describe itself as "official" or "certified."
