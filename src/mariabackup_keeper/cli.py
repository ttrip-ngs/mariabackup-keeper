"""Argument parsing and dispatch only. No business logic lives here."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mariabackup_keeper import __version__
from mariabackup_keeper.config import DEFAULT_CONFIG_PATH, Config, load_config
from mariabackup_keeper.destinations import build_destination
from mariabackup_keeper.errors import DestinationError, KeeperError
from mariabackup_keeper.exit_codes import ExitCode
from mariabackup_keeper.logging_setup import get_logger, setup_logging
from mariabackup_keeper.orchestrator import PurgeSummary
from mariabackup_keeper.orchestrator import purge as purge_pipeline
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
    _add_config_arg(run_parser)

    purge_parser = subparsers.add_parser(
        "purge", help="Purge old generations per each destination's retention policy."
    )
    _add_config_arg(purge_parser)
    purge_parser.add_argument(
        "--destination",
        action="append",
        dest="destinations",
        metavar="NAME",
        help="Limit to this destination name (repeatable). Default: all destinations.",
    )
    purge_parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be deleted without deleting."
    )

    list_parser = subparsers.add_parser("list", help="List generations known to each destination.")
    _add_config_arg(list_parser)
    list_parser.add_argument(
        "--destination", metavar="NAME", help="Limit to this destination name."
    )

    return parser


def _add_config_arg(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to the TOML config file (default: {DEFAULT_CONFIG_PATH}).",
    )


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
            return int(run_pipeline(config).exit_code)
        if args.command == "purge":
            destination_names = set(args.destinations) if args.destinations else None
            summary = purge_pipeline(
                config, destination_names=destination_names, dry_run=args.dry_run
            )
            _print_purge_summary(summary, dry_run=args.dry_run)
            return int(summary.exit_code)
        if args.command == "list":
            return _cmd_list(config, args.destination)
    except KeeperError as exc:
        logger.error(str(exc))
        return int(exc.exit_code)
    except Exception as exc:  # CLI boundary: never crash with a raw traceback
        logger.error(f"unexpected error: {exc}", exc_info=True)
        return int(ExitCode.INTERNAL_ERROR)

    return int(ExitCode.USAGE_ERROR)


def _print_purge_summary(summary: PurgeSummary, dry_run: bool) -> None:
    verb = "would delete" if dry_run else "deleted"
    for result in summary.results:
        if result.error:
            print(f"[{result.name}] error: {result.error}")
        elif result.deleted:
            print(f"[{result.name}] {verb}: {', '.join(result.deleted)}")
        else:
            print(f"[{result.name}] nothing to purge (kept {len(result.kept)} generations)")


def _cmd_list(config: Config, destination_filter: str | None) -> int:
    had_error = False

    for dest_config in config.destinations:
        if destination_filter and dest_config.name != destination_filter:
            continue

        print(f"[{dest_config.name}] (keep={dest_config.keep})")
        destination = build_destination(dest_config, config.transfer)
        try:
            backups = sorted(destination.list_backups(), key=lambda b: b.backup_id, reverse=True)
        except DestinationError as exc:
            print(f"  error: {exc}")
            had_error = True
            continue

        if not backups:
            print("  (no generations)")
        for backup in backups:
            status = "complete" if backup.complete else "partial"
            print(f"  {backup.backup_id}  {status}  stored_at={backup.stored_at.isoformat()}")

    return int(ExitCode.PRECONDITION_FAILED) if had_error else int(ExitCode.SUCCESS)


if __name__ == "__main__":
    sys.exit(main())
