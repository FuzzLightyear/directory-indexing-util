# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Performant, security-minded directory walking, file hashing, and indexing.

Public API
----------
The package exposes a small, stable surface for library consumers:

>>> from directory_indexing_util import scan_directory, hash_dataframe, index_directory
>>> df = scan_directory("/path/to/dir")
>>> df = hash_dataframe(df, algorithm="sha256")

For the most common workflow (scan + hash in one call), use
:func:`index_directory`:

>>> df = index_directory("/path/to/dir", algorithm="sha256")

The supported hash algorithms are exposed via :data:`ALGORITHMS` and the
default in :data:`DEFAULT_ALGORITHM`.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import polars as pl

from directory_indexing_util._algorithms import ALGORITHMS, DEFAULT_ALGORITHM
from directory_indexing_util.hasher import hash_dataframe
from directory_indexing_util.scanner import scan_directory

try:
    __version__: str = version("directory-indexing-util")
except PackageNotFoundError:  # pragma: no cover - only triggered without install
    __version__ = "0.0.0+unknown"

__all__ = [
    "ALGORITHMS",
    "DEFAULT_ALGORITHM",
    "__version__",
    "hash_dataframe",
    "index_directory",
    "scan_directory",
]


def index_directory(
    root: Path | str,
    *,
    algorithm: str = DEFAULT_ALGORITHM,
    include: set[str] | None = None,
    workers: int | None = None,
    desc: str | None = None,
) -> pl.DataFrame:
    """Scan *root* and hash every enumerated file in one call.

    Convenience wrapper combining :func:`scan_directory` and
    :func:`hash_dataframe`.  Equivalent to::

        df = scan_directory(root, include=include)
        df = hash_dataframe(df, algorithm=algorithm, workers=workers, desc=desc)

    Parameters
    ----------
    root : Path or str
        Directory to scan.  Must exist and be a directory.
    algorithm : str, default ``"sha256"``
        Hash algorithm.  See :data:`ALGORITHMS` for accepted values.
    include : set of str, optional
        Extension whitelist applied during scanning — see
        :func:`scan_directory` for semantics.
    workers : int or None, default ``None``
        Number of worker threads for the hashing phase.  ``None`` uses
        the auto-tuned default from :func:`hash_dataframe`.
    desc : str or None, default ``None``
        When non-``None``, drives a Rich progress bar during the hashing
        phase.  Library callers leave this as ``None`` for silent
        operation.

    Returns
    -------
    pl.DataFrame
        DataFrame with columns ``file_name``, ``file_path``, and
        ``file_hash`` (the latter ``Utf8`` and nullable).
    """
    df = scan_directory(root, include=include)
    return hash_dataframe(df, algorithm=algorithm, workers=workers, desc=desc)
