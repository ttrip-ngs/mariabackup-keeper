# Configuration reference

`mbkeeper` reads a single TOML file (default `/etc/mbkeeper/config.toml`,
override with `-c`/`--config`). Unknown keys are rejected and all
validation errors are reported together, not one at a time.

## `schema_version`

Required. Must be `1`.

## `[backup]`

| Key | Default | Notes |
|---|---|---|
| `work_dir` | *(required)* | Local working directory for taking + preparing a generation before it's placed at any destination. Must not equal any `local` destination's `path`. |
| `name_prefix` | `"full"` | Generation ID = `"{name_prefix}-{UTC timestamp}"`, e.g. `full-20260702T180000Z`. |
| `mariabackup_path` | `"mariabackup"` | Path to the `mariabackup` binary. |
| `defaults_file` | `""` | Passed as `--defaults-file`; empty means omitted. |
| `defaults_extra_file` | `""` | Passed as `--defaults-extra-file`. **Put DB credentials here, never in this config file.** |
| `extra_args` | `[]` | Extra `mariabackup` arguments, e.g. `["--parallel=4"]`. Reserved arguments (`--backup`, `--prepare`, `--target-dir`, `--password`) are rejected. |
| `prepare` | `true` | Run `--prepare` immediately after `--backup` so the generation is restorable standalone. |
| `timeout_seconds` | `0` | `0` = no timeout. On timeout: SIGTERM, 10s grace, then SIGKILL; the run is marked failed. |

## `[replication]`

All fields are optional and default to "don't check anything."

| Key | Default | Notes |
|---|---|---|
| `mode` | `"off"` | `"off"` or `"require_replica"`. `require_replica` refuses to run if `SHOW REPLICA STATUS` is empty. |
| `max_lag_seconds` | `0` | `0` = no check. Otherwise refuses to run if `Seconds_Behind_Master` exceeds this or is unknown. |
| `safe_slave_backup` | `true` | Adds `--safe-slave-backup` to the `mariabackup` invocation when `mode != "off"`. |
| `client_path` | `"mariadb"` | Client binary used to query replication status / server version. |

**Note:** when `mode = "off"` and `max_lag_seconds = 0` (the default), `mbkeeper run`
never invokes the replication client at all -- a plain single-node setup has
no forced DB-connectivity dependency for this check. `mbkeeper check`
always probes it, since that command's job is to surface connectivity
problems proactively.

## `[transfer]`

| Key | Default | Notes |
|---|---|---|
| `on_destination_failure` | `"continue"` | `"continue"` (best-effort: try every destination regardless of earlier failures) or `"abort"` (stop at the first failure). |
| `retries` | `2` | Retries per destination for the data-transfer step (rsync-based destinations only). |
| `rsync_path` | `"rsync"` | Path to the `rsync` binary, used by `ssh`-type destinations. |

## `[retention]`

| Key | Default | Notes |
|---|---|---|
| `incomplete_grace_hours` | `24` | An incomplete generation (`.partial` or missing `meta.json`) is only purged once this many hours have passed since it was last touched. Protects a generation still being transferred. |

## `[[destinations]]`

At least one required. `name` must be unique across all destinations.

Common to both types:

| Key | Default | Notes |
|---|---|---|
| `name` | *(required)* | Unique identifier, used in logs and `mbkeeper list`/`purge --destination`. |
| `type` | *(required)* | `"local"` or `"ssh"`. |
| `path` | *(required)* | Local filesystem path (`local`) or remote path (`ssh`). |
| `keep` | *(required, >= 1)* | Generations to retain **at this destination**. Independent per destination. |

`type = "ssh"` additionally requires:

| Key | Default | Notes |
|---|---|---|
| `host` | *(required)* | Remote hostname/IP. |
| `user` | *(required)* | Remote SSH user. |
| `ssh_key` | *(required)* | Private key path. Password auth is not supported. |
| `port` | `22` | |
| `ssh_options` | `[]` | Extra `ssh` arguments, e.g. `["-o", "StrictHostKeyChecking=accept-new"]`. `BatchMode=yes` is always added so a stuck prompt can never hang a run. |
| `bwlimit_kbps` | `0` | Passed as `rsync --bwlimit`. `0` = unlimited. |

## `[logging]`

| Key | Default | Notes |
|---|---|---|
| `level` | `"info"` | `debug` \| `info` \| `warning` \| `error`. |
| `format` | `"text"` | `"text"` or `"json"` (one JSON object per line -- the basis for monitoring integration). |
| `file` | `""` | Empty = stderr only. When set, logs go to both stderr and this file. |

## `[lock]`

| Key | Default | Notes |
|---|---|---|
| `file` | `"/run/mbkeeper/mbkeeper.lock"` | `flock`-based single-instance lock; guards against overlapping cron invocations. |

## `[hooks]`

All optional; empty string means "don't run." Only `pre_backup` failing
aborts the run -- the other three log an error and continue, since a broken
notification hook shouldn't block backups or purges.

| Key | Runs | On failure |
|---|---|---|
| `pre_backup` | Before acquiring the backup | Aborts the run |
| `post_backup` | After a successful backup + prepare, before placement | Logged, run continues |
| `pre_purge` | Immediately before purge | Logged, run continues |
| `post_run` | Always, at the very end of `mbkeeper run` (even on backup failure), receives a JSON run summary on stdin | Logged, run continues |

Hook commands are parsed with `shlex.split` (no shell involved), so simple
`"/path/to/script --flag"` forms work; shell features (pipes, redirects,
variable expansion) are not available -- write a wrapper script if you need
them.

## Example

```toml
schema_version = 1

[backup]
work_dir = "/var/lib/mbkeeper/work"
defaults_extra_file = "/etc/mbkeeper/client.cnf"

[replication]
mode = "require_replica"
max_lag_seconds = 300

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
ssh_options = ["-o", "StrictHostKeyChecking=accept-new"]
keep = 14

[logging]
format = "json"

[hooks]
post_run = "/usr/local/bin/notify-backup-result.sh"
```
