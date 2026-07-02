FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-server \
      rsync \
      netcat-openbsd \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/sshd \
    && useradd -m -d /home/backup -s /bin/bash backup \
    && mkdir -p /home/backup/.ssh /backups \
    && chmod 700 /home/backup/.ssh \
    && chown -R backup:backup /home/backup/.ssh /backups

COPY docker/sshd-entrypoint.sh /usr/local/bin/sshd-entrypoint.sh
RUN chmod +x /usr/local/bin/sshd-entrypoint.sh

EXPOSE 22
ENTRYPOINT ["sshd-entrypoint.sh"]
