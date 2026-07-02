#!/bin/sh
# Waits for the replica container to publish its public key on the shared
# volume, trusts it for the `backup` user, then starts sshd in the foreground.
set -eu

echo "waiting for replica's ssh public key..."
until [ -f /shared-ssh-keys/id_ed25519.pub ]; do
  sleep 1
done

cp /shared-ssh-keys/id_ed25519.pub /home/backup/.ssh/authorized_keys
chown backup:backup /home/backup/.ssh/authorized_keys
chmod 600 /home/backup/.ssh/authorized_keys

ssh-keygen -A

exec /usr/sbin/sshd -D -e
