from mariabackup_keeper.exit_codes import ExitCode


class KeeperError(Exception):
    """Base class for errors that map to a specific process exit code."""

    exit_code = ExitCode.INTERNAL_ERROR


class ConfigError(KeeperError):
    """Configuration file is missing, malformed, or fails validation."""

    exit_code = ExitCode.CONFIG_ERROR


class LockError(KeeperError):
    """Another run holds the lock file."""

    exit_code = ExitCode.LOCKED


class PreconditionError(KeeperError):
    """A precondition for running (replication state, tool availability) is not met."""

    exit_code = ExitCode.PRECONDITION_FAILED


class BackupError(KeeperError):
    """mariabackup --backup or --prepare failed."""

    exit_code = ExitCode.BACKUP_FAILED


class DestinationError(KeeperError):
    """A destination operation (store/list/delete/check) failed."""

    exit_code = ExitCode.ALL_DESTINATIONS_FAILED
