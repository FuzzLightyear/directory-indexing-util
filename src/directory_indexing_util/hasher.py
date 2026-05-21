# Copyright (c) 2025 Mercury. All rights reserved.
# SPDX-License-Identifier: MIT

"""Parallel file hashing via ThreadPoolExecutor and hashlib.file_digest."""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor

import polars as pl

from directory_indexing_util.progress import rprogress

ALGORITHMS: tuple[str, ...] = ("sha256", "sha512", "blake2b", "md5")
DEFAULT_ALGORITHM = "sha256"


def _hash_file(path: str, algorithm: str) -> str | None:
    """Compute a hex digest of *path*.

    Parameters
    ----------
    path : str
        Absolute path to the file.
    algorithm : str
        ``hashlib`` algorithm name (e.g., ``"sha256"``).

    Returns
    -------
    str or None
        Lowercase hex digest, or ``None`` if the file cannot be opened.
    """
    try:
        with open(path, "rb") as f:  # noqa: S324 - algorithm is caller-validated
            return hashlib.file_digest(f, algorithm).hexdigest()
    except (PermissionError, OSError):
        return None


def hash_dataframe(
    df: pl.DataFrame,
    *,
    algorithm: str = DEFAULT_ALGORITHM,
    desc: str | None = None,
) -> pl.DataFrame:
    """Hash files referenced by ``df['file_path']`` and return an extended DataFrame.

    Uses ``ThreadPoolExecutor.map`` with ``hashlib.file_digest`` — the
    fastest stdlib strategy per project benchmarks (2,465 MB/s on
    SHA-256).  Worker count is ``min(os.cpu_count() * 2, 32)`` and order
    is preserved so the appended column aligns with the input rows.

    Parameters
    ----------
    df : pl.DataFrame
        Input DataFrame.  Must contain a ``file_path`` column.
    algorithm : str, default ``"sha256"``
        Any algorithm supported by ``hashlib.file_digest``.
    desc : str or None, default ``None``
        When non-``None``, drives a Rich progress bar with the given
        label.  Library callers leave this as ``None`` for silent
        operation; the CLI passes a description explicitly.

    Returns
    -------
    pl.DataFrame
        *df* with an appended ``file_hash`` column (``Utf8``, nullable
        where the file could not be read).

    Raises
    ------
    ValueError
        If ``file_path`` is missing or *algorithm* is unsupported.
    """
    if "file_path" not in df.columns:
        raise ValueError("DataFrame must contain a 'file_path' column")
    if algorithm not in hashlib.algorithms_available:
        raise ValueError(f"Unsupported hash algorithm: {algorithm!r}")

    paths = df.get_column("file_path").to_list()
    workers = min((os.cpu_count() or 1) * 2, 32)

    def _hash(p: str) -> str | None:
        return _hash_file(p, algorithm)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        iterator = ex.map(_hash, paths)
        if desc is not None:
            iterator = rprogress(iterator, total=len(paths), desc=desc)
        hashes = list(iterator)

    return df.with_columns(pl.Series("file_hash", hashes, dtype=pl.Utf8))
