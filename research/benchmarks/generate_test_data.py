# Copyright (c) 2025 Mercury. All rights reserved.
# SPDX-License-Identifier: MIT

"""Synthetic test data generation for scanning and hashing benchmarks.

Produces two directory layouts:

- **flat**: ~370 files across 4 subdirectories with varying file sizes
  (4 KB to 4 MB). Exercises hash throughput on mixed workloads.
- **deep**: ~5 800 files across ~730 directories at 4 levels of nesting.
  Exercises directory-traversal overhead and concurrency dispatch costs.

Files are filled with ``os.urandom`` bytes -- cryptographically random
noise with no executable content.
"""

import os
import shutil
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path(__file__).parent / "_test_data"
DEEP_OUTPUT_DIR = Path(__file__).parent / "_test_data_deep"

FLAT_SPECS: list[tuple[str, str, int, int]] = [
    # (subdirectory, prefix, count, size_bytes)
    ("small", "sm", 200, 4_096),
    ("medium", "md", 100, 256_000),
    ("large", "lg", 20, 4_000_000),
    ("mixed", "mx", 50, 64_000),
]


def generate_flat(output_dir: Path = DEFAULT_OUTPUT_DIR, *, clean: bool = True) -> int:
    """Create a flat directory layout with files of varying sizes.

    Parameters
    ----------
    output_dir : Path
        Root directory for generated files.
    clean : bool
        Remove ``output_dir`` before generating if it exists.

    Returns
    -------
    int
        Total number of files created.
    """
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)

    total = 0
    for subdir, prefix, count, size in FLAT_SPECS:
        folder = output_dir / subdir
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            (folder / f"{prefix}_{i:04d}.bin").write_bytes(os.urandom(size))
            total += 1
    return total


def generate_deep(
    output_dir: Path = DEEP_OUTPUT_DIR,
    *,
    clean: bool = True,
    breadth: int = 12,
    depth: int = 4,
    files_per_dir: int = 8,
    file_size: int = 512,
) -> int:
    """Create a wide-and-deep directory tree.

    Breadth halves at each level (``max(2, breadth // 2**level)``),
    producing roughly 5 800 files across ~730 directories with the
    default parameters.

    Parameters
    ----------
    output_dir : Path
        Root directory for the generated tree.
    clean : bool
        Remove ``output_dir`` before generating if it exists.
    breadth : int
        Number of subdirectories at the root level.
    depth : int
        Maximum nesting depth.
    files_per_dir : int
        Number of files created in each directory.
    file_size : int
        Size in bytes of each generated file.

    Returns
    -------
    int
        Total number of files created.
    """
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)

    total = 0

    def _build(parent: Path, level: int) -> None:
        nonlocal total
        parent.mkdir(parents=True, exist_ok=True)
        for i in range(files_per_dir):
            (parent / f"f_{i:03d}.bin").write_bytes(os.urandom(file_size))
            total += 1
        if level < depth:
            n_subdirs = max(2, breadth // (2**level))
            for j in range(n_subdirs):
                _build(parent / f"d{level}_{j:03d}", level + 1)

    _build(output_dir, 0)
    return total


if __name__ == "__main__":
    n_flat = generate_flat()
    print(f"Generated {n_flat} files (flat) in {DEFAULT_OUTPUT_DIR}")
    n_deep = generate_deep()
    print(f"Generated {n_deep} files (deep) in {DEEP_OUTPUT_DIR}")
