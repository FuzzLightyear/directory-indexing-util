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
import json
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING

from directory_indexing_util._algorithms import ALGORITHMS, DEFAULT_ALGORITHM

if TYPE_CHECKING:
    import polars as pl

_FORMATS = ("parquet", "csv", "json", "ndjson")
_DEFAULT_FORMAT = "parquet"


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
    over the argparse-default format — letting ``-o report.csv`` Just
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


def _resolve_output_path(output: str | None, fmt: str, *, prefix: str = "scan") -> Path:
    """Determine the final output file path.

    Parameters
    ----------
    output : str or None
        User-supplied ``-o`` value.  May be a file path, a directory, or
        ``None`` (defaults to the current directory).
    fmt : str
        Output format extension (without dot).
    prefix : str, default ``"scan"``
        Filename stem prefix used when a timestamped name is generated.

    Returns
    -------
    Path
        Resolved absolute path for the output file.
    """
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{ts}.{fmt}"

    if output is None:
        return Path.cwd() / filename

    target = Path(output)
    if target.is_dir():
        return target / filename
    return target


def _sanitize_csv(df: pl.DataFrame) -> pl.DataFrame:
    """Neutralize spreadsheet formula injection in string columns.

    Parameters
    ----------
    df : pl.DataFrame
        DataFrame about to be written as CSV.

    Returns
    -------
    pl.DataFrame
        A copy in which every ``Utf8`` cell beginning with ``=``, ``+``,
        ``-``, ``@``, a tab, or a carriage return is prefixed with a single
        quote, so a spreadsheet treats it as text rather than a formula.

    Notes
    -----
    Only the CSV writer applies this.  Parquet, JSON, and NDJSON are data
    formats that no spreadsheet evaluates, so they are written verbatim.
    """
    import polars as pl  # noqa: PLC0415 - lazy import keeps --help/--version fast

    lead = r"^[=+\-@\t\r]"
    string_cols = [name for name, dtype in df.schema.items() if dtype == pl.Utf8]
    if not string_cols:
        return df
    return df.with_columns(
        pl.when(pl.col(name).str.contains(lead))
        .then(pl.lit("'") + pl.col(name))
        .otherwise(pl.col(name))
        .alias(name)
        for name in string_cols
    )


