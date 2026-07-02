"""Argument parsing and dispatch only. No business logic lives here."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mariabackup_keeper import __version__
from mariabackup_keeper.config import DEFAULT_CONFIG_PATH, load_config
from mariabackup_keeper.errors import KeeperError
from mariabackup_keeper.exit_codes import ExitCode
from mariabackup_keeper.logging_setup import get_logger, setup_logging
from mariabackup_keeper.orchestrator import run as run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mbkeeper",
        description=(
            "Orchestrates MariaDB mariabackup: scheduling, generation retention, "
            "and cross-node backup replication."
        ),
    )
    parser.add_argument("--version", action="version", version=f"mbkeeper {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Run the full pipeline: acquire, store to destinations, purge."
    )
    run_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to the TOML config file (default: {DEFAULT_CONFIG_PATH}).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except KeeperError as exc:
        print(str(exc), file=sys.stderr)
        return int(exc.exit_code)

    setup_logging(config.logging)
    logger = get_logger()

    try:
        if args.command == "run":
            summary = run_pipeline(config)
            return int(summary.exit_code)
    except KeeperError as exc:
        logger.error(str(exc))
        return int(exc.exit_code)
    except Exception as exc:  # CLI boundary: never crash with a raw traceback
        logger.error(f"unexpected error: {exc}", exc_info=True)
        return int(ExitCode.INTERNAL_ERROR)

    return int(ExitCode.USAGE_ERROR)


if __name__ == "__main__":
    sys.exit(main())
