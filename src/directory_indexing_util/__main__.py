# Copyright (c) 2025 Mercury. All rights reserved.
# SPDX-License-Identifier: MIT

"""CLI entry point for directory-indexing-util.

Run via ``dirindex`` (installed script) or ``python -m directory_indexing_util``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from loguru import logger
from rich.console import Console

from directory_indexing_util.hasher import ALGORITHMS, DEFAULT_ALGORITHM, hash_dataframe
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
        Number of rows in the produced index.
    """
    payload = {
        "command": command,
        "input_path": input_path,
        "output_path": output_path,
        "hash_algorithm": algorithm,
        "file_count": file_count,
        "created_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8", newline="")


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

    with console.status("[bold cyan]Scanning…") as status:
        df = scan_directory(root, include=include)
        status.update(f"[bold cyan]Scanned {df.height:,} files")

    output_path = _resolve_output_path(args.output, fmt)
    _write_dataframe(df, output_path, fmt)

    console.print(f"[green]{df.height:,}[/green] files -> [bold]{output_path}[/bold]")


def _cmd_hash(args: argparse.Namespace) -> None:
    """Execute the ``hash`` subcommand."""
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input file does not exist: {}", input_path)
        raise SystemExit(1)
    if not input_path.is_file():
        logger.error("Not a file: {}", input_path)
        raise SystemExit(1)

    fmt = args.format
    if args.output and not Path(args.output).is_dir():
        suffix = Path(args.output).suffix.lstrip(".")
        if suffix in _FORMATS and fmt == _DEFAULT_FORMAT:
            fmt = suffix

    try:
        df = _read_dataframe(input_path)
    except ValueError as exc:
        logger.error("{}", exc)
        raise SystemExit(1) from exc

    if "file_path" not in df.columns:
        logger.error("Input file missing required 'file_path' column.")
        raise SystemExit(1)

    df = hash_dataframe(df, algorithm=args.algorithm, workers=args.workers, desc="Hashing")

    output_path = _resolve_output_path(args.output, fmt, prefix="hash")
    _write_dataframe(df, output_path, fmt)
    _write_manifest(
        output_path.with_suffix(".meta.json"),
        command="hash",
        input_path=str(input_path.resolve()),
        output_path=str(output_path),
        algorithm=args.algorithm,
        file_count=df.height,
    )

    console.print(f"[green]{df.height:,}[/green] hashes -> [bold]{output_path}[/bold]")


def _cmd_index(args: argparse.Namespace) -> None:
    """Execute the ``index`` subcommand — scan + hash in a single pass."""
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

    with console.status("[bold cyan]Scanning…") as status:
        df = scan_directory(root, include=include)
        status.update(f"[bold cyan]Scanned {df.height:,} files")

    df = hash_dataframe(df, algorithm=args.algorithm, workers=args.workers, desc="Hashing")

    output_path = _resolve_output_path(args.output, fmt, prefix="index")
    _write_dataframe(df, output_path, fmt)
    _write_manifest(
        output_path.with_suffix(".meta.json"),
        command="index",
        input_path=str(root.resolve()),
        output_path=str(output_path),
        algorithm=args.algorithm,
        file_count=df.height,
    )

    console.print(f"[green]{df.height:,}[/green] indexed -> [bold]{output_path}[/bold]")


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

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{message}")

    args.func(args)


if __name__ == "__main__":
    main()
