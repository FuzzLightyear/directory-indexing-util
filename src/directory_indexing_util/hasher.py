# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Parallel file hashing via ThreadPoolExecutor and hashlib.file_digest."""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor

import polars as pl

from directory_indexing_util._algorithms import ALGORITHMS, DEFAULT_ALGORITHM
from directory_indexing_util.progress import rprogress

__all__ = ["ALGORITHMS", "DEFAULT_ALGORITHM", "hash_dataframe"]


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


def _default_workers() -> int:
    """Return the auto-tuned worker count: ``min(os.cpu_count() * 2, 32)``.

    Returns
    -------
    int
        Worker count derived from available CPUs, capped at 32 to avoid
        diminishing returns at very high concurrency.
    """
    return min((os.cpu_count() or 1) * 2, 32)


def hash_dataframe(
    df: pl.DataFrame,
    *,
    algorithm: str = DEFAULT_ALGORITHM,
    workers: int | None = None,
    desc: str | None = None,
) -> pl.DataFrame:
    """Hash files referenced by ``df['file_path']`` and return an extended DataFrame.

    Uses ``ThreadPoolExecutor.map`` with ``hashlib.file_digest`` — the
    fastest stdlib strategy per project benchmarks (2,465 MB/s on
    SHA-256).  Order is preserved so the appended column aligns with
    the input rows.

    Parameters
    ----------
    df : pl.DataFrame
        Input DataFrame.  Must contain a ``file_path`` column.
    algorithm : str, default ``"sha256"``
        Any algorithm supported by ``hashlib.file_digest``.
    workers : int or None, default ``None``
        Number of worker threads.  ``None`` selects the auto-tuned
        default ``min(os.cpu_count() * 2, 32)`` from project benchmarks.
        Override when running under CPU quotas, alongside other
        concurrent workloads, or on hardware where the default
        saturates I/O.
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
        If ``file_path`` is missing, *algorithm* is unsupported, or
        *workers* is not a positive integer.
    """
    if "file_path" not in df.columns:
        raise ValueError("DataFrame must contain a 'file_path' column")
    if algorithm not in hashlib.algorithms_available:
        raise ValueError(f"Unsupported hash algorithm: {algorithm!r}")
    if workers is not None and workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")

    paths = df.get_column("file_path").to_list()
    worker_count = workers if workers is not None else _default_workers()

    def _hash(p: str) -> str | None:
        return _hash_file(p, algorithm)

    with ThreadPoolExecutor(max_workers=worker_count) as ex:
        iterator = ex.map(_hash, paths)
        if desc is not None:
            iterator = rprogress(iterator, total=len(paths), desc=desc)
        hashes = list(iterator)

    return df.with_columns(pl.Series("file_hash", hashes, dtype=pl.Utf8))
