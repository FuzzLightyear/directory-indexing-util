# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Security-minded recursive directory scanning via iterative os.scandir."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import polars as pl


def scan_directory(root: Path) -> pl.DataFrame:
    """Recursively enumerate regular files under *root*.

    Uses an iterative stack-based ``os.scandir`` traversal — the fastest
    enumeration strategy per project benchmarks.  Symlinks are skipped and
    every resolved path is validated to stay within *root*, preventing
    directory-junction escapes.

    Parameters
    ----------
    root : Path
        Directory to scan.  Must exist and be a directory.

    Returns
    -------
    pl.DataFrame
        DataFrame with columns ``file_name`` (``Utf8``) and ``file_path``
        (``Utf8``).  See :ref:`scan-output-format` in the README for the
        full schema specification.

    Raises
    ------
    FileNotFoundError
        If *root* does not exist.
    NotADirectoryError
        If *root* exists but is not a directory.
    """
    root_resolved = root.resolve(strict=True)
    if not root_resolved.is_dir():
        raise NotADirectoryError(root_resolved)

    root_str = str(root_resolved)
    root_prefix = root_str + os.sep
    names: list[str] = []
    paths: list[str] = []
    stack: list[Path] = [root_resolved]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue

                    if entry.is_dir(follow_symlinks=False):
                        resolved = str(Path(entry.path).resolve())
                        if resolved == root_str or resolved.startswith(root_prefix):
                            stack.append(Path(entry.path))
                        continue

                    if not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        if not stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
                            continue
                    except OSError:
                        continue

                    resolved = str(Path(entry.path).resolve())
                    if resolved == root_str or resolved.startswith(root_prefix):
                        names.append(entry.name)
                        paths.append(resolved)
        except PermissionError:
            continue

    return pl.DataFrame(
        {"file_name": names, "file_path": paths},
        schema={"file_name": pl.Utf8, "file_path": pl.Utf8},
    )
