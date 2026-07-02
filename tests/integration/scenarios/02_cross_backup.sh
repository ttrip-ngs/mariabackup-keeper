#!/bin/bash
# Verifies cross-backup: a generation lands on both the local and the ssh
# (store) destination with identical contents, and that taking the store
# node down degrades to best-effort (local still succeeds, exit code 8)
# rather than failing the whole run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

log() { echo "[02] $*"; }

log "running mbkeeper run on the replica (local + ssh destinations)"
docker compose exec -T replica mbkeeper run -c /mbkeeper-config/02-cross-backup.toml

local_id="$(docker compose exec -T replica sh -c 'ls /var/backups/mbkeeper/s02-local' | tr -d '\r' | tail -1)"
store_id="$(docker compose exec -T store sh -c 'ls /backups' | tr -d '\r' | tail -1)"
log "local backup_id=$local_id, store backup_id=$store_id"

if [ -z "$local_id" ] || [ "$local_id" != "$store_id" ]; then
  log "ERROR: local and store do not have a matching generation ($local_id vs $store_id)"
  exit 1
fi

log "comparing file listings between local and store copies"
local_listing="$(docker compose exec -T replica sh -c "cd /var/backups/mbkeeper/s02-local/${local_id} && find . -type f -printf '%P %s\n' | sort")"
store_listing="$(docker compose exec -T store sh -c "cd /backups/${store_id} && find . -type f -printf '%P %s\n' | sort")"

if [ "$local_listing" != "$store_listing" ]; then
  log "ERROR: file listings differ between local and store"
  echo "--- local ---"
  echo "$local_listing"
  echo "--- store ---"
  echo "$store_listing"
  exit 1
fi
log "file listings match"

log "stopping the store node to simulate a destination outage"
docker compose stop store

set +e
docker compose exec -T replica mbkeeper run -c /mbkeeper-config/02-cross-backup.toml
partial_exit_code=$?
set -e
log "run with store down exited with code $partial_exit_code"

if [ "$partial_exit_code" != "8" ]; then
  log "ERROR: expected exit code 8 (partial destination failure), got $partial_exit_code"
  docker compose start store
  exit 1
fi

new_local_id="$(docker compose exec -T replica sh -c 'ls /var/backups/mbkeeper/s02-local' | tr -d '\r' | tail -1)"
if [ "$new_local_id" = "$local_id" ]; then
  log "ERROR: local destination did not receive a new generation while store was down"
  docker compose start store
  exit 1
fi
log "local destination still received the new generation ($new_local_id) despite store being down"

log "restarting the store node"
docker compose start store
for _ in $(seq 1 30); do
  status="$(docker compose ps --format '{{.Health}}' store 2>/dev/null || true)"
  [ "$status" = "healthy" ] && break
  sleep 2
done
