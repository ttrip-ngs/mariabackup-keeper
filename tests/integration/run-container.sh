#!/bin/bash
# Local integration runner for Apple Silicon Macs using Apple's `container`
# CLI (https://github.com/apple/container) instead of Docker/docker compose.
#
# This is NOT what CI runs -- CI (.github/workflows/ci.yml) uses
# tests/integration/run.sh with real Docker Compose on a Linux runner, which
# remains the project's canonical, portable integration harness. This script
# exists because `container` has no Docker Compose equivalent (no multi-service
# orchestration, no `build`/profiles usable without Rosetta) and this repo's
# primary dev machine is an Apple Silicon Mac without a Docker daemon. The
# scenario coverage mirrors tests/integration/scenarios/*.sh but is
# implemented directly against `container` rather than sharing those files,
# since the two runtimes' primitives (compose exec/cp/profiles vs. plain
# `container run`/`exec`/`cp` with manual provisioning) don't map cleanly
# onto a single abstraction without more machinery than it's worth for a
# secondary, local-only path.
#
# Requires: `container` CLI (`brew install container`), running
# (`container system start`), on macOS 26+ (inter-container networking is
# required; macOS 15 isolates every container on its own network).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_DIR="$SCRIPT_DIR/config"

MARIADB_VERSION="${MARIADB_VERSION:-11.4}"
RUN_ID="mbkeeper-it-$$"
PRIMARY="${RUN_ID}-primary"
REPLICA="${RUN_ID}-replica"
STORE="${RUN_ID}-store"
RESTORE="${RUN_ID}-restore"
SSH_DIR="$(mktemp -d)"

log() { echo "[run-container] $*"; }

cleanup() {
  local exit_code=$?
  log "tearing down (run: $RUN_ID)"
  container rm -f "$PRIMARY" "$REPLICA" "$STORE" "$RESTORE" >/dev/null 2>&1 || true
  rm -rf "$SSH_DIR"
  exit "$exit_code"
}
trap cleanup EXIT

container_ip() {
  container inspect "$1" | jq -r '.. | objects | select(has("ipv4Address")) | .ipv4Address' | cut -d/ -f1
}

wait_mariadb_ready() {
  local name="$1"
  for _ in $(seq 1 60); do
    if container exec "$name" healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  log "ERROR: $name did not become ready in time"
  container logs "$name" || true
  exit 1
}

start_store_sshd() {
  container exec -d "$STORE" /usr/sbin/sshd -D -e
  for _ in $(seq 1 15); do
    if container exec "$STORE" sh -c 'pgrep sshd' >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  log "ERROR: sshd did not start on $STORE"
  exit 1
}

log "using MariaDB ${MARIADB_VERSION}, run id ${RUN_ID}"
log "pulling mariadb:${MARIADB_VERSION}"
container image pull "mariadb:${MARIADB_VERSION}" >/dev/null

log "starting primary"
container run -d --name "$PRIMARY" --network default \
  -e MARIADB_ROOT_PASSWORD=test -e MARIADB_DATABASE=appdb \
  "mariadb:${MARIADB_VERSION}" --server-id=1 --log-bin=mariadb-bin --binlog-format=ROW >/dev/null

log "starting replica"
container run -d --name "$REPLICA" --network default \
  -e MARIADB_ROOT_PASSWORD=test \
  -v "$REPO_ROOT:/opt/mariabackup-keeper:ro" \
  -v "$SSH_DIR:/shared-ssh-keys" \
  -v "$CONFIG_DIR:/mbkeeper-config:ro" \
  "mariadb:${MARIADB_VERSION}" --server-id=2 --log-bin=mariadb-bin --binlog-format=ROW --relay-log=relay-bin >/dev/null

log "starting store"
container run -d --name "$STORE" --network default \
  -v "$SSH_DIR:/shared-ssh-keys:ro" \
  debian:bookworm-slim sleep infinity >/dev/null

log "waiting for primary"
wait_mariadb_ready "$PRIMARY"
log "waiting for replica"
wait_mariadb_ready "$REPLICA"

log "provisioning replica: mbkeeper, mariabackup, ssh client, ssh keypair"
container exec "$REPLICA" bash -c '
  set -e
  apt-get update -qq
  apt-get install -y -qq python3 python3-pip rsync openssh-client mariadb-backup
  # pip refuses to build from a read-only source tree (it tries to touch
  # src/*.egg-info in place), so copy to a writable path first.
  cp -r /opt/mariabackup-keeper /tmp/mbkeeper-src
  # MariaDB 11.4 (Ubuntu 24.04, pip 24) needs --break-system-packages and the
  # first command succeeds. MariaDB 10.11 (Ubuntu 22.04, pip 22.0.2) rejects
  # that flag (so it fails fast, no half-install) AND ships setuptools 59.6,
  # too old to read this project'"'"'s PEP 621 metadata -- a plain install there
  # silently builds an empty "UNKNOWN-0.0.0" with no mbkeeper entry point.
  # Upgrading pip (pulls a modern setuptools; 22.04 is not externally-managed)
  # fixes both, then the install yields a real mbkeeper on PATH.
  python3 -m pip install --break-system-packages --quiet --no-cache-dir /tmp/mbkeeper-src \
    || { python3 -m pip install --quiet --upgrade pip \
         && python3 -m pip install --quiet --no-cache-dir /tmp/mbkeeper-src; }
  mkdir -p /var/lib/mbkeeper/work /var/backups/mbkeeper /run/mbkeeper /shared-ssh-keys
  if [ ! -f /shared-ssh-keys/id_ed25519 ]; then
    ssh-keygen -t ed25519 -N "" -f /shared-ssh-keys/id_ed25519 -q
  fi
  chmod 600 /shared-ssh-keys/id_ed25519
