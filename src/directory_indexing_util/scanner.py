# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Security-minded recursive directory scanning via iterative os.scandir."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import polars as pl


def scan_directory(
    root: Path | str,
    *,
    include: set[str] | None = None,
) -> pl.DataFrame:
    """Recursively enumerate regular files under *root*.

    Uses an iterative stack-based ``os.scandir`` traversal — the fastest
    enumeration strategy per project benchmarks.  Symlinks are skipped and
    every resolved path is validated to stay within *root*, preventing
    directory-junction escapes.

    Parameters
    ----------
    root : Path or str
        Directory to scan.  Must exist and be a directory.  ``str``
        inputs are accepted for ergonomic library use and converted
        internally.
    include : set of str, optional
        Whitelist of normalized lowercase extensions (without leading
        dot) to keep.  Files whose extension is not in this set are
        skipped.  Files with no extension match ``""``.  ``None`` keeps
        every file.

    Returns
    -------
    pl.DataFrame
        DataFrame with columns ``file_name`` (``Utf8``) and ``file_path``
        (``Utf8``).  See the Scan Output Format section in the README for
        the full schema specification.

    Raises
    ------
    FileNotFoundError
        If *root* does not exist.
    NotADirectoryError
        If *root* exists but is not a directory.

    Notes
    -----
    Filesystem roots — POSIX ``/`` and Windows drive roots such as
    ``C:\\`` — are valid inputs and enumerate files beneath the root as
    expected.  Their resolved string already terminates with the path
    separator, so the within-root containment check is constructed
    accordingly rather than blindly appending another separator.

    Each visited directory is recorded by its resolved path, so a reparse
    cycle (such as an NTFS junction pointing back into the tree) is entered
    once rather than followed endlessly.  An ``OSError`` from an unreadable
    or malformed directory is skipped rather than propagated.
    """
    root_resolved = Path(root).resolve(strict=True)
    if not root_resolved.is_dir():
        raise NotADirectoryError(root_resolved)

    root_str = str(root_resolved)
    root_prefix = root_str if root_str.endswith(os.sep) else root_str + os.sep
    names: list[str] = []
    paths: list[str] = []
    stack: list[Path] = [root_resolved]
    visited: set[str] = {root_str}

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue

                    if entry.is_dir(follow_symlinks=False):
                        resolved = str(Path(entry.path).resolve())
                        within = resolved == root_str or resolved.startswith(root_prefix)
                        if within and resolved not in visited:
                            visited.add(resolved)
                            stack.append(Path(entry.path))
                        continue

                    if not entry.is_file(follow_symlinks=False):
                        continue

                    name = entry.name
                    if include is not None:
                        dot = name.rfind(".")
                        ext = name[dot + 1:].lower() if dot > 0 else ""
                        if ext not in include:
                            continue

                    try:
                        if not stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
                            continue
                    except OSError:
                        continue

                    resolved = str(Path(entry.path).resolve())
                    if resolved == root_str or resolved.startswith(root_prefix):
                        names.append(name)
                        paths.append(resolved)
        except OSError:
            continue

    return pl.DataFrame(
        {"file_name": names, "file_path": paths},
        schema={"file_name": pl.Utf8, "file_path": pl.Utf8},
    )
