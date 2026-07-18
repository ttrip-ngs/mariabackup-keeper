# Operations

## Scheduling

`mbkeeper run` is meant to be invoked by cron or a systemd timer -- it does
no scheduling itself.

### cron

```cron
# /etc/cron.d/mbkeeper
0 2 * * * mbkeeper mbkeeper run -c /etc/mbkeeper/config.toml >> /var/log/mbkeeper/cron.log 2>&1
```

The `flock`-based lock (`[lock].file`) makes overlapping invocations safe:
a run that's still in progress causes the next one to exit immediately with
code 4 rather than running concurrently.

### systemd timer

```ini
# /etc/systemd/system/mbkeeper.service
[Unit]
Description=mariabackup-keeper backup run

[Service]
Type=oneshot
User=mbkeeper
ExecStart=/usr/local/bin/mbkeeper run -c /etc/mbkeeper/config.toml
```

```ini
# /etc/systemd/system/mbkeeper.timer
[Unit]
Description=Run mariabackup-keeper daily

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemctl enable --now mbkeeper.timer
```

Check `mbkeeper check -c /etc/mbkeeper/config.toml` succeeds (exit code 0)
before enabling the timer -- it validates the config and probes
`mariabackup`, replication, and every destination without taking a backup.

## Running as a dedicated user

Run `mbkeeper` (and `mariabackup`) as a dedicated system user with:

- Read access to the MariaDB datadir and InnoDB/Aria log files
  (`mariabackup` needs this; consult MariaDB's own privilege requirements
  for `mariabackup`)
- Write access to `[backup].work_dir`, each `local`-type destination's
  `path`, and `[lock].file`'s parent directory
- A private SSH key readable only by this user, for any `ssh`-type
  destination

## SSH key setup for cross-backup

Cross-backup places generations on a remote node over SSH. Recommended
setup, run once per acquiring-node/destination-node pair:

1. On the acquiring node (the one running `mbkeeper run`), generate a
   dedicated key with no passphrase (it must run unattended):

   ```bash
   ssh-keygen -t ed25519 -N "" -f /etc/mbkeeper/id_ed25519
   ```

2. On the destination node, create a dedicated user and restrict its
   `authorized_keys` entry to only what `mbkeeper` needs. Avoid naming it
   plain `backup` -- Debian/Ubuntu already ship a system account with that
   name (uid/gid 34), and `useradd` will collide with it:

   ```bash
   useradd -m -d /home/mbkbackup -s /usr/sbin/nologin mbkbackup
   mkdir -p /home/mbkbackup/.ssh /var/backups/mbkeeper
   chown mbkbackup:mbkbackup /home/mbkbackup/.ssh /var/backups/mbkeeper
   ```

   In `/home/mbkbackup/.ssh/authorized_keys`, prefix the key with
   restrictions -- this account should never get an interactive shell:

   ```
   command="/usr/bin/rrsync /var/backups/mbkeeper",restrict ssh-ed25519 AAAA... acquiring-node
   ```

   (`rrsync`, shipped with `rsync`, restricts the session to rsync
   operations under the given path. If it's not available on your distro,
   at minimum keep `restrict` and consider `from="<acquiring-node-ip>"`.)

3. Point the destination at this key in config:

   ```toml
   [[destinations]]
   name = "master-dr"
   type = "ssh"
   host = "db-master.example.com"
   user = "mbkbackup"
   path = "/var/backups/mbkeeper"
   ssh_key = "/etc/mbkeeper/id_ed25519"
   ssh_options = ["-o", "StrictHostKeyChecking=accept-new"]
   keep = 14
   ```

   `StrictHostKeyChecking=accept-new` trusts the host key on first
   connection and then pins it -- pre-seed `known_hosts` yourself instead if
   your security posture requires verifying the host key out-of-band before
   first use.

**One acquiring node per destination path.** `mbkeeper` doesn't do
distributed locking across destinations -- it assumes a given destination
`path` is written to by exactly one acquiring node. If multiple replicas
back up to the same DR node, give each one its own subdirectory (a
separate `path` per source).

## Credentials

Never put a DB password directly in `config.toml`. Use
`[backup].defaults_extra_file` pointing at a `[client]`-section file:

```ini
# /etc/mbkeeper/client.cnf, mode 0600, owned by the mbkeeper user
[client]
user=backup
password=...
```

## Restore drills

This project's CI verifies backup/restore correctness against
representative configurations -- it cannot verify *your* data or
environment. Run periodic restore drills against your actual backups:
`mariabackup --prepare` (if not already prepared) then `--copy-back` (or
equivalent) into a scratch instance, and verify the data you actually care
about. See [README.md's Responsibility split](../README.md#responsibility-split).
