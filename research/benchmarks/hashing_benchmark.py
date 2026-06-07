# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Hashing parallelism benchmark.

Compares concurrency strategies for file hashing using a single hash
function (``hashlib.file_digest`` with SHA-256) to isolate the
parallelism variable. Every strategy calls the same ``hash_file``
implementation; the only difference is the dispatch mechanism.

Strategies are tagged by dependency tier to evaluate the trade-off
between performance and install footprint:

- **T0**: stdlib only (``hashlib``, ``concurrent.futures``, ``os``).
  Fully ``mypyc``-compilable.
- **T2**: adds ``tqdm`` for progress tracking.
- **T3**: adds ``joblib`` for convenience parallelism.

Security
--------
Files are opened ``rb``-only. Symlinks are rejected.  Resolved paths
are checked against the root boundary to prevent traversal escapes.
``stat.S_ISREG`` confirms regular-file status before hashing.

Notes
-----
The ``joblib(loky)`` strategy intentionally avoids ``tqdm_joblib`` for
progress indication. ``tqdm_joblib`` monkeypatches joblib's
``BatchCompletionCallBack`` and silently overrides the backend to
``threading`` even when ``backend="loky"`` is explicitly passed.
This benchmark uses ``verbose=10`` for loky progress instead.

A warmup phase runs each strategy on a small file subset before
timing. This ensures ``loky``'s cached worker pool is initialized,
preventing one-time process-spawn cost (~0.45 s) from biasing
the first timed run.

Examples
--------
.. code-block:: bash

    uv run --extra research research/benchmarks/hashing_benchmark.py
    uv run --extra research research/benchmarks/hashing_benchmark.py /path/to/files
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import os
import stat
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from functools import partial
from multiprocessing import Pool, cpu_count, freeze_support
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Callable

try:
    from tqdm import tqdm
    from tqdm.contrib.concurrent import process_map, thread_map

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

try:
    from joblib import Parallel, delayed

    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False

try:
    from tqdm_joblib import tqdm_joblib

    HAS_TQDM_JOBLIB = True
except ImportError:
    HAS_TQDM_JOBLIB = False


def hash_file(file_path: str) -> str | None:
    """Hash a single file with SHA-256 via ``hashlib.file_digest``.

    Parameters
    ----------
    file_path : str
        Absolute path to the file.

    Returns
    -------
    str or None
        Hex digest, or ``None`` if the file cannot be read.
    """
    try:
        with open(file_path, "rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    except (PermissionError, OSError):
        return None


def enumerate_files(root: Path) -> list[str]:
    """Securely enumerate regular files under *root*.

    Parameters
    ----------
    root : Path
        Directory to scan.

    Returns
    -------
    list of str
        Resolved absolute paths for every regular, non-symlink file
        whose resolved path stays within *root*.
    """
    root_resolved = root.resolve(strict=True)
    root_prefix = str(root_resolved) + os.sep
    paths: list[str] = []
    stack = [root_resolved]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        resolved = str(Path(entry.path).resolve())
                        if resolved == str(root_resolved) or resolved.startswith(root_prefix):
                            stack.append(Path(entry.path).resolve())
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        if not stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
                            continue
                    except OSError:
                        continue
                    resolved = str(Path(entry.path).resolve())
                    if resolved == str(root_resolved) or resolved.startswith(root_prefix):
                        paths.append(resolved)
        except PermissionError:
            continue
    return paths


def _mp_worker(file_path: str) -> tuple[str, str | None]:
    """Module-level wrapper for ``multiprocessing.Pool`` pickling."""
    return file_path, hash_file(file_path)


def _sequential(files: list[str], *, progress: bool) -> pl.DataFrame:
    """Single-threaded baseline."""
    it = tqdm(files, desc="sequential", leave=False) if (progress and HAS_TQDM) else files
    hashes = [hash_file(fp) for fp in it]
    return pl.DataFrame({"path": files, "hash": hashes})


def _threadpool_map(files: list[str], *, progress: bool) -> pl.DataFrame:
    """``ThreadPoolExecutor.map``, preserves input order, minimal overhead."""
    n = min(cpu_count() * 2, 32)
    with ThreadPoolExecutor(max_workers=n) as ex:
        if progress and HAS_TQDM:
            hashes = list(
                tqdm(ex.map(hash_file, files), total=len(files), desc="ThreadPool.map", leave=False)
            )
        else:
            hashes = list(ex.map(hash_file, files))
    return pl.DataFrame({"path": files, "hash": hashes})


def _threadpool_as_completed(files: list[str], *, progress: bool) -> pl.DataFrame:
    """``ThreadPoolExecutor`` with ``as_completed`` for first-finished ordering."""
    n = min(cpu_count() * 2, 32)
    results: list[tuple[str, str | None]] = []
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(hash_file, fp): fp for fp in files}
        it = as_completed(futs)
        if progress and HAS_TQDM:
            it = tqdm(it, total=len(files), desc="ThreadPool+as_completed", leave=False)
        for fut in it:
            results.append((futs[fut], fut.result()))
    return pl.DataFrame({"path": [r[0] for r in results], "hash": [r[1] for r in results]})


