# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Directory scanning benchmark.

Compares eleven file-enumeration strategies sourced from two prior
projects, ranging from ``os.walk`` and ``os.scandir`` variants to
``pathlib`` methods and concurrent approaches using
``ThreadPoolExecutor`` and ``asyncio``.

Every strategy enumerates the same directory tree and returns a list
of file paths.  After each run the file count is verified against a
ground-truth scan to detect correctness regressions.

Two synthetic datasets exercise different performance characteristics:

- **flat** — ~370 files across 4 directories.  Measures per-file
  overhead and raw enumeration speed.
- **deep** — ~5 800 files across ~730 directories at 4 levels.
  Exercises traversal dispatch cost and concurrency overhead.

Each strategy runs multiple iterations; best, median, and mean times
are reported for statistical confidence.

Security
--------
Symlinks are skipped.  ``PermissionError`` is caught and the
offending directory is silently skipped.

Examples
--------
.. code-block:: bash

    uv run --group research research/benchmarks/scanning_benchmark.py
    uv run --group research research/benchmarks/scanning_benchmark.py /path/to/scan
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count, freeze_support
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

try:
    from tqdm import tqdm

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

RUNS_PER_STRATEGY = 3


def _os_walk(root: str, *, progress: bool) -> list[str]:
    """Classic ``os.walk`` — the most common Python traversal pattern."""
    paths: list[str] = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            paths.append(os.path.join(dirpath, f))
    return paths


def _os_walk_comprehension(root: str, *, progress: bool) -> list[str]:
    """One-liner ``os.walk`` via set comprehension."""
    return list(
        {
            os.path.join(dirpath, f)
            for dirpath, _, filenames in os.walk(root)
            for f in filenames
        }
    )


def _scandir_stack(root: str, *, progress: bool) -> list[str]:
    """Iterative stack-based traversal with ``os.scandir``."""
    paths: list[str] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        paths.append(entry.path)
        except PermissionError:
            continue
    return paths


def _scandir_stack_with_metadata(root: str, *, progress: bool) -> list[str]:
    """Stack-based ``os.scandir`` collecting size and mtime via ``entry.stat()``.

    Returns paths only for fair comparison, but performs the ``stat()``
    work to measure the overhead of metadata collection.
    """
    paths: list[str] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        _ = st.st_size
                        _ = st.st_mtime
                        paths.append(entry.path)
        except PermissionError:
            continue
    return paths


def _scandir_gen_yieldfrom_inner(directory: str) -> Generator[str]:
    """Recursive generator using ``yield from`` for subdirectories."""
    try:
        with os.scandir(directory) as scan:
            for item in scan:
                if item.is_symlink():
                    continue
                if item.is_file(follow_symlinks=False):
                    yield item.path
                elif item.is_dir(follow_symlinks=False):
                    yield from _scandir_gen_yieldfrom_inner(item.path)
    except PermissionError:
        return


def _scandir_gen_yieldfrom(root: str, *, progress: bool) -> list[str]:
    """Recursive ``os.scandir`` generator with ``yield from``."""
    return list(_scandir_gen_yieldfrom_inner(root))


def _scandir_gen_explicit_inner(directory: str) -> Generator[str]:
    """Recursive generator using explicit for-loop for subdirectories."""
    try:
        with os.scandir(directory) as scan:
            for item in scan:
                if item.is_symlink():
                    continue
                if item.is_file(follow_symlinks=False):
                    yield item.path
                elif item.is_dir(follow_symlinks=False):
                    for subitem in _scandir_gen_explicit_inner(item.path):
                        yield subitem
    except PermissionError:
        return


def _scandir_gen_explicit(root: str, *, progress: bool) -> list[str]:
    """Recursive ``os.scandir`` generator with explicit loop delegation."""
    return list(_scandir_gen_explicit_inner(root))


def _path_rglob(root: str, *, progress: bool) -> list[str]:
    """``Path.rglob('*')`` filtered to files."""
    return [str(p) for p in Path(root).rglob("*") if p.is_file()]


def _path_glob_hybrid(root: str, *, progress: bool) -> list[str]:
    """Top-level ``Path.glob`` for files, ``rglob`` for each subdirectory."""
    d = Path(root)
    files = [str(f) for f in d.glob("*") if f.is_file()]
    for sub in d.glob("*"):
        if sub.is_dir():
            files.extend(str(f) for f in sub.rglob("*") if f.is_file())
    return files


def _iterdir_recursive_inner(d: Path, out: list[str]) -> None:
    """Recursive ``Path.iterdir`` collecting files into *out*."""
    try:
        for item in d.iterdir():
            if item.is_symlink():
                continue
            if item.is_file():
                out.append(str(item))
            elif item.is_dir():
                _iterdir_recursive_inner(item, out)
    except PermissionError:
        pass


def _path_iterdir_recursive(root: str, *, progress: bool) -> list[str]:
    """Recursive ``Path.iterdir`` traversal."""
    out: list[str] = []
    _iterdir_recursive_inner(Path(root), out)
    return out


