"""Structured logging setup: plain text or one-JSON-object-per-line."""

from __future__ import annotations

import json
import logging
import sys

from mariabackup_keeper.config import LoggingConfig

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

LOGGER_NAME = "mariabackup_keeper"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "message": record.getMessage(),
            "run_id": getattr(record, "run_id", None),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        run_id = getattr(record, "run_id", None)
        prefix = f"[{run_id}] " if run_id else ""
        base = self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z")
        text = f"{base} {record.levelname:<7} {prefix}{record.getMessage()}"
        if record.exc_info:
            text += "\n" + self.formatException(record.exc_info)
        return text


class RunIdFilter(logging.Filter):
    """Injects a run_id (the backup generation ID) into every record."""

    def __init__(self, run_id: str | None = None) -> None:
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        return True


def setup_logging(config: LoggingConfig) -> RunIdFilter:
    """Configure the package logger per config. Returns the filter so callers
    can set run_id once a backup generation ID has been assigned."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_LEVELS[config.level])
    logger.handlers.clear()

    formatter: logging.Formatter = _JsonFormatter() if config.format == "json" else _TextFormatter()
    run_id_filter = RunIdFilter()

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(run_id_filter)
    logger.addHandler(stream_handler)

    if config.file:
        file_handler = logging.FileHandler(config.file)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(run_id_filter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return run_id_filter


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
