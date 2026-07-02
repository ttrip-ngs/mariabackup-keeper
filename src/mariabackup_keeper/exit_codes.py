from enum import IntEnum


class ExitCode(IntEnum):
    """Process exit codes. See docs/exit-codes.md for the operator-facing table."""

    SUCCESS = 0
    INTERNAL_ERROR = 1
    USAGE_ERROR = 2
    CONFIG_ERROR = 3
    LOCKED = 4
    PRECONDITION_FAILED = 5
    BACKUP_FAILED = 6
    ALL_DESTINATIONS_FAILED = 7
    PARTIAL_DESTINATION_FAILURE = 8
    PURGE_FAILED = 9