def _processpoolexecutor(files: list[str], *, progress: bool) -> pl.DataFrame:
    """``ProcessPoolExecutor`` with ``as_completed``."""
    results: list[tuple[str, str | None]] = []
    with ProcessPoolExecutor(max_workers=cpu_count()) as ex:
        futs = {ex.submit(hash_file, fp): fp for fp in files}
        it = as_completed(futs)
        if progress and HAS_TQDM:
            it = tqdm(it, total=len(files), desc="ProcessPoolExecutor", leave=False)
        for fut in it:
            results.append((futs[fut], fut.result()))
    return pl.DataFrame({"path": [r[0] for r in results], "hash": [r[1] for r in results]})


def _mp_pool_imap(files: list[str], *, progress: bool) -> pl.DataFrame:
    """``multiprocessing.Pool`` with ``imap_unordered``."""
    results: list[tuple[str, str | None]] = []
    with Pool(processes=cpu_count()) as pool:
        it = pool.imap_unordered(_mp_worker, files)
        if progress and HAS_TQDM:
            it = tqdm(it, total=len(files), desc="mp.Pool(imap)", leave=False)
        for r in it:
            results.append(r)
    return pl.DataFrame({"path": [r[0] for r in results], "hash": [r[1] for r in results]})


def _tqdm_thread_map(files: list[str], *, progress: bool) -> pl.DataFrame:
    """``tqdm.contrib.concurrent.thread_map``, one-liner threaded parallel."""
    hashes = list(
        thread_map(
            hash_file,
            files,
            desc="tqdm.thread_map" if progress else None,
            disable=not progress,
            leave=False,
        )
    )
    return pl.DataFrame({"path": files, "hash": hashes})


def _tqdm_process_map(files: list[str], *, progress: bool) -> pl.DataFrame:
    """``tqdm.contrib.concurrent.process_map``, one-liner process parallel."""
    hashes = list(
        process_map(
            hash_file,
            files,
            desc="tqdm.process_map" if progress else None,
            disable=not progress,
            leave=False,
            chunksize=1,
        )
    )
    return pl.DataFrame({"path": files, "hash": hashes})


def _joblib_threading(files: list[str], *, progress: bool) -> pl.DataFrame:
    """``joblib.Parallel`` with ``backend='threading'`` (pinned)."""
    if progress and HAS_TQDM_JOBLIB:
        with tqdm_joblib("joblib(threading)", total=len(files)):
            hashes = Parallel(n_jobs=-1, backend="threading")(
                delayed(hash_file)(fp) for fp in files
            )
    else:
        hashes = Parallel(n_jobs=-1, backend="threading")(delayed(hash_file)(fp) for fp in files)
    return pl.DataFrame({"path": files, "hash": hashes})


def _joblib_loky(files: list[str], *, progress: bool) -> pl.DataFrame:
    """``joblib.Parallel`` with ``backend='loky'`` (multiprocessing, pinned).

    Uses ``verbose=10`` instead of ``tqdm_joblib`` for progress indication.
    See module docstring for rationale.
    """
    verbosity = 10 if progress else 0
    hashes = Parallel(n_jobs=-1, backend="loky", verbose=verbosity)(
        delayed(hash_file)(fp) for fp in files
    )
    return pl.DataFrame({"path": files, "hash": hashes})


STRATEGIES: list[tuple[str, Callable, str]] = [
    ("sequential", _sequential, "T0"),
    ("ThreadPool.map", _threadpool_map, "T0"),
    ("ThreadPool+as_completed", _threadpool_as_completed, "T0"),
    ("ProcessPoolExecutor", _processpoolexecutor, "T0"),
    ("mp.Pool(imap_unordered)", _mp_pool_imap, "T0"),
]

