#!/bin/bash
# Backs up the replica's data with mbkeeper, restores it into a throwaway
# third node, and checks the restored table matches the primary's.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

log() { echo "[01] $*"; }

log "seeding test data on primary"
docker compose exec -T primary mariadb -uroot -ptest appdb -e "
  CREATE TABLE IF NOT EXISTS widgets (id INT PRIMARY KEY, name VARCHAR(50));
  TRUNCATE TABLE widgets;
  INSERT INTO widgets VALUES (1,'alpha'),(2,'beta'),(3,'gamma');
"

log "waiting for the row count to replicate"
for _ in $(seq 1 30); do
  count="$(docker compose exec -T replica mariadb -uroot -ptest -N -e "SELECT COUNT(*) FROM appdb.widgets" 2>/dev/null || echo 0)"
  [ "$count" = "3" ] && break
  sleep 1
done
if [ "$count" != "3" ]; then
  log "ERROR: replica never caught up (last count=$count)"
  exit 1
fi

primary_checksum="$(docker compose exec -T primary mariadb -uroot -ptest -N -e "CHECKSUM TABLE appdb.widgets" | awk '{print $2}')"
log "primary checksum: $primary_checksum"

log "running mbkeeper run on the replica"
docker compose exec -T replica mbkeeper run -c /mbkeeper-config/01-full-backup-restore.toml

backup_id="$(docker compose exec -T replica sh -c 'ls /var/backups/mbkeeper/s01' | tr -d '\r' | tail -1)"
log "backup_id=$backup_id"
if [ -z "$backup_id" ]; then
  log "ERROR: no generation found under /var/backups/mbkeeper/s01"
  exit 1
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

log "copying the backup out to the host, then into a fresh restore-target"
docker compose cp "replica:/var/backups/mbkeeper/s01/${backup_id}" "$work_dir/backup"

docker compose --profile restore up -d restore-target
docker compose cp "$work_dir/backup" "restore-target:/tmp/restore-src"

log "restoring via mariadb-backup --copy-back"
docker compose exec -T restore-target sh -c "
  set -e
  rm -rf /var/lib/mysql/*
  if ! command -v mariabackup >/dev/null 2>&1 && command -v mariadb-backup >/dev/null 2>&1; then
    ln -sf \"\$(command -v mariadb-backup)\" /usr/local/bin/mariabackup
  fi
  mariabackup --copy-back --target-dir=/tmp/restore-src --datadir=/var/lib/mysql
  chown -R mysql:mysql /var/lib/mysql
"

log "starting mariadbd inside restore-target"
docker compose exec -d restore-target mariadbd --user=mysql

for _ in $(seq 1 30); do
  if docker compose exec -T restore-target mariadb-admin ping >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
if ! docker compose exec -T restore-target mariadb-admin ping >/dev/null 2>&1; then
  log "ERROR: restored mariadbd never came up"
  docker compose logs restore-target || true
  exit 1
fi

restored_checksum="$(docker compose exec -T restore-target mariadb -N -e "CHECKSUM TABLE appdb.widgets" | awk '{print $2}')"
log "restored checksum: $restored_checksum"

docker compose --profile restore stop restore-target >/dev/null 2>&1 || true

if [ "$primary_checksum" != "$restored_checksum" ]; then
  log "ERROR: checksum mismatch (primary=$primary_checksum restored=$restored_checksum)"
  exit 1
fi

log "checksums match"