'

log "provisioning store: sshd, rsync, mbkbackup user"
# Named mbkbackup, not backup: Debian ships a system account called `backup`
# (uid/gid 34) and `useradd backup` collides with it.
container exec "$STORE" bash -c '
  set -e
  apt-get update -qq
  apt-get install -y -qq openssh-server rsync
  mkdir -p /var/run/sshd
  id mbkbackup >/dev/null 2>&1 || useradd -m -d /home/mbkbackup -s /bin/bash mbkbackup
  mkdir -p /home/mbkbackup/.ssh /backups
  chown -R mbkbackup:mbkbackup /home/mbkbackup/.ssh /backups
  chmod 700 /home/mbkbackup/.ssh
  until [ -f /shared-ssh-keys/id_ed25519.pub ]; do sleep 1; done
  cp /shared-ssh-keys/id_ed25519.pub /home/mbkbackup/.ssh/authorized_keys
  chown mbkbackup:mbkbackup /home/mbkbackup/.ssh/authorized_keys
  chmod 600 /home/mbkbackup/.ssh/authorized_keys
  ssh-keygen -A
'
start_store_sshd

PRIMARY_IP="$(container_ip "$PRIMARY")"
STORE_IP="$(container_ip "$STORE")"
log "primary=$PRIMARY_IP store=$STORE_IP"

log "creating replication user on primary"
container exec "$PRIMARY" mariadb -uroot -ptest -e "
  CREATE USER IF NOT EXISTS 'repl'@'%' IDENTIFIED BY 'repltest';
  GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';
  FLUSH PRIVILEGES;
"

log "pointing replica at primary"
container exec "$REPLICA" mariadb -uroot -ptest -e "
  STOP SLAVE;
  CHANGE MASTER TO MASTER_HOST='${PRIMARY_IP}', MASTER_USER='repl',
    MASTER_PASSWORD='repltest', MASTER_USE_GTID=slave_pos;
  START SLAVE;
"

log "waiting for replication to catch up"
io_running=0
sql_running=0
for _ in $(seq 1 30); do
  status="$(container exec "$REPLICA" mariadb -uroot -ptest -e "SHOW SLAVE STATUS\G" 2>/dev/null)"
  io_running="$(echo "$status" | grep -c 'Slave_IO_Running: Yes' || true)"
  sql_running="$(echo "$status" | grep -c 'Slave_SQL_Running: Yes' || true)"
  [ "$io_running" = "1" ] && [ "$sql_running" = "1" ] && break
  sleep 2
done
if [ "$io_running" != "1" ] || [ "$sql_running" != "1" ]; then
  log "ERROR: replication did not start"
  container exec "$REPLICA" mariadb -uroot -ptest -e "SHOW SLAVE STATUS\G" || true
  exit 1
fi
log "replication is running"

# --- Scenario 1: full backup, physical restore, checksum verification ------

log "=== scenario 1: full backup + restore ==="

container exec "$PRIMARY" mariadb -uroot -ptest appdb -e "
  CREATE TABLE IF NOT EXISTS widgets (id INT PRIMARY KEY, name VARCHAR(50));
  TRUNCATE TABLE widgets;
  INSERT INTO widgets VALUES (1,'alpha'),(2,'beta'),(3,'gamma');
"

count=0
for _ in $(seq 1 30); do
  count="$(container exec "$REPLICA" mariadb -uroot -ptest -N -e "SELECT COUNT(*) FROM appdb.widgets" 2>/dev/null || echo 0)"
  [ "$count" = "3" ] && break
  sleep 1
done
[ "$count" = "3" ] || { log "ERROR: replica never caught up (count=$count)"; exit 1; }

primary_checksum="$(container exec "$PRIMARY" mariadb -uroot -ptest -N -e "CHECKSUM TABLE appdb.widgets" | awk '{print $2}')"
log "primary checksum: $primary_checksum"

container exec "$REPLICA" mbkeeper run -c /mbkeeper-config/01-full-backup-restore.toml
backup_id="$(container exec "$REPLICA" sh -c 'ls /var/backups/mbkeeper/s01' | tr -d '\r' | tail -1)"
log "backup_id=$backup_id"