if HAS_TQDM:
    STRATEGIES += [
        ("tqdm.thread_map", _tqdm_thread_map, "T2"),
        ("tqdm.process_map", _tqdm_process_map, "T2"),
    ]

if HAS_JOBLIB:
    STRATEGIES += [
        ("joblib(threading)", _joblib_threading, "T3"),
        ("joblib(loky/mp)", _joblib_loky, "T3"),
    ]


def run_single(fn: Callable, files: list[str], *, progress: bool) -> tuple[float, int]:
    """Execute a single strategy and return elapsed time and valid hash count.

    Parameters
    ----------
    fn : Callable
        Strategy function accepting ``(files, *, progress)`` and
        returning a ``pl.DataFrame`` with ``path`` and ``hash`` columns.
    files : list of str
        File paths to hash.
    progress : bool
        Whether to enable progress display.

    Returns
    -------
    tuple of (float, int)
        Wall-clock seconds and number of non-null hashes produced.
    """
    start = time.perf_counter()
    df = fn(files, progress=progress)
    elapsed = time.perf_counter() - start
    valid = df.filter(pl.col("hash").is_not_null()).height
    return elapsed, valid


def warmup(strategies: list[tuple[str, Callable, str]], files: list[str]) -> None:
    """Run each strategy once on a small subset to initialize worker pools.

    Parameters
    ----------
    strategies : list of (name, fn, tier)
        Strategy registry.
    files : list of str
        Full file list; only the first 5 are used.
    """
    subset = files[:5]
    for _, fn, _ in strategies:
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
            contextlib.suppress(Exception),
        ):
            fn(subset, progress=False)


def run_all(target_dir: Path) -> pl.DataFrame:
    """Run every registered strategy against *target_dir*.

    Parameters
    ----------
    target_dir : Path
        Root directory containing files to hash.

    Returns
    -------
    pl.DataFrame
        One row per (strategy, progress_mode) combination with columns:
        ``strategy``, ``dep_tier``, ``progress``, ``elapsed_s``,
        ``throughput_mb_s``, ``files_hashed``, ``total_files``.
    """
    files = enumerate_files(target_dir)
    total_bytes = sum(os.path.getsize(f) for f in files)
    total_mb = total_bytes / 1_000_000

    print("=" * 80)
    print("  HASHING BENCHMARK: hashlib.file_digest SHA-256")
    print("=" * 80)
    print(f"  Target:  {target_dir}")
    print(f"  Files:   {len(files)}")
    print(f"  Size:    {total_mb:.1f} MB")
    print(f"  CPUs:    {cpu_count()}")
    print(
        f"  Deps:    tqdm={'yes' if HAS_TQDM else 'no'}  "
        f"joblib={'yes' if HAS_JOBLIB else 'no'}  "
        f"tqdm_joblib={'yes' if HAS_TQDM_JOBLIB else 'no'}"
    )
    print()

    print("  Warming up worker pools...", end=" ", flush=True)
    warmup(STRATEGIES, files)
    print("done.\n")

    rows: list[dict] = []
    for name, fn, tier in STRATEGIES:
        for with_progress in (False, True):
            tag = "+progress" if with_progress else "no-progress"
            label = f"  {name:<28} {tag:<12} [{tier}]"
            print(label, end="  ", flush=True)
            elapsed, valid = run_single(fn, files, progress=with_progress)
            tp = total_mb / elapsed if elapsed > 0 else 0
            print(f"{elapsed:.4f}s   {tp:>7.0f} MB/s   [{valid}/{len(files)}]")
            rows.append(
                {
                    "strategy": name,
                    "dep_tier": tier,
                    "progress": with_progress,
                    "elapsed_s": round(elapsed, 4),
                    "throughput_mb_s": round(tp, 1),
                    "files_hashed": valid,
                    "total_files": len(files),
                }
            )

    return pl.DataFrame(rows)


