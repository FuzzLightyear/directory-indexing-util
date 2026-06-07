# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Output-path resolution, format-aware DataFrame I/O, and the run manifest.

These helpers are independent of argument parsing, so they live apart from the
CLI entry point.  Polars is imported lazily inside the readers and the CSV
sanitizer, so importing this module stays cheap and keeps ``dirindex --version``
and ``dirindex --help`` fast.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

_FORMATS = ("parquet", "csv", "json", "ndjson")
_DEFAULT_FORMAT = "parquet"


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
        If *fmt* is not a recognised format, a defensive check, since
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
        Original input, either the scan file (``hash``) or the source
        directory (``index``).
    output_path : str
        Data file written alongside this manifest.
    algorithm : str
        Hash algorithm used for the run.
    file_count : int
        Total number of rows in the produced index.
    failed_count : int
        Subset of *file_count* for which ``file_hash`` is ``null``,
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
