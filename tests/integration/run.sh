#!/bin/bash
# Single entrypoint for local and CI integration runs -- both call this
# script so the test logic never has to be maintained twice (see
# .github/workflows/ci.yml). Spins up a disposable primary/replica/store
# topology, wires up replication and ssh trust, runs each scenario in
# tests/integration/scenarios/, then always tears everything down.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export MARIADB_VERSION="${MARIADB_VERSION:-11.4}"
export COMPOSE_PROJECT_NAME="mbkeeper-it-$$"
LOG_DIR="${MBKEEPER_IT_LOG_DIR:-/tmp/mbkeeper-it-logs}"

log() { echo "[run.sh] $*"; }

cleanup() {
  local exit_code=$?
  if [ "$exit_code" -ne 0 ]; then
    log "run failed (exit $exit_code); saving container logs to $LOG_DIR"
    mkdir -p "$LOG_DIR"
    docker compose --profile restore logs --no-color > "$LOG_DIR/compose.log" 2>&1 || true
  fi
  log "tearing down (project: $COMPOSE_PROJECT_NAME)"
  docker compose --profile restore down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "using MariaDB ${MARIADB_VERSION}, compose project ${COMPOSE_PROJECT_NAME}"

log "building and starting primary, replica, store"
docker compose up -d --build primary replica store

wait_healthy() {
  local service="$1"
  local attempts=60
  for _ in $(seq 1 "$attempts"); do
    status="$(docker compose ps --format '{{.Health}}' "$service" 2>/dev/null || true)"
    if [ "$status" = "healthy" ]; then
      return 0
    fi
    sleep 2
  done
  log "ERROR: $service did not become healthy in time"
  docker compose logs "$service" || true
  exit 1
}

log "waiting for primary"
wait_healthy primary
log "waiting for replica"
wait_healthy replica
log "waiting for store"
wait_healthy store

log "creating replication user on primary"
docker compose exec -T primary mariadb -uroot -ptest -e "
  CREATE USER IF NOT EXISTS 'repl'@'%' IDENTIFIED BY 'repltest';
  GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';
  FLUSH PRIVILEGES;
"

log "pointing replica at primary"
docker compose exec -T replica mariadb -uroot -ptest -e "
  STOP SLAVE;
  CHANGE MASTER TO MASTER_HOST='primary', MASTER_USER='repl',
    MASTER_PASSWORD='repltest', MASTER_USE_GTID=slave_pos;
  START SLAVE;
"

log "waiting for replication to catch up"
for _ in $(seq 1 30); do
  io_running="$(docker compose exec -T replica mariadb -uroot -ptest -N -e "SHOW SLAVE STATUS\G" 2>/dev/null | grep -c 'Slave_IO_Running: Yes' || true)"
  sql_running="$(docker compose exec -T replica mariadb -uroot -ptest -N -e "SHOW SLAVE STATUS\G" 2>/dev/null | grep -c 'Slave_SQL_Running: Yes' || true)"
  if [ "$io_running" = "1" ] && [ "$sql_running" = "1" ]; then
    break
  fi
  sleep 2
done

if [ "${io_running:-0}" != "1" ] || [ "${sql_running:-0}" != "1" ]; then
  log "ERROR: replication did not start"
  docker compose exec -T replica mariadb -uroot -ptest -e "SHOW SLAVE STATUS\G" || true
  exit 1
fi
log "replication is running"

failures=0
for scenario in scenarios/*.sh; do
  log "=== running $(basename "$scenario") ==="
  if ! bash "$scenario"; then
    log "=== $(basename "$scenario") FAILED ==="
    failures=$((failures + 1))
  else
    log "=== $(basename "$scenario") passed ==="
  fi
done

if [ "$failures" -gt 0 ]; then
  log "$failures scenario(s) failed"
  exit 1
fi

log "all scenarios passed"
