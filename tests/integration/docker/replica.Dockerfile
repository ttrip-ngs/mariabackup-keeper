# Build context is the repo root (see docker-compose.yml) so we can install
# the mbkeeper package under test straight from source.
ARG MARIADB_VERSION=11.4
FROM mariadb:${MARIADB_VERSION}

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      rsync \
      openssh-client \
      mariadb-backup \
    && rm -rf /var/lib/apt/lists/* \
    && if ! command -v mariabackup >/dev/null 2>&1 && command -v mariadb-backup >/dev/null 2>&1; then \
         ln -sf "$(command -v mariadb-backup)" /usr/local/bin/mariabackup; \
       fi

COPY . /opt/mariabackup-keeper
# --break-system-packages only exists on pip >= 23.0 (Debian 12/Ubuntu
# 24.04-era); MariaDB 10.11's image is Ubuntu 22.04, whose python3-pip is
# older (rejects the unknown flag) and doesn't provide a bare `pip` binary.
RUN python3 -m pip install --break-system-packages --no-cache-dir /opt/mariabackup-keeper \
    || python3 -m pip install --no-cache-dir /opt/mariabackup-keeper

COPY tests/integration/docker/replica-entrypoint.sh /usr/local/bin/replica-entrypoint.sh
RUN chmod +x /usr/local/bin/replica-entrypoint.sh

ENTRYPOINT ["replica-entrypoint.sh"]
CMD ["mariadbd"]
