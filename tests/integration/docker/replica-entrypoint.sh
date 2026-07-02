#!/bin/bash
# Prepares this node for the integration scenarios, then hands off to the
# official mariadb image entrypoint (which performs first-boot init and
# finally execs the CMD, e.g. `mariadbd`).
set -euo pipefail

mkdir -p /shared-ssh-keys
if [ ! -f /shared-ssh-keys/id_ed25519 ]; then
  ssh-keygen -t ed25519 -N "" -f /shared-ssh-keys/id_ed25519 -q
fi
chmod 600 /shared-ssh-keys/id_ed25519

mkdir -p /var/lib/mbkeeper/work /var/backups/mbkeeper /run/mbkeeper

exec docker-entrypoint.sh "$@"
