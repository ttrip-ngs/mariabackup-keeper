FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-server \
      rsync \
      netcat-openbsd \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/sshd \
    && useradd -m -d /home/mbkbackup -s /bin/bash mbkbackup \
    && mkdir -p /home/mbkbackup/.ssh /backups \
    && chmod 700 /home/mbkbackup/.ssh \
    && chown -R mbkbackup:mbkbackup /home/mbkbackup/.ssh /backups

COPY docker/sshd-entrypoint.sh /usr/local/bin/sshd-entrypoint.sh
RUN chmod +x /usr/local/bin/sshd-entrypoint.sh

EXPOSE 22
ENTRYPOINT ["sshd-entrypoint.sh"]