work_dir="$(mktemp -d)"
container cp "${REPLICA}:/var/backups/mbkeeper/s01/${backup_id}" "$work_dir/backup"

container run -d --name "$RESTORE" --network default --entrypoint sleep "mariadb:${MARIADB_VERSION}" infinity >/dev/null
container cp "$work_dir/backup" "${RESTORE}:/tmp/restore-src"
rm -rf "$work_dir"

container exec "$RESTORE" bash -c '
  set -e
  command -v mariadb-backup >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq mariadb-backup)
  rm -rf /var/lib/mysql/*
  mariadb-backup --copy-back --target-dir=/tmp/restore-src --datadir=/var/lib/mysql
  chown -R mysql:mysql /var/lib/mysql
'
container exec -d "$RESTORE" mariadbd --user=mysql

restore_ready=1
for _ in $(seq 1 30); do
  if container exec "$RESTORE" mariadb -uroot -ptest -e "SELECT 1" >/dev/null 2>&1; then
    restore_ready=0
    break
  fi
  sleep 2
done
[ "$restore_ready" = "0" ] || { log "ERROR: restored mariadbd never came up"; container logs "$RESTORE" || true; exit 1; }

restored_checksum="$(container exec "$RESTORE" mariadb -uroot -ptest -N -e "CHECKSUM TABLE appdb.widgets" | awk '{print $2}')"
log "restored checksum: $restored_checksum"
container rm -f "$RESTORE" >/dev/null 2>&1 || true

if [ "$primary_checksum" != "$restored_checksum" ]; then
  log "SCENARIO 1 FAILED: checksum mismatch (primary=$primary_checksum restored=$restored_checksum)"
  exit 1
fi
log "scenario 1 passed: checksums match"

# --- Scenario 2: cross-backup + best-effort destination failure ------------

log "=== scenario 2: cross-backup ==="

scenario2_config="$(mktemp)"
cat > "$scenario2_config" <<EOF
schema_version = 1

[backup]
work_dir = "/var/lib/mbkeeper/work"
mariabackup_path = "mariabackup"
defaults_extra_file = "/mbkeeper-config/client.cnf"

[transfer]
on_destination_failure = "continue"
retries = 1

[[destinations]]
name = "local"
type = "local"
path = "/var/backups/mbkeeper/s02-local"
keep = 7

[[destinations]]
name = "store"
type = "ssh"
host = "${STORE_IP}"
user = "mbkbackup"
path = "/backups"
ssh_key = "/shared-ssh-keys/id_ed25519"
ssh_options = ["-o", "StrictHostKeyChecking=accept-new"]
keep = 7

[lock]
file = "/run/mbkeeper/mbkeeper.lock"
EOF
container cp "$scenario2_config" "${REPLICA}:/tmp/02-test.toml"
rm -f "$scenario2_config"

container exec "$REPLICA" mbkeeper run -c /tmp/02-test.toml
local_id="$(container exec "$REPLICA" sh -c 'ls /var/backups/mbkeeper/s02-local' | tr -d '\r' | tail -1)"
store_id="$(container exec "$STORE" sh -c 'ls /backups' | tr -d '\r' | tail -1)"
log "local=$local_id store=$store_id"
if [ -z "$local_id" ] || [ "$local_id" != "$store_id" ]; then
  log "SCENARIO 2 FAILED: local and store generations don't match"
  exit 1
fi

log "stopping store to simulate an outage"
container stop "$STORE" >/dev/null

set +e
container exec "$REPLICA" mbkeeper run -c /tmp/02-test.toml
partial_exit_code=$?
set -e
log "run with store down exited $partial_exit_code"
if [ "$partial_exit_code" != "8" ]; then
  log "SCENARIO 2 FAILED: expected exit code 8, got $partial_exit_code"
  exit 1
fi

new_local_id="$(container exec "$REPLICA" sh -c 'ls /var/backups/mbkeeper/s02-local' | tr -d '\r' | tail -1)"
if [ "$new_local_id" = "$local_id" ]; then
  log "SCENARIO 2 FAILED: local did not receive a new generation while store was down"
  exit 1
fi
log "local still received $new_local_id despite store being down"

container start "$STORE" >/dev/null
start_store_sshd
log "scenario 2 passed"

# --- Scenario 3: purge ------------------------------------------------------

log "=== scenario 3: purge (keep=2) ==="

for i in 1 2 3 4; do
  container exec "$REPLICA" mbkeeper run -c /mbkeeper-config/03-purge.toml >/dev/null
  sleep 2
done

remaining="$(container exec "$REPLICA" sh -c 'ls /var/backups/mbkeeper/s03' | tr -d '\r')"
remaining_count="$(echo "$remaining" | grep -c . || true)"
log "remaining generations ($remaining_count): $(echo "$remaining" | tr '\n' ' ')"
if [ "$remaining_count" != "2" ]; then
  log "SCENARIO 3 FAILED: expected 2 surviving generations, found $remaining_count"
  exit 1
fi
log "scenario 3 passed"

log "all scenarios passed"
