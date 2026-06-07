# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""CLI entry point for directory-indexing-util.

Run via ``dirindex`` (installed script) or ``python -m directory_indexing_util``.

Notes
-----
Module-level imports are intentionally limited to stdlib plus the dependency-free
:mod:`directory_indexing_util._algorithms` module.  This keeps ``dirindex --version``
and ``dirindex --help`` fast by avoiding the cost of loading polars, rich, and
loguru when no command will actually run.  Command handlers import what they
need at call time.
"""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING

from directory_indexing_util._algorithms import ALGORITHMS, DEFAULT_ALGORITHM
from directory_indexing_util.formats import (
    _DEFAULT_FORMAT,
    _FORMATS,
    _read_dataframe,
    _resolve_output_path,
    _write_dataframe,
    _write_manifest,
)

if TYPE_CHECKING:
    import polars as pl
    from rich.console import Console


def _get_version() -> str:
    """Return the installed package version, or a sentinel if uninstalled.

    Returns
    -------
    str
        Package version string read from installed metadata, or
        ``"0.0.0+unknown"`` if the package cannot be located (e.g.,
        running directly from source without an editable install).
    """
    try:
        return version("directory-indexing-util")
    except PackageNotFoundError:  # pragma: no cover - only without install
        return "0.0.0+unknown"


def _infer_format(args: argparse.Namespace) -> str:
    """Determine the effective output format for a command invocation.

    When the user supplied ``-o`` as a *file path* (not a directory) and
    its extension is one of the recognised formats, that extension wins
    over the argparse-default format, letting ``-o report.csv`` Just
    Work without also requiring ``-f csv``.  An explicit ``-f`` (i.e.,
    something other than the default) is always respected.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.  Must have ``output`` (``str`` or ``None``)
        and ``format`` (member of :data:`_FORMATS`) attributes.

    Returns
    -------
    str
        Final format string (one of :data:`_FORMATS`).
    """
    fmt = args.format
    if args.output and not Path(args.output).is_dir():
        suffix = Path(args.output).suffix.lstrip(".").lower()
        if suffix in _FORMATS and fmt == _DEFAULT_FORMAT:
            fmt = suffix
    return fmt


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


def _require_directory(value: str) -> Path:
    """Return *value* as an existing directory, or exit with an error.

    Parameters
    ----------
    value : str
        User-supplied path expected to be an existing directory.

    Returns
    -------
    Path
        The path, confirmed to exist and to be a directory.

    Raises
    ------
    SystemExit
        With code 1 if the path is missing or is not a directory.
    """
    from loguru import logger  # noqa: PLC0415 - lazy

    path = Path(value)
    if not path.exists():
        logger.error("Directory does not exist: {}", path)
        raise SystemExit(1)
    if not path.is_dir():
        logger.error("Not a directory: {}", path)
        raise SystemExit(1)
    return path


def _require_file(value: str) -> Path:
    """Return *value* as an existing file, or exit with an error.

    Parameters
    ----------
    value : str
        User-supplied path expected to be an existing regular file.

    Returns
    -------
    Path
        The path, confirmed to exist and to be a file.

    Raises
    ------
    SystemExit
        With code 1 if the path is missing or is not a file.
    """
    from loguru import logger  # noqa: PLC0415 - lazy

    path = Path(value)
    if not path.exists():
        logger.error("Input file does not exist: {}", path)
        raise SystemExit(1)
    if not path.is_file():
        logger.error("Not a file: {}", path)
        raise SystemExit(1)
    return path


def _scan_with_status(console: Console, root: Path, include: set[str] | None) -> pl.DataFrame:
    """Scan *root* under a Rich status spinner and return the result.

    Parameters
    ----------
    console : rich.console.Console
        Console used to render the transient status line.
    root : Path
        Directory to scan.
    include : set of str or None
        Extension whitelist passed through to the scanner.

    Returns
    -------
    pl.DataFrame
        The scan result.
    """
    from directory_indexing_util.scanner import scan_directory  # noqa: PLC0415 - lazy

    with console.status("[bold cyan]Scanning…") as status:
        df = scan_directory(root, include=include)
        status.update(f"[bold cyan]Scanned {df.height:,} files")
    return df


def _emit(
    console: Console,
    df: pl.DataFrame,
    *,
    output: str | None,
    fmt: str,
    prefix: str,
    noun: str,
    manifest: tuple[str, str, str] | None = None,
) -> None:
    """Write *df* to disk and print a one-line summary.

    Parameters
    ----------
    console : rich.console.Console
        Console used for the summary line.
    df : pl.DataFrame
        DataFrame to write.
    output : str or None
        User-supplied output path or directory.
    fmt : str
        Output format.
    prefix : str
        Filename stem prefix for a generated timestamped name.
    noun : str
        Word describing the rows in the summary (e.g., ``"files"``).
    manifest : tuple of (command, input_path, algorithm) or None
        When given, a sidecar ``.meta.json`` is written and the summary
        reports any rows whose ``file_hash`` is ``null``.
    """
    output_path = _resolve_output_path(output, fmt, prefix=prefix)
    _write_dataframe(df, output_path, fmt)

    failed_count = 0
    if manifest is not None:
        command, input_path, algorithm = manifest
        failed_count = int(df.get_column("file_hash").null_count())
        _write_manifest(
            output_path.with_suffix(".meta.json"),
            command=command,
            input_path=input_path,
            output_path=str(output_path),
            algorithm=algorithm,
            file_count=df.height,
            failed_count=failed_count,
        )

    summary = f"[green]{df.height:,}[/green] {noun}"
    if failed_count:
        summary += f" ([yellow]{failed_count} unreadable[/yellow])"
    console.print(f"{summary} -> [bold]{output_path}[/bold]")


def _cmd_scan(args: argparse.Namespace) -> None:
    """Execute the ``scan`` subcommand."""
    from rich.console import Console  # noqa: PLC0415 - lazy

    console = Console()

    root = _require_directory(args.directory)
    fmt = _infer_format(args)
    include = _parse_extensions(args.include)

    df = _scan_with_status(console, root, include)
    _emit(console, df, output=args.output, fmt=fmt, prefix="scan", noun="files")


def _cmd_hash(args: argparse.Namespace) -> None:
    """Execute the ``hash`` subcommand."""
    from loguru import logger  # noqa: PLC0415 - lazy
    from rich.console import Console  # noqa: PLC0415 - lazy

    from directory_indexing_util.hasher import hash_dataframe  # noqa: PLC0415

    console = Console()

    input_path = _require_file(args.input)

    fmt = _infer_format(args)

    try:
        df = _read_dataframe(input_path)
    except ValueError as exc:
        logger.error("{}", exc)
        raise SystemExit(1) from exc

    if "file_path" not in df.columns:
        logger.error("Input file missing required 'file_path' column.")
        raise SystemExit(1)

    df = hash_dataframe(df, algorithm=args.algorithm, workers=args.workers, desc="Hashing")

    _emit(
        console,
        df,
        output=args.output,
        fmt=fmt,
        prefix="hash",
        noun="hashes",
        manifest=("hash", str(input_path.resolve()), args.algorithm),
    )


def _cmd_index(args: argparse.Namespace) -> None:
    """Execute the ``index`` subcommand: scan + hash in a single pass."""
    from rich.console import Console  # noqa: PLC0415 - lazy

    from directory_indexing_util.hasher import hash_dataframe  # noqa: PLC0415

    console = Console()

    root = _require_directory(args.directory)
    fmt = _infer_format(args)
    include = _parse_extensions(args.include)

    df = _scan_with_status(console, root, include)
    df = hash_dataframe(df, algorithm=args.algorithm, workers=args.workers, desc="Hashing")

    _emit(
        console,
        df,
        output=args.output,
        fmt=fmt,
        prefix="index",
        noun="indexed",
        manifest=("index", str(root.resolve()), args.algorithm),
    )


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``-o/--output`` and ``-f/--format`` options to *parser*."""
    parser.add_argument(
        "-o",
        "--output",
        help=(
            "Output file path or directory.  When a directory is given, a "
            "timestamped filename is generated automatically.  "
            "Defaults to the current working directory."
        ),
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=_FORMATS,
        default=_DEFAULT_FORMAT,
        help=f"Output file format (default: {_DEFAULT_FORMAT}).",
    )


