#!/bin/sh
# Waits for the replica container to publish its public key on the shared
# volume, trusts it for the `mbkbackup` user, then starts sshd in the
# foreground. Named `mbkbackup` rather than `backup` because Debian already
# ships a system account called `backup` (uid/gid 34) -- `useradd backup`
# collides with it.
set -eu

echo "waiting for replica's ssh public key..."
until [ -f /shared-ssh-keys/id_ed25519.pub ]; do
  sleep 1
done

cp /shared-ssh-keys/id_ed25519.pub /home/mbkbackup/.ssh/authorized_keys
chown mbkbackup:mbkbackup /home/mbkbackup/.ssh/authorized_keys
chmod 600 /home/mbkbackup/.ssh/authorized_keys

ssh-keygen -A

exec /usr/sbin/sshd -D -e