def print_results(df: pl.DataFrame) -> None:
    """Print formatted leaderboards and overhead analysis.

    Parameters
    ----------
    df : pl.DataFrame
        Results from :func:`run_all`.
    """
    pl.Config.set_ascii_tables(True)

    print()
    print("=" * 80)
    print("  ALL RESULTS")
    print("=" * 80)
    with pl.Config(tbl_cols=-1, tbl_rows=-1, tbl_width_chars=120):
        print(df.sort("elapsed_s"))

    for label, filt in [
        ("NO PROGRESS", ~pl.col("progress")),
        ("WITH PROGRESS", pl.col("progress")),
    ]:
        ranked = df.filter(filt).sort("elapsed_s")
        print()
        print("=" * 80)
        print(f"  RANKING: {label}")
        print("=" * 80)
        print(f"  {'#':<3} {'Strategy':<28} {'Tier':<5} {'Time':>9} {'MB/s':>10}")
        print(f"  {'-' * 3} {'-' * 28} {'-' * 5} {'-' * 9} {'-' * 10}")
        for i, row in enumerate(ranked.iter_rows(named=True), 1):
            print(
                f"  {i:<3} {row['strategy']:<28} {row['dep_tier']:<5} "
                f"{row['elapsed_s']:>8.4f}s {row['throughput_mb_s']:>9.1f}"
            )

    t0 = df.filter(pl.col("dep_tier") == "T0")
    print()
    print("=" * 80)
    print("  BEST STDLIB-ONLY (T0): zero ext deps, mypyc-compilable")
    print("=" * 80)
    for label, filt in [
        ("no progress", ~pl.col("progress")),
        ("with progress", pl.col("progress")),
    ]:
        best = t0.filter(filt).sort("elapsed_s").head(3)
        print(f"  [{label}]")
        for i, r in enumerate(best.iter_rows(named=True), 1):
            print(
                f"    {i}. {r['strategy']:<28} {r['elapsed_s']:.4f}s  "
                f"({r['throughput_mb_s']:.1f} MB/s)"
            )

    no_p = df.filter(~pl.col("progress")).select("strategy", pl.col("elapsed_s").alias("base_s"))
    wi_p = df.filter(pl.col("progress")).select("strategy", pl.col("elapsed_s").alias("prog_s"))
    overhead = (
        no_p.join(wi_p, on="strategy")
        .with_columns(
            ((pl.col("prog_s") - pl.col("base_s")) / pl.col("base_s") * 100)
            .round(1)
            .alias("overhead_%")
        )
        .sort("overhead_%")
    )
    print()
    print("=" * 80)
    print("  PROGRESS OVERHEAD")
    print("=" * 80)
    print(f"  {'Strategy':<28} {'Base':>9} {'w/Prog':>9} {'Delta':>10}")
    print(f"  {'-' * 28} {'-' * 9} {'-' * 9} {'-' * 10}")
    for row in overhead.iter_rows(named=True):
        sign = "+" if row["overhead_%"] >= 0 else ""
        print(
            f"  {row['strategy']:<28} {row['base_s']:>8.4f}s {row['prog_s']:>8.4f}s "
            f"{sign}{row['overhead_%']:>8.1f}%"
        )


def _hash_file_with(file_path: str, digest: str | Callable[[], object]) -> str | None:
    """Hash a single file with an arbitrary ``hashlib.file_digest`` digest.

    Parameters
    ----------
    file_path : str
        Absolute path to the file.
    digest : str or collections.abc.Callable
        Algorithm name or constructor passed to ``hashlib.file_digest``.

    Returns
    -------
    str or None
        Hex digest, or ``None`` if the file cannot be read.
    """
    try:
        with open(file_path, "rb") as f:
            return hashlib.file_digest(f, digest).hexdigest()
    except (PermissionError, OSError):
        return None


def _digest_arg(algorithm: str) -> str | Callable[[], object]:
    """Return the ``hashlib.file_digest`` argument for *algorithm*.

    Parameters
    ----------
    algorithm : str
        Algorithm name.  ``"blake3"`` resolves to the blake3 constructor.

    Returns
    -------
    str or collections.abc.Callable
        The stdlib algorithm name, or the blake3 constructor.
    """
    if algorithm == "blake3":
        from blake3 import blake3

        return blake3
    return algorithm


def _time_pool(
    files: list[str], workers: int, digest: str | Callable[[], object] = "sha256"
) -> float:
    """Time one ``ThreadPoolExecutor.map`` hashing pass.

    Parameters
    ----------
    files : list of str
        File paths to hash.
    workers : int
        Thread-pool size.
    digest : str or collections.abc.Callable, default ``"sha256"``
        Digest passed to ``hashlib.file_digest``.

    Returns
    -------
    float
        Wall-clock seconds for the pass.
    """
    fn = partial(_hash_file_with, digest=digest)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(fn, files))
    return time.perf_counter() - start


