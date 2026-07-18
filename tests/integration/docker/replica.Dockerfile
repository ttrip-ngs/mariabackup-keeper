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
# Two image generations, two different pip situations:
#   * MariaDB 11.4 -> Ubuntu 24.04, pip 24: PEP 668 externally-managed, so the
#     install needs --break-system-packages. This path succeeds outright.
#   * MariaDB 10.11 -> Ubuntu 22.04, pip 22.0.2: doesn't know
#     --break-system-packages (so the first command fails fast, before any
#     install), and its bundled setuptools (59.6) is too old to read this
#     project's PEP 621 [project] metadata -- a plain install there silently
#     builds an empty "UNKNOWN-0.0.0" package and never creates the mbkeeper
#     entry point. Upgrading pip (which also pulls a modern setuptools; 22.04
#     has no externally-managed marker so this just works) fixes both, then
#     the install produces a real mbkeeper on PATH.
RUN python3 -m pip install --break-system-packages --no-cache-dir /opt/mariabackup-keeper \
    || { python3 -m pip install --upgrade pip \
         && python3 -m pip install --no-cache-dir /opt/mariabackup-keeper; }

COPY tests/integration/docker/replica-entrypoint.sh /usr/local/bin/replica-entrypoint.sh
RUN chmod +x /usr/local/bin/replica-entrypoint.sh

ENTRYPOINT ["replica-entrypoint.sh"]
CMD ["mariadbd"]
