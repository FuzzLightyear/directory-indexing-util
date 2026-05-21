# Copyright (c) 2025 Mercury. All rights reserved.
# SPDX-License-Identifier: MIT

"""CLI entry point for directory-indexing-util.

Run via ``dirindex`` (installed script) or ``python -m directory_indexing_util``.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from loguru import logger
from rich.console import Console

from directory_indexing_util.scanner import scan_directory

_FORMATS = ("parquet", "csv", "json", "ndjson")
_DEFAULT_FORMAT = "parquet"

console = Console()


def _parse_extensions(value: str | None) -> set[str] | None:
    """Parse a comma-separated extension list into a normalized set.

    Strips whitespace, drops leading dots, lowercases each entry, and
    discards empty fragments.  Returns ``None`` when the input yields
    no usable extensions so the scanner can short-circuit filtering.

    Parameters
    ----------
    value : str or None
        Raw CLI argument value (e.g., ``".JPG, png, gif"``).

    Returns
    -------
    set of str or None
        Normalized extension set, or ``None`` when empty.
    """
    if not value:
        return None
    exts = {part.strip().lstrip(".").lower() for part in value.split(",") if part.strip()}
    return exts or None


def _resolve_output_path(output: str | None, fmt: str) -> Path:
    """Determine the final output file path.

    Parameters
    ----------
    output : str or None
        User-supplied ``-o`` value.  May be a file path, a directory, or
        ``None`` (defaults to the current directory).
    fmt : str
        Output format extension (without dot).

    Returns
    -------
    Path
        Resolved absolute path for the output file.
    """
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"scan_{ts}.{fmt}"

    if output is None:
        return Path.cwd() / filename

    target = Path(output)
    if target.is_dir():
        return target / filename
    return target


def _write_dataframe(df: pl.DataFrame, path: Path, fmt: str) -> None:
    """Export a Polars DataFrame in the requested format.

    Parameters
    ----------
    df : pl.DataFrame
        DataFrame to write.
    path : Path
        Destination file path.
    fmt : str
        One of ``parquet``, ``csv``, ``json``, ``ndjson``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "parquet":
        df.write_parquet(path)
    elif fmt == "csv":
        df.write_csv(path)
    elif fmt == "json":
        df.write_json(path)
    elif fmt == "ndjson":
        df.write_ndjson(path)


def _cmd_scan(args: argparse.Namespace) -> None:
    """Execute the ``scan`` subcommand."""
    root = Path(args.directory)
    if not root.exists():
        logger.error("Directory does not exist: {}", root)
        raise SystemExit(1)
    if not root.is_dir():
        logger.error("Not a directory: {}", root)
        raise SystemExit(1)

    fmt = args.format
    if args.output and not Path(args.output).is_dir():
        suffix = Path(args.output).suffix.lstrip(".")
        if suffix in _FORMATS and fmt == _DEFAULT_FORMAT:
            fmt = suffix

    include = _parse_extensions(args.include)
    exclude = _parse_extensions(args.exclude)

    with console.status("[bold cyan]Scanning…") as status:
        df = scan_directory(root, include=include, exclude=exclude)
        status.update(f"[bold cyan]Scanned {df.height:,} files")

    output_path = _resolve_output_path(args.output, fmt)
    _write_dataframe(df, output_path, fmt)

    console.print(f"[green]{df.height:,}[/green] files -> [bold]{output_path}[/bold]")


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with subcommands.

    Returns
    -------
    argparse.ArgumentParser
        Configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="dirindex",
        description="Performant, security-minded directory indexing utility.",
    )
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="Recursively enumerate files in a directory.")
    scan.add_argument("directory", help="Source directory to scan.")
    scan.add_argument(
        "-o", "--output",
        help=(
            "Output file path or directory.  When a directory is given, a "
            "timestamped filename is generated automatically.  "
            "Defaults to the current working directory."
        ),
    )
    scan.add_argument(
        "-f", "--format",
        choices=_FORMATS,
        default=_DEFAULT_FORMAT,
        help=f"Output file format (default: {_DEFAULT_FORMAT}).",
    )
    scan.add_argument(
        "-i", "--include",
        help=(
            "Comma-separated whitelist of file extensions to keep "
            "(e.g., 'jpg,png,gif').  Leading dots and case are normalized.  "
            "Combinable with --exclude."
        ),
    )
    scan.add_argument(
        "-x", "--exclude",
        help=(
            "Comma-separated blacklist of file extensions to drop "
            "(e.g., 'tmp,log,cache').  Leading dots and case are normalized.  "
            "Combinable with --include."
        ),
    )
    scan.set_defaults(func=_cmd_scan)

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = _build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(0)

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{message}")

    args.func(args)


if __name__ == "__main__":
    main()
