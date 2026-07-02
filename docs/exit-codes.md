# Exit codes

`mbkeeper` always exits with one of these codes, so cron/systemd/monitoring
can distinguish "nothing to worry about," "warning," and "critical" without
parsing log text.

| Code | Name | Meaning | Severity |
|---|---|---|---|
| 0 | `SUCCESS` | Backup taken, stored at every destination, purge completed. | -- |
| 1 | `INTERNAL_ERROR` | Unexpected/unhandled error. | critical |
| 2 | `USAGE_ERROR` | Bad CLI arguments (argparse default). | -- |
| 3 | `CONFIG_ERROR` | Config file missing, malformed, or fails validation. | critical |
| 4 | `LOCKED` | Another `mbkeeper` invocation is already running (lock held). | info -- expected under cron overlap, usually not worth alerting on |
| 5 | `PRECONDITION_FAILED` | A precondition wasn't met: `mariabackup` missing, `[replication].mode`/`max_lag_seconds` violated, or a `pre_backup` hook failed. | critical |
| 6 | `BACKUP_FAILED` | `mariabackup --backup` or `--prepare` failed. Nothing was placed at any destination; `work_dir` is left in place for inspection. | critical |
| 7 | `ALL_DESTINATIONS_FAILED` | Every destination failed to receive the new generation. `work_dir` is preserved -- this is the only copy, it is not deleted. | critical |
| 8 | `PARTIAL_DESTINATION_FAILURE` | At least one destination succeeded, at least one failed. | warning, not critical |
| 9 | `PURGE_FAILED` | Storage succeeded everywhere it was attempted, but purge failed on at least one destination (couldn't list, or couldn't delete). | warning |

`mbkeeper check` uses a simpler binary signal: `0` if every probe (mariabackup,
replication, each destination) passed, `5` (`PRECONDITION_FAILED`) otherwise.

## Suggested monitoring split

- **Page / critical**: 1, 3, 5, 6, 7
- **Warn, don't page**: 8, 9
- **Ignore (expected under cron overlap)**: 4
