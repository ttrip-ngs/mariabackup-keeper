"""Destination type registry.

Each backend module registers its class via @register("type_name") on import.
build_destination() is the single place that dispatches config.type -> class,
so adding a new backend (or later, an entry_points-based plugin loader) never
touches call sites elsewhere in the codebase.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from mariabackup_keeper.config import DestinationConfig, TransferConfig
from mariabackup_keeper.destinations.base import Destination
from mariabackup_keeper.errors import ConfigError

DESTINATION_TYPES: dict[str, type[Destination]] = {}

T = TypeVar("T", bound=type[Destination])


def register(type_name: str) -> Callable[[T], T]:
    def decorator(cls: T) -> T:
        DESTINATION_TYPES[type_name] = cls
        return cls

    return decorator


def build_destination(config: DestinationConfig, transfer: TransferConfig) -> Destination:
    try:
        destination_cls = DESTINATION_TYPES[config.type]
    except KeyError as exc:
        raise ConfigError(f"unknown destination type '{config.type}'") from exc
    return destination_cls.from_config(config, transfer)


from mariabackup_keeper.destinations import local, ssh  # noqa: E402,F401
