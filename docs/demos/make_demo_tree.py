# Copyright (c) 2026 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Generate the synthetic directory tree the VHS demo tapes run against.

Creates ``demo/`` in the current working directory with a few hundred
files across photo, document, and music subdirectories, plus scratch
files that the exclude-filter demo drops. File contents are random
bytes; only names, extensions, and sizes matter to the demos.
"""

from __future__ import annotations

import os
from pathlib import Path

LAYOUT: tuple[tuple[str, str, int, int], ...] = (
    ("photos", "jpg", 90, 1_400_000),
    ("photos", "png", 40, 2_200_000),
    ("photos/raw", "dng", 12, 3_800_000),
    ("documents", "pdf", 25, 600_000),
    ("documents", "txt", 30, 4_000),
    ("music", "mp3", 18, 3_200_000),
    ("", "tmp", 8, 90_000),
    ("", "log", 6, 30_000),
)


def main() -> None:
    """Write the demo tree and print a one-line summary.

    Returns
    -------
    None
        Writes files under ``demo/`` as a side effect.
    """
    root = Path("demo")
    total_files = 0
    total_bytes = 0
    for subdir, ext, count, size in LAYOUT:
        target = root / subdir if subdir else root
        target.mkdir(parents=True, exist_ok=True)
        stem = subdir.split("/")[-1] if subdir else "scratch"
        for i in range(1, count + 1):
            (target / f"{stem}_{i:04d}.{ext}").write_bytes(os.urandom(size))
        total_files += count
        total_bytes += count * size
    print(f"demo tree ready: {total_files} files, {total_bytes / 1_000_000:.0f} MB")


if __name__ == "__main__":
    main()