def _write_dataframe(df: pl.DataFrame, path: Path, fmt: str) -> None:
    """Export a Polars DataFrame in the requested format.

    Parameters
    ----------
    df : pl.DataFrame
        DataFrame to write.  The methods called are bound to the
        instance, so this helper does not import polars itself.
    path : Path
        Destination file path.
    fmt : str
        One of ``parquet``, ``csv``, ``json``, ``ndjson``.

    Raises
    ------
    ValueError
        If *fmt* is not a recognised format — defensive check, since
        argparse validates this for CLI use.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "parquet":
        df.write_parquet(path)
    elif fmt == "csv":
        _sanitize_csv(df).write_csv(path)
    elif fmt == "json":
        df.write_json(path)
    elif fmt == "ndjson":
        df.write_ndjson(path)
    else:
        raise ValueError(f"Unsupported output format: {fmt!r}")


def _read_dataframe(path: Path) -> pl.DataFrame:
    """Read a scan output file, dispatching on file extension.

    Parameters
    ----------
    path : Path
        Input file path.  Format inferred from extension.

    Returns
    -------
    pl.DataFrame
        Parsed DataFrame.

    Raises
    ------
    ValueError
        If the file extension is not a supported format.
    """
    import polars as pl  # noqa: PLC0415 - lazy import keeps --help/--version fast

    ext = path.suffix.lstrip(".").lower()
    if ext == "parquet":
        return pl.read_parquet(path)
    if ext == "csv":
        return pl.read_csv(path)
    if ext == "json":
        return pl.read_json(path)
    if ext == "ndjson":
        return pl.read_ndjson(path)
    raise ValueError(f"Unsupported input format: {ext!r}")


def _write_manifest(
    path: Path,
    *,
    command: str,
    input_path: str,
    output_path: str,
    algorithm: str,
    file_count: int,
    failed_count: int,
) -> None:
    """Write a JSON sidecar manifest documenting the run.

    Parameters
    ----------
    path : Path
        Destination of the ``.meta.json`` file (caller-determined).
    command : str
        Subcommand that produced the output (``"hash"`` or ``"index"``).
    input_path : str
        Original input — either the scan file (``hash``) or the source
        directory (``index``).
    output_path : str
        Data file written alongside this manifest.
    algorithm : str
        Hash algorithm used for the run.
    file_count : int
        Total number of rows in the produced index.
    failed_count : int
        Subset of *file_count* for which ``file_hash`` is ``null`` —
        files that existed at scan time but could not be opened or read
        during hashing (e.g., deleted in between, permissions changed,
        locked by another process).  ``0`` when every file hashed
        successfully.
    """
    payload = {
        "command": command,
        "input_path": input_path,
        "output_path": output_path,
        "hash_algorithm": algorithm,
        "file_count": file_count,
        "failed_count": failed_count,
        "created_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8", newline="")


def _cmd_scan(args: argparse.Namespace) -> None:
    """Execute the ``scan`` subcommand."""
    from loguru import logger  # noqa: PLC0415 - lazy
    from rich.console import Console  # noqa: PLC0415 - lazy

    from directory_indexing_util.scanner import scan_directory  # noqa: PLC0415

    console = Console()

    root = Path(args.directory)
    if not root.exists():
        logger.error("Directory does not exist: {}", root)
        raise SystemExit(1)
    if not root.is_dir():
        logger.error("Not a directory: {}", root)
        raise SystemExit(1)

    fmt = _infer_format(args)

    include = _parse_extensions(args.include)

    with console.status("[bold cyan]Scanning…") as status:
        df = scan_directory(root, include=include)
        status.update(f"[bold cyan]Scanned {df.height:,} files")

    output_path = _resolve_output_path(args.output, fmt)
    _write_dataframe(df, output_path, fmt)

    console.print(f"[green]{df.height:,}[/green] files -> [bold]{output_path}[/bold]")


def _cmd_hash(args: argparse.Namespace) -> None:
    """Execute the ``hash`` subcommand."""
    from loguru import logger  # noqa: PLC0415 - lazy
    from rich.console import Console  # noqa: PLC0415 - lazy

    from directory_indexing_util.hasher import hash_dataframe  # noqa: PLC0415

    console = Console()

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input file does not exist: {}", input_path)
        raise SystemExit(1)
    if not input_path.is_file():
        logger.error("Not a file: {}", input_path)
        raise SystemExit(1)

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
    failed_count = int(df.get_column("file_hash").null_count())

    output_path = _resolve_output_path(args.output, fmt, prefix="hash")
    _write_dataframe(df, output_path, fmt)
    _write_manifest(
        output_path.with_suffix(".meta.json"),
        command="hash",
        input_path=str(input_path.resolve()),
        output_path=str(output_path),
        algorithm=args.algorithm,
        file_count=df.height,
        failed_count=failed_count,
    )

    summary = f"[green]{df.height:,}[/green] hashes"
    if failed_count:
        summary += f" ([yellow]{failed_count} unreadable[/yellow])"
    console.print(f"{summary} -> [bold]{output_path}[/bold]")


def _cmd_index(args: argparse.Namespace) -> None:
    """Execute the ``index`` subcommand — scan + hash in a single pass."""
    from loguru import logger  # noqa: PLC0415 - lazy
    from rich.console import Console  # noqa: PLC0415 - lazy

    from directory_indexing_util.hasher import hash_dataframe  # noqa: PLC0415
    from directory_indexing_util.scanner import scan_directory  # noqa: PLC0415

    console = Console()

    root = Path(args.directory)
    if not root.exists():
        logger.error("Directory does not exist: {}", root)
        raise SystemExit(1)
    if not root.is_dir():
        logger.error("Not a directory: {}", root)
        raise SystemExit(1)

    fmt = _infer_format(args)

    include = _parse_extensions(args.include)

    with console.status("[bold cyan]Scanning…") as status:
        df = scan_directory(root, include=include)
        status.update(f"[bold cyan]Scanned {df.height:,} files")

    df = hash_dataframe(df, algorithm=args.algorithm, workers=args.workers, desc="Hashing")
    failed_count = int(df.get_column("file_hash").null_count())

    output_path = _resolve_output_path(args.output, fmt, prefix="index")
    _write_dataframe(df, output_path, fmt)
    _write_manifest(
        output_path.with_suffix(".meta.json"),
        command="index",
        input_path=str(root.resolve()),
        output_path=str(output_path),
        algorithm=args.algorithm,
        file_count=df.height,
        failed_count=failed_count,
    )

    summary = f"[green]{df.height:,}[/green] indexed"
    if failed_count:
        summary += f" ([yellow]{failed_count} unreadable[/yellow])"
    console.print(f"{summary} -> [bold]{output_path}[/bold]")


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
        "-V", "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
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
            "(e.g., 'jpg,png,gif').  Leading dots and case are normalized."
        ),
    )
    scan.set_defaults(func=_cmd_scan)

    hash_cmd = sub.add_parser(
        "hash",
        help="Compute file hashes for paths referenced by a scan output.",
    )
    hash_cmd.add_argument(
        "input",
        help=(
            "Scan output file (parquet/csv/json/ndjson) containing a "
            "'file_path' column."
        ),
    )
    hash_cmd.add_argument(
        "-o", "--output",
        help=(
            "Output file path or directory.  When a directory is given, a "
            "timestamped filename is generated automatically.  "
            "Defaults to the current working directory."
        ),
    )
    hash_cmd.add_argument(
        "-f", "--format",
        choices=_FORMATS,
        default=_DEFAULT_FORMAT,
        help=f"Output file format (default: {_DEFAULT_FORMAT}).",
    )
    hash_cmd.add_argument(
        "-a", "--algorithm",
        choices=ALGORITHMS,
        default=DEFAULT_ALGORITHM,
        help=f"Hash algorithm (default: {DEFAULT_ALGORITHM}).",
    )
    hash_cmd.add_argument(
        "-w", "--workers",
        type=int,
        default=None,
        help=(
            "Worker thread count for hashing.  Defaults to an auto-tuned "
            "value of min(cpu_count * 2, 32).  Lower it under CPU quotas "
            "or when running multiple instances concurrently."
        ),
    )
    hash_cmd.set_defaults(func=_cmd_hash)

    index_cmd = sub.add_parser(
        "index",
        help="Scan a directory and hash all files in a single pass.",
    )
    index_cmd.add_argument("directory", help="Source directory to scan and hash.")
    index_cmd.add_argument(
        "-o", "--output",
        help=(
            "Output file path or directory.  When a directory is given, a "
            "timestamped filename is generated automatically.  "
            "Defaults to the current working directory."
        ),
    )
    index_cmd.add_argument(
        "-f", "--format",
        choices=_FORMATS,
        default=_DEFAULT_FORMAT,
        help=f"Output file format (default: {_DEFAULT_FORMAT}).",
    )
    index_cmd.add_argument(
        "-i", "--include",
        help=(
            "Comma-separated whitelist of file extensions to keep "
            "(e.g., 'jpg,png,gif').  Leading dots and case are normalized."
        ),
    )
    index_cmd.add_argument(
        "-a", "--algorithm",
        choices=ALGORITHMS,
        default=DEFAULT_ALGORITHM,
        help=f"Hash algorithm (default: {DEFAULT_ALGORITHM}).",
    )
    index_cmd.add_argument(
        "-w", "--workers",
        type=int,
        default=None,
        help=(
            "Worker thread count for hashing.  Defaults to an auto-tuned "
            "value of min(cpu_count * 2, 32).  Lower it under CPU quotas "
            "or when running multiple instances concurrently."
        ),
    )
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
