#!/bin/bash
# Runs mbkeeper 4 times against a keep=2 destination and checks that only
# the 2 newest generations survive.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

log() { echo "[03] $*"; }

log "running mbkeeper run 4 times (keep=2)"
for i in 1 2 3 4; do
  docker compose exec -T replica mbkeeper run -c /mbkeeper-config/03-purge.toml
  # backup_id has 1-second resolution; make sure consecutive runs land on
  # distinct generations.
  sleep 2
done

remaining="$(docker compose exec -T replica sh -c 'ls /var/backups/mbkeeper/s03' | tr -d '\r')"
remaining_count="$(echo "$remaining" | grep -c . || true)"
log "remaining generations ($remaining_count):"
echo "$remaining"

if [ "$remaining_count" != "2" ]; then
  log "ERROR: expected exactly 2 generations to survive purge, found $remaining_count"
  exit 1
fi

newest_two="$(echo "$remaining" | sort | tail -2)"
if [ "$(echo "$remaining" | sort)" != "$newest_two" ]; then
  log "ERROR: the surviving generations are not the two newest"
  exit 1
fi

log "purge kept exactly the 2 newest generations"