def _scandir_one_level(directory: str) -> tuple[list[str], list[str]]:
    """Scan a single directory level, returning (files, subdirs).

    Parameters
    ----------
    directory : str
        Directory to scan.

    Returns
    -------
    tuple of (list of str, list of str)
        File paths and subdirectory paths found at this level.
    """
    files: list[str] = []
    subdirs: list[str] = []
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_symlink():
                    continue
                if entry.is_file(follow_symlinks=False):
                    files.append(entry.path)
                elif entry.is_dir(follow_symlinks=False):
                    subdirs.append(entry.path)
    except PermissionError:
        pass
    return files, subdirs


def _threadpool_scandir(root: str, *, progress: bool) -> list[str]:
    """``ThreadPoolExecutor`` dispatching ``os.scandir`` per subdirectory."""
    all_files: list[str] = []
    n_workers = min(cpu_count() * 2, 32)

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        pending = {executor.submit(_scandir_one_level, root)}
        while pending:
            done = {f for f in pending if f.done()}
            if not done:
                done = {next(iter(as_completed(pending)))}
            pending -= done
            for fut in done:
                files, subdirs = fut.result()
                all_files.extend(files)
                for sd in subdirs:
                    pending.add(executor.submit(_scandir_one_level, sd))
    return all_files


async def _async_scandir_one(
    directory: str, loop: asyncio.AbstractEventLoop
) -> tuple[list[str], list[str]]:
    """Run ``_scandir_one_level`` in the default executor."""
    return await loop.run_in_executor(None, _scandir_one_level, directory)


async def _async_scandir_core(root: str) -> list[str]:
    """Async dispatcher that fans out ``os.scandir`` per directory."""
    loop = asyncio.get_event_loop()
    all_files: list[str] = []
    tasks = [asyncio.ensure_future(_async_scandir_one(root, loop))]

    while tasks:
        done, tasks_set = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        tasks = list(tasks_set)
        for t in done:
            files, subdirs = t.result()
            all_files.extend(files)
            for sd in subdirs:
                tasks.append(asyncio.ensure_future(_async_scandir_one(sd, loop)))
    return all_files


def _asyncio_scandir(root: str, *, progress: bool) -> list[str]:
    """``asyncio`` dispatching ``os.scandir`` to the default executor."""
    return asyncio.run(_async_scandir_core(root))


STRATEGIES: list[tuple[str, Callable, str, str]] = [
    ("os.walk", _os_walk, "T0", "stdlib"),
    ("os.walk (set-comp)", _os_walk_comprehension, "T0", "MediaRegistryTool"),
    ("scandir stack", _scandir_stack, "T0", "custom"),
    ("scandir stack +stat", _scandir_stack_with_metadata, "T0", "custom"),
    ("scandir gen yield-from", _scandir_gen_yieldfrom, "T0", "custom"),
    ("scandir gen explicit-loop", _scandir_gen_explicit, "T0", "custom"),
    ("Path.rglob", _path_rglob, "T0", "stdlib"),
    ("Path.glob+rglob hybrid", _path_glob_hybrid, "T0", "prior project"),
    ("Path.iterdir recursive", _path_iterdir_recursive, "T0", "MediaRegistryTool"),
    ("ThreadPool+scandir", _threadpool_scandir, "T0", "custom"),
    ("asyncio+scandir", _asyncio_scandir, "T0", "stdlib"),
]


def run_single(fn: Callable, root: str, *, progress: bool) -> tuple[float, int]:
    """Execute a single scan strategy and return elapsed time and file count.

    Parameters
    ----------
    fn : Callable
        Strategy function accepting ``(root, *, progress)``.
    root : str
        Directory to scan.
    progress : bool
        Whether to enable progress display.

    Returns
    -------
    tuple of (float, int)
        Wall-clock seconds and number of files found.
    """
    start = time.perf_counter()
    paths = fn(root, progress=progress)
    elapsed = time.perf_counter() - start
    return elapsed, len(paths)


def warmup(strategies: list[tuple[str, Callable, str, str]], root: str) -> None:
    """Run each strategy once to prime filesystem caches.

    Parameters
    ----------
    strategies : list of (name, fn, tier, source)
        Strategy registry.
    root : str
        Directory to scan.
    """
    for _, fn, _, _ in strategies:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                fn(root, progress=False)
            except Exception:
                pass


