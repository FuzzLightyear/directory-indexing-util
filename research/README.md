# Research

This directory contains reproducible benchmarks and analysis that informed every architectural decision in the implementation. Each benchmark isolates a single variable, runs multiple iterations, and reports best/median/mean times for statistical confidence.

## Motivation

File hashing and directory scanning are deceptively complex performance problems. The optimal strategy depends on the interplay between I/O patterns, OS syscall overhead, the GIL, process-spawn cost, and hash algorithm internals. Rather than guessing, we measured.

## Benchmarks

### Hashing Strategies (`benchmarks/hashing_benchmark.py`)

Compares parallelism approaches for file hashing using a single hash function (`hashlib.file_digest` SHA-256) to isolate the concurrency variable:

| Strategy | Tier | Description |
|----------|------|-------------|
| `sequential` | T0 | Single-threaded baseline |
| `ThreadPoolExecutor.map` | T0 | stdlib thread pool, ordered results |
| `ThreadPoolExecutor` + `as_completed` | T0 | stdlib thread pool, first-finished order |
| `ProcessPoolExecutor` | T0 | stdlib process pool |
| `multiprocessing.Pool.imap_unordered` | T0 | Classic multiprocessing |
| `tqdm.thread_map` | T2 | One-liner threaded parallel with progress |
| `tqdm.process_map` | T2 | One-liner process parallel with progress |
| `joblib.Parallel` (threading) | T3 | joblib with pinned threading backend |
| `joblib.Parallel` (loky) | T3 | joblib with pinned loky/multiprocessing backend |

Each tested with and without progress tracking. Worker pools are warmed up before timing.

### Scanning Strategies (`benchmarks/scanning_benchmark.py`)

Compares directory enumeration approaches, all collecting the same file list:

| Strategy | Description | Source |
|----------|-------------|--------|
| `os.walk` | Classic recursive walk | stdlib |
| `os.walk` (set comprehension) | One-liner variant | MediaRegistryTool |
| `os.scandir` (stack) | Iterative with explicit stack | Custom |
| `os.scandir` (stack + stat) | Same, collecting size/mtime metadata | Custom |
| `os.scandir` (generator, yield-from) | Recursive generator | Custom |
| `os.scandir` (generator, explicit loop) | Recursive generator variant | Custom |
| `Path.rglob` | pathlib recursive glob | stdlib |
| `Path.glob` + `rglob` hybrid | Top-level glob + recursive subdirs | Prior project |
| `Path.iterdir` (recursive) | pathlib recursive iteration | Prior project |
| `ThreadPoolExecutor` + `scandir` | Per-subdirectory thread dispatch | Custom |
| `asyncio` + `scandir` | Async per-subdirectory dispatch | Custom |

Tested on both flat (370 files, 4 dirs) and deep (5 864 files, ~730 dirs) layouts.

## Dependency Tiers

Strategies are tagged by dependency cost to evaluate the trade-off between performance and install footprint:

| Tier | Dependencies | mypyc-compilable |
|------|-------------|------------------|
| **T0** | stdlib only (`hashlib`, `concurrent.futures`, `os`, `pathlib`) | Yes |
| **T1** | + `blake3` (C extension) | Usable, not compilable |
| **T2** | + `tqdm` | No |
| **T3** | + `joblib`, `tqdm-joblib` | No |

## Findings

- [`hashing_strategies.md`](hashing_strategies.md) — Full analysis of parallelism for file hashing
- [`scanning_strategies.md`](scanning_strategies.md) — Full analysis of directory enumeration methods

## Running the Benchmarks

```bash
uv run --group research research/benchmarks/generate_test_data.py
uv run --group research research/benchmarks/hashing_benchmark.py [directory]
uv run --group research research/benchmarks/scanning_benchmark.py [directory]
```

If no directory is given, synthetic test data is generated automatically.