def run_worker_sweep(target_dir: Path, *, reps: int = 3) -> pl.DataFrame:
    """Sweep ``ThreadPoolExecutor.map`` worker counts for SHA-256.

    Validates the library default of ``min(cpu_count() * 2, 32)`` by timing
    a range of worker counts on the same file set.

    Parameters
    ----------
    target_dir : Path
        Root directory of files to hash.
    reps : int, default 3
        Timed repetitions per worker count; the best time is kept.

    Returns
    -------
    pl.DataFrame
        Columns ``workers``, ``elapsed_s``, ``throughput_mb_s``.
    """
    files = enumerate_files(target_dir)
    total_mb = sum(os.path.getsize(f) for f in files) / 1_000_000
    cpu = cpu_count()
    counts = sorted({cpu, int(cpu * 1.5), cpu * 2, cpu * 3, min(cpu * 2, 32)})
    rows: list[dict] = []
    for n in counts:
        best = min(_time_pool(files, n) for _ in range(reps))
        tp = total_mb / best if best > 0 else 0
        rows.append({"workers": n, "elapsed_s": round(best, 4), "throughput_mb_s": round(tp, 1)})
    return pl.DataFrame(rows)


def run_algorithm_sweep(target_dir: Path, *, reps: int = 3) -> pl.DataFrame:
    """Compare hash algorithms at the default worker count.

    Includes ``blake3`` when the optional package is installed.

    Parameters
    ----------
    target_dir : Path
        Root directory of files to hash.
    reps : int, default 3
        Timed repetitions per algorithm; the best time is kept.

    Returns
    -------
    pl.DataFrame
        Columns ``algorithm``, ``elapsed_s``, ``throughput_mb_s``.
    """
    files = enumerate_files(target_dir)
    total_mb = sum(os.path.getsize(f) for f in files) / 1_000_000
    n = min(cpu_count() * 2, 32)
    algorithms = ["sha256", "sha512", "blake2b"]
    if importlib.util.find_spec("blake3") is not None:
        algorithms.append("blake3")
    rows: list[dict] = []
    for algo in algorithms:
        best = min(_time_pool(files, n, _digest_arg(algo)) for _ in range(reps))
        tp = total_mb / best if best > 0 else 0
        rows.append(
            {"algorithm": algo, "elapsed_s": round(best, 4), "throughput_mb_s": round(tp, 1)}
        )
    return pl.DataFrame(rows)


def print_sweep(df: pl.DataFrame, title: str, key: str) -> None:
    """Print a two-column sweep leaderboard sorted fastest first.

    Parameters
    ----------
    df : pl.DataFrame
        Sweep results with *key*, ``elapsed_s``, and ``throughput_mb_s``.
    title : str
        Section heading.
    key : str
        Name of the varied column (``"workers"`` or ``"algorithm"``).
    """
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)
    print(f"  {key:<12} {'Time':>10} {'MB/s':>10}")
    print(f"  {'-' * 12} {'-' * 10} {'-' * 10}")
    for row in df.sort("elapsed_s").iter_rows(named=True):
        print(f"  {str(row[key]):<12} {row['elapsed_s']:>9.4f}s {row['throughput_mb_s']:>9.1f}")


def main():
    """Entry point: parse arguments, run benchmark, save results."""
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        if not target.is_dir():
            print(f"ERROR: Not a directory: {target}")
            sys.exit(1)
    else:
        from generate_test_data import DEFAULT_OUTPUT_DIR, generate_flat

        print("No directory given; generating synthetic test data...")
        n = generate_flat()
        print(f"Generated {n} files in {DEFAULT_OUTPUT_DIR}\n")
        target = DEFAULT_OUTPUT_DIR

    df = run_all(target)
    print_results(df)

    worker_df = run_worker_sweep(target)
    print_sweep(worker_df, "WORKER-COUNT SWEEP: ThreadPool.map SHA-256", "workers")
    algo_df = run_algorithm_sweep(target)
    print_sweep(algo_df, "ALGORITHM SWEEP: ThreadPool.map at the default worker count", "algorithm")

    out_path = Path(__file__).parent / "hashing_results.parquet"
    df.write_parquet(out_path)
    worker_df.write_parquet(Path(__file__).parent / "worker_sweep_results.parquet")
    algo_df.write_parquet(Path(__file__).parent / "algorithm_sweep_results.parquet")
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    freeze_support()
    main()