def _add_include_arg(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``-i/--include`` extension whitelist option to *parser*."""
    parser.add_argument(
        "-i",
        "--include",
        help=(
            "Comma-separated whitelist of file extensions to keep "
            "(e.g., 'jpg,png,gif').  Leading dots and case are normalized."
        ),
    )


def _add_hash_args(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``-a/--algorithm`` and ``-w/--workers`` options to *parser*."""
    parser.add_argument(
        "-a",
        "--algorithm",
        choices=ALGORITHMS,
        default=DEFAULT_ALGORITHM,
        help=f"Hash algorithm (default: {DEFAULT_ALGORITHM}).",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help=(
            "Worker thread count for hashing.  Defaults to an auto-tuned "
            "value of min(cpu_count * 2, 32).  Lower it under CPU quotas "
            "or when running multiple instances concurrently."
        ),
    )


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
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="Recursively enumerate files in a directory.")
    scan.add_argument("directory", help="Source directory to scan.")
    _add_output_args(scan)
    _add_include_arg(scan)
    scan.set_defaults(func=_cmd_scan)

    hash_cmd = sub.add_parser(
        "hash",
        help="Compute file hashes for paths referenced by a scan output.",
    )
    hash_cmd.add_argument(
        "input",
        help="Scan output file (parquet/csv/json/ndjson) containing a 'file_path' column.",
    )
    _add_output_args(hash_cmd)
    _add_hash_args(hash_cmd)
    hash_cmd.set_defaults(func=_cmd_hash)

    index_cmd = sub.add_parser(
        "index",
        help="Scan a directory and hash all files in a single pass.",
    )
    index_cmd.add_argument("directory", help="Source directory to scan and hash.")
    _add_output_args(index_cmd)
    _add_include_arg(index_cmd)
    _add_hash_args(index_cmd)
    index_cmd.set_defaults(func=_cmd_index)

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = _build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(0)

    from loguru import logger  # noqa: PLC0415 - lazy, only when a command runs

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{message}")

    args.func(args)


if __name__ == "__main__":
    main()