def run_all(target_dir: Path) -> pl.DataFrame:
    """Run every registered strategy against *target_dir*.

    Parameters
    ----------
    target_dir : Path
        Root directory to scan.

    Returns
    -------
    pl.DataFrame
        One row per strategy with columns: ``strategy``, ``dep_tier``,
        ``source``, ``best_s``, ``median_s``, ``mean_s``,
        ``files_found``, ``expected``, ``correct``, ``runs``.
    """
    root = str(target_dir.resolve())
    truth_count = len(_scandir_stack(root, progress=False))

    print("=" * 85)
    print("  DIRECTORY SCANNING BENCHMARK")
    print("=" * 85)
    print(f"  Target:  {target_dir}")
    print(f"  Files:   {truth_count}")
    print(f"  CPUs:    {cpu_count()}")
    print()

    print("  Warming up...", end=" ", flush=True)
    warmup(STRATEGIES, root)
    print("done.\n")

    rows: list[dict] = []

    for name, fn, tier, source in STRATEGIES:
        label = f"  {name:<27} [{tier}]"
        print(label, end="  ", flush=True)

        times = []
        count = 0
        for _ in range(RUNS_PER_STRATEGY):
            elapsed, count = run_single(fn, root, progress=False)
            times.append(elapsed)

        best = min(times)
        median = sorted(times)[len(times) // 2]
        mean = sum(times) / len(times)
        match = "OK" if count == truth_count else f"MISMATCH({count})"

        print(
            f"best={best:.5f}s  median={median:.5f}s  mean={mean:.5f}s  "
            f"[{count} files] {match}"
        )

        rows.append({
            "strategy": name,
            "dep_tier": tier,
            "source": source,
            "best_s": round(best, 5),
            "median_s": round(median, 5),
            "mean_s": round(mean, 5),
            "files_found": count,
            "expected": truth_count,
            "correct": count == truth_count,
            "runs": RUNS_PER_STRATEGY,
        })

    return pl.DataFrame(rows)


def print_results(df: pl.DataFrame) -> None:
    """Print formatted rankings and category analysis.

    Parameters
    ----------
    df : pl.DataFrame
        Results from :func:`run_all`.
    """
    pl.Config.set_ascii_tables(True)

    print()
    print("=" * 85)
    print("  ALL RESULTS (sorted by best time)")
    print("=" * 85)
    with pl.Config(tbl_cols=-1, tbl_rows=-1, tbl_width_chars=140):
        print(df.sort("best_s"))

    ranked = df.sort("best_s")
    baseline = ranked["best_s"][0]

    print()
    print("=" * 85)
    print("  RANKING")
    print("=" * 85)
    print(f"  {'#':<3} {'Strategy':<27} {'Best':>10} {'Median':>10} {'vs #1':>8} {'Source'}")
    print(f"  {'-' * 3} {'-' * 27} {'-' * 10} {'-' * 10} {'-' * 8} {'-' * 35}")
    for i, row in enumerate(ranked.iter_rows(named=True), 1):
        ratio = row["best_s"] / baseline if baseline > 0 else 0
        print(
            f"  {i:<3} {row['strategy']:<27} {row['best_s']:>9.5f}s {row['median_s']:>9.5f}s "
            f"{ratio:>7.2f}x  {row['source']}"
        )

    bad = df.filter(~pl.col("correct"))
    if bad.height:
        print()
        print("  WARNING: these strategies returned wrong file count:")
        for row in bad.iter_rows(named=True):
            print(f"    {row['strategy']}: got {row['files_found']}, expected {row['expected']}")

    print()
    print("=" * 85)
    print("  BY CATEGORY (best time)")
    print("=" * 85)
    categories = {
        "os.walk variants": ["os.walk", "os.walk (set-comp)"],
        "os.scandir (manual)": [
            "scandir stack",
            "scandir stack +stat",
            "scandir gen yield-from",
            "scandir gen explicit-loop",
        ],
        "pathlib (Path.*)": ["Path.rglob", "Path.glob+rglob hybrid", "Path.iterdir recursive"],
        "concurrent": ["ThreadPool+scandir", "asyncio+scandir"],
    }
    for cat, names in categories.items():
        subset = df.filter(pl.col("strategy").is_in(names)).sort("best_s")
        if subset.height:
            best_row = subset.row(0, named=True)
            print(
                f"  {cat:<30}  winner: {best_row['strategy']:<27} {best_row['best_s']:.5f}s"
            )


def main():
    """Entry point — parse arguments, run benchmarks, save results."""
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        if not target.is_dir():
            print(f"ERROR: Not a directory: {target}")
            sys.exit(1)
        targets = [("user-provided", target)]
    else:
        from generate_test_data import DEFAULT_OUTPUT_DIR, DEEP_OUTPUT_DIR, generate_deep, generate_flat

        print("No directory given — generating synthetic test data...")
        n1 = generate_flat()
        print(f"Generated {n1} files (flat) in {DEFAULT_OUTPUT_DIR}")
        n2 = generate_deep()
        print(f"Generated {n2} files (deep tree) in {DEEP_OUTPUT_DIR}\n")
        targets = [
            ("FLAT (370 files, 4 dirs)", DEFAULT_OUTPUT_DIR),
            (f"DEEP ({n2} files, many dirs)", DEEP_OUTPUT_DIR),
        ]

    all_dfs = []
    for label, target in targets:
        print()
        print("#" * 85)
        print(f"  DATASET: {label}")
        print("#" * 85)
        df = run_all(target)
        df = df.with_columns(pl.lit(label).alias("dataset"))
        print_results(df)
        all_dfs.append(df)

    combined = pl.concat(all_dfs)
    out_path = Path(__file__).parent / "scanning_results.parquet"
    combined.write_parquet(out_path)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    freeze_support()
    main()
