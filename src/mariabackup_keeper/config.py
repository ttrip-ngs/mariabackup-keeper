"""TOML configuration loading and validation.

Converts the on-disk TOML into validated, frozen dataclasses. All downstream
code depends only on these dataclasses, never on raw dict/TOML data.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mariabackup_keeper.errors import ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

SUPPORTED_SCHEMA_VERSION = 1
VALID_REPLICATION_MODES = ("off", "require_replica")
VALID_ON_DESTINATION_FAILURE = ("continue", "abort")
VALID_LOG_LEVELS = ("debug", "info", "warning", "error")
VALID_LOG_FORMATS = ("text", "json")
VALID_DESTINATION_TYPES = ("local", "ssh")

# argv positions mariabackup.py owns; users may not smuggle these via extra_args.
_RESERVED_MARIABACKUP_ARGS = ("--backup", "--prepare", "--target-dir", "--password")

DEFAULT_CONFIG_PATH = Path("/etc/mbkeeper/config.toml")


class _Errors:
    """Accumulates validation errors so the user sees them all at once."""

    def __init__(self) -> None:
        self._items: list[str] = []

    def add(self, message: str) -> None:
        self._items.append(message)

    def extend(self, other: _Errors) -> None:
        self._items.extend(other._items)

    def raise_if_any(self) -> None:
        if self._items:
            joined = "\n".join(f"  - {m}" for m in self._items)
            raise ConfigError(f"Invalid configuration:\n{joined}")


@dataclass(frozen=True)
class BackupConfig:
    work_dir: Path
    name_prefix: str = "full"
    mariabackup_path: str = "mariabackup"
    defaults_file: str = ""
    defaults_extra_file: str = ""
    extra_args: tuple[str, ...] = ()
    prepare: bool = True
    timeout_seconds: int = 0


@dataclass(frozen=True)
class ReplicationConfig:
    mode: str = "off"
    max_lag_seconds: int = 0
    safe_slave_backup: bool = True
    client_path: str = "mariadb"


@dataclass(frozen=True)
class TransferConfig:
    on_destination_failure: str = "continue"
    retries: int = 2
    rsync_path: str = "rsync"


@dataclass(frozen=True)
class RetentionConfig:
    incomplete_grace_hours: int = 24


@dataclass(frozen=True)
class DestinationConfig:
    name: str
    type: str
    keep: int
    path: str
    host: str = ""
    port: int = 22
    user: str = ""
    ssh_key: str = ""
    ssh_options: tuple[str, ...] = ()
    bwlimit_kbps: int = 0


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "info"
    format: str = "text"
    file: str = ""


@dataclass(frozen=True)
class LockConfig:
    file: Path = Path("/run/mbkeeper/mbkeeper.lock")


@dataclass(frozen=True)
class HooksConfig:
    pre_backup: str = ""
    post_backup: str = ""
    pre_purge: str = ""
    post_run: str = ""


@dataclass(frozen=True)
class Config:
    schema_version: int
    backup: BackupConfig
    destinations: tuple[DestinationConfig, ...]
    replication: ReplicationConfig = field(default_factory=ReplicationConfig)
    transfer: TransferConfig = field(default_factory=TransferConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    lock: LockConfig = field(default_factory=LockConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)


def load_config(path: Path) -> Config:
    """Load and validate a TOML config file. Raises ConfigError on any problem."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from exc

    try:
        raw = tomllib.loads(raw_bytes.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Cannot parse TOML in {path}: {exc}") from exc

    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> Config:
    """Validate an already-parsed TOML dict and build the Config dataclass tree."""
    errors = _Errors()

    _reject_unknown_keys(
        raw,
        {
            "schema_version",
            "backup",
            "replication",
            "transfer",
            "retention",
            "destinations",
            "logging",
            "lock",
            "hooks",
        },
        "top-level",
        errors,
    )

    schema_version = raw.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        errors.add(f"schema_version must be {SUPPORTED_SCHEMA_VERSION}, got {schema_version!r}")

    backup = _parse_backup(raw.get("backup"), errors)
    replication = _parse_replication(raw.get("replication"), errors)
    transfer = _parse_transfer(raw.get("transfer"), errors)
    retention = _parse_retention(raw.get("retention"), errors)
    destinations = _parse_destinations(raw.get("destinations"), errors)
    logging_cfg = _parse_logging(raw.get("logging"), errors)
    lock = _parse_lock(raw.get("lock"), errors)
    hooks = _parse_hooks(raw.get("hooks"), errors)

    if backup is not None and destinations:
        for dest in destinations:
            if dest.type == "local" and str(backup.work_dir) == dest.path:
                errors.add(f"destination '{dest.name}': path must not equal backup.work_dir")

    errors.raise_if_any()

    assert backup is not None  # guaranteed by errors.raise_if_any() above
    return Config(
        schema_version=schema_version,
        backup=backup,
        destinations=tuple(destinations),
        replication=replication,
        transfer=transfer,
        retention=retention,
        logging=logging_cfg,
        lock=lock,
        hooks=hooks,
    )


def _reject_unknown_keys(
    table: dict[str, Any], allowed: set[str], context: str, errors: _Errors
) -> None:
    for key in table:
        if key not in allowed:
            errors.add(f"unknown key '{key}' in {context}")


def _require_str(table: dict[str, Any], key: str, context: str, errors: _Errors) -> str | None:
    if key not in table:
        errors.add(f"missing required key '{key}' in {context}")
        return None
    value = table[key]
    if not isinstance(value, str) or not value:
        errors.add(f"'{key}' in {context} must be a non-empty string")
        return None
    return value


def _parse_backup(table: Any, errors: _Errors) -> BackupConfig | None:
    context = "[backup]"
    if table is None:
        errors.add(f"missing required section {context}")
        return None
    if not isinstance(table, dict):
        errors.add(f"{context} must be a table")
        return None

    allowed = {
        "work_dir",
        "name_prefix",
        "mariabackup_path",
        "defaults_file",
        "defaults_extra_file",
        "extra_args",
        "prepare",
        "timeout_seconds",
    }
    _reject_unknown_keys(table, allowed, context, errors)

    work_dir_str = _require_str(table, "work_dir", context, errors)

    name_prefix = table.get("name_prefix", "full")
    if not isinstance(name_prefix, str) or not name_prefix:
        errors.add(f"'name_prefix' in {context} must be a non-empty string")

    extra_args = table.get("extra_args", [])
    if not isinstance(extra_args, list) or not all(isinstance(a, str) for a in extra_args):
        errors.add(f"'extra_args' in {context} must be a list of strings")
        extra_args = []
    for reserved in _RESERVED_MARIABACKUP_ARGS:
        if any(a == reserved or a.startswith(reserved + "=") for a in extra_args):
            errors.add(f"'extra_args' in {context} must not set reserved argument '{reserved}'")

    timeout_seconds = table.get("timeout_seconds", 0)
    invalid_timeout = (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds < 0
    )
    if invalid_timeout:
        errors.add(f"'timeout_seconds' in {context} must be a non-negative integer")
        timeout_seconds = 0

    prepare = table.get("prepare", True)
    if not isinstance(prepare, bool):
        errors.add(f"'prepare' in {context} must be a boolean")
        prepare = True

    if work_dir_str is None:
        return None

    return BackupConfig(
        work_dir=Path(work_dir_str),
        name_prefix=name_prefix if isinstance(name_prefix, str) else "full",
        mariabackup_path=table.get("mariabackup_path", "mariabackup"),
        defaults_file=table.get("defaults_file", ""),
        defaults_extra_file=table.get("defaults_extra_file", ""),
        extra_args=tuple(extra_args),
        prepare=prepare,
        timeout_seconds=timeout_seconds,
    )


def _parse_replication(table: Any, errors: _Errors) -> ReplicationConfig:
    context = "[replication]"
    if table is None:
        return ReplicationConfig()
    if not isinstance(table, dict):
        errors.add(f"{context} must be a table")
        return ReplicationConfig()

    allowed = {"mode", "max_lag_seconds", "safe_slave_backup", "client_path"}
    _reject_unknown_keys(table, allowed, context, errors)

    mode = table.get("mode", "off")
    if mode not in VALID_REPLICATION_MODES:
        errors.add(f"'mode' in {context} must be one of {VALID_REPLICATION_MODES}, got {mode!r}")
        mode = "off"

    max_lag_seconds = table.get("max_lag_seconds", 0)
    if (
        not isinstance(max_lag_seconds, int)
        or isinstance(max_lag_seconds, bool)
        or max_lag_seconds < 0
    ):
        errors.add(f"'max_lag_seconds' in {context} must be a non-negative integer")
        max_lag_seconds = 0

    safe_slave_backup = table.get("safe_slave_backup", True)
    if not isinstance(safe_slave_backup, bool):
        errors.add(f"'safe_slave_backup' in {context} must be a boolean")
        safe_slave_backup = True

    return ReplicationConfig(
        mode=mode,
        max_lag_seconds=max_lag_seconds,
        safe_slave_backup=safe_slave_backup,
        client_path=table.get("client_path", "mariadb"),
    )


def _parse_transfer(table: Any, errors: _Errors) -> TransferConfig:
    context = "[transfer]"
    if table is None:
        return TransferConfig()
    if not isinstance(table, dict):
        errors.add(f"{context} must be a table")
        return TransferConfig()

    allowed = {"on_destination_failure", "retries", "rsync_path"}
    _reject_unknown_keys(table, allowed, context, errors)

    on_failure = table.get("on_destination_failure", "continue")
    if on_failure not in VALID_ON_DESTINATION_FAILURE:
        errors.add(
            f"'on_destination_failure' in {context} must be one of "
            f"{VALID_ON_DESTINATION_FAILURE}, got {on_failure!r}"
        )
        on_failure = "continue"

    retries = table.get("retries", 2)
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        errors.add(f"'retries' in {context} must be a non-negative integer")
        retries = 2

    return TransferConfig(
        on_destination_failure=on_failure,
        retries=retries,
        rsync_path=table.get("rsync_path", "rsync"),
    )


def _parse_retention(table: Any, errors: _Errors) -> RetentionConfig:
    context = "[retention]"
    if table is None:
        return RetentionConfig()
    if not isinstance(table, dict):
        errors.add(f"{context} must be a table")
        return RetentionConfig()

    allowed = {"incomplete_grace_hours"}
    _reject_unknown_keys(table, allowed, context, errors)

    grace = table.get("incomplete_grace_hours", 24)
    if not isinstance(grace, int) or isinstance(grace, bool) or grace < 0:
        errors.add(f"'incomplete_grace_hours' in {context} must be a non-negative integer")
        grace = 24

    return RetentionConfig(incomplete_grace_hours=grace)


def _parse_destinations(raw_list: Any, errors: _Errors) -> list[DestinationConfig]:
    if raw_list is None or raw_list == []:
        errors.add("at least one [[destinations]] entry is required")
        return []
    if not isinstance(raw_list, list):
        errors.add("'destinations' must be an array of tables")
        return []

    destinations: list[DestinationConfig] = []
    seen_names: set[str] = set()

    for index, table in enumerate(raw_list):
        context = f"destinations[{index}]"
        if not isinstance(table, dict):
            errors.add(f"{context} must be a table")
            continue

        dest_type = table.get("type")
        if dest_type not in VALID_DESTINATION_TYPES:
            errors.add(
                f"'type' in {context} must be one of {VALID_DESTINATION_TYPES}, got {dest_type!r}"
            )
            continue

        allowed = {"name", "type", "path", "keep"}
        if dest_type == "ssh":
            allowed |= {"host", "port", "user", "ssh_key", "ssh_options", "bwlimit_kbps"}
        _reject_unknown_keys(table, allowed, context, errors)

        name = _require_str(table, "name", context, errors)
        if name is not None:
            if name in seen_names:
                errors.add(f"duplicate destination name '{name}'")
            seen_names.add(name)

        path = _require_str(table, "path", context, errors)

        keep = table.get("keep")
        if not isinstance(keep, int) or isinstance(keep, bool) or keep < 1:
            errors.add(f"'keep' in {context} must be an integer >= 1")
            keep = None

        host = table.get("host", "")
        user = table.get("user", "")
        ssh_key = table.get("ssh_key", "")
        port = table.get("port", 22)
        ssh_options = table.get("ssh_options", [])
        bwlimit_kbps = table.get("bwlimit_kbps", 0)

        if dest_type == "ssh":
            if not host:
                errors.add(f"'host' in {context} is required for type=ssh")
            if not user:
                errors.add(f"'user' in {context} is required for type=ssh")
            if not ssh_key:
                errors.add(f"'ssh_key' in {context} is required for type=ssh")
            if not isinstance(port, int) or isinstance(port, bool) or not (0 < port < 65536):
                errors.add(f"'port' in {context} must be an integer in 1..65535")
                port = 22
            if not isinstance(ssh_options, list) or not all(
                isinstance(o, str) for o in ssh_options
            ):
                errors.add(f"'ssh_options' in {context} must be a list of strings")
                ssh_options = []
            if (
                not isinstance(bwlimit_kbps, int)
                or isinstance(bwlimit_kbps, bool)
                or bwlimit_kbps < 0
            ):
                errors.add(f"'bwlimit_kbps' in {context} must be a non-negative integer")
                bwlimit_kbps = 0

        if name is None or path is None or keep is None:
            continue

        destinations.append(
            DestinationConfig(
                name=name,
                type=dest_type,
                keep=keep,
                path=path,
                host=host,
                port=port,
                user=user,
                ssh_key=ssh_key,
                ssh_options=tuple(ssh_options),
                bwlimit_kbps=bwlimit_kbps,
            )
        )

    return destinations


def _parse_logging(table: Any, errors: _Errors) -> LoggingConfig:
    context = "[logging]"
    if table is None:
        return LoggingConfig()
    if not isinstance(table, dict):
        errors.add(f"{context} must be a table")
        return LoggingConfig()

    allowed = {"level", "format", "file"}
    _reject_unknown_keys(table, allowed, context, errors)

    level = table.get("level", "info")
    if level not in VALID_LOG_LEVELS:
        errors.add(f"'level' in {context} must be one of {VALID_LOG_LEVELS}, got {level!r}")
        level = "info"

    fmt = table.get("format", "text")
    if fmt not in VALID_LOG_FORMATS:
        errors.add(f"'format' in {context} must be one of {VALID_LOG_FORMATS}, got {fmt!r}")
        fmt = "text"

    return LoggingConfig(level=level, format=fmt, file=table.get("file", ""))


def _parse_lock(table: Any, errors: _Errors) -> LockConfig:
    context = "[lock]"
    if table is None:
        return LockConfig()
    if not isinstance(table, dict):
        errors.add(f"{context} must be a table")
        return LockConfig()

    allowed = {"file"}
    _reject_unknown_keys(table, allowed, context, errors)

    file_str = table.get("file", "/run/mbkeeper/mbkeeper.lock")
    if not isinstance(file_str, str) or not file_str:
        errors.add(f"'file' in {context} must be a non-empty string")
        file_str = "/run/mbkeeper/mbkeeper.lock"

    return LockConfig(file=Path(file_str))


def _parse_hooks(table: Any, errors: _Errors) -> HooksConfig:
    context = "[hooks]"
    if table is None:
        return HooksConfig()
    if not isinstance(table, dict):
        errors.add(f"{context} must be a table")
        return HooksConfig()

    allowed = {"pre_backup", "post_backup", "pre_purge", "post_run"}
    _reject_unknown_keys(table, allowed, context, errors)

    values = {}
    for key in allowed:
        value = table.get(key, "")
        if not isinstance(value, str):
            errors.add(f"'{key}' in {context} must be a string")
            value = ""
        values[key] = value

    return HooksConfig(**values)
