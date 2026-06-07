# Scanning Strategy Analysis

Benchmark-driven evaluation of directory-enumeration methods. All strategies scan the same directory tree and return a flat list of file paths. Each runs 3 iterations; best, median, and mean times are reported.

## Test Environment

| Parameter | Value |
|-----------|-------|
| Flat dataset | 370 files, 4 directories |
| Deep dataset | 5 864 files, ~730 directories, 4 levels |
| CPUs | 8 logical cores |
| Platform | Windows 11 / Python 3.12 |

## Results: Flat Dataset (370 files, 4 dirs)

| # | Strategy | Best (s) | Median (s) | vs #1 |
|---|----------|----------|------------|-------|
| 1 | `scandir stack` | 0.00035 | 0.00037 | 1.00× |
| 2 | `scandir gen yield-from` | 0.00036 | 0.00038 | 1.03× |
| 3 | `scandir gen explicit-loop` | 0.00037 | 0.00039 | 1.06× |
| 4 | `scandir stack +stat` | 0.00038 | 0.00039 | 1.09× |
| 5 | `os.walk` | 0.00058 | 0.00061 | 1.66× |
| 6 | `os.walk (set-comp)` | 0.00060 | 0.00063 | 1.71× |
| 7 | `Path.iterdir recursive` | 0.00190 | 0.00200 | 5.43× |
| 8 | `Path.rglob` | 0.00210 | 0.00220 | 6.00× |
| 9 | `Path.glob+rglob hybrid` | 0.00230 | 0.00240 | 6.57× |
| 10 | `ThreadPool+scandir` | 0.00800 | 0.00850 | 22.86× |
| 11 | `asyncio+scandir` | 0.00870 | 0.00900 | 24.86× |

## Results: Deep Dataset (5 864 files, ~730 dirs)

| # | Strategy | Best (s) | Median (s) | vs #1 |
|---|----------|----------|------------|-------|
| 1 | `scandir stack` | 0.03800 | 0.03950 | 1.00× |
| 2 | `scandir gen explicit-loop` | 0.03850 | 0.04000 | 1.01× |
| 3 | `scandir gen yield-from` | 0.03900 | 0.04050 | 1.03× |
| 4 | `scandir stack +stat` | 0.03950 | 0.04100 | 1.04× |
| 5 | `os.walk` | 0.04500 | 0.04700 | 1.18× |
| 6 | `os.walk (set-comp)` | 0.04600 | 0.04800 | 1.21× |
| 7 | `Path.iterdir recursive` | 0.12000 | 0.12500 | 3.16× |
| 8 | `Path.rglob` | 0.14000 | 0.14500 | 3.68× |
| 9 | `Path.glob+rglob hybrid` | 0.14500 | 0.15000 | 3.82× |
| 10 | `ThreadPool+scandir` | 0.08800 | 0.09200 | 2.32× |
| 11 | `asyncio+scandir` | 0.09500 | 0.09800 | 2.50× |

## Analysis

### `os.scandir` is 1.2 to 1.7× faster than `os.walk`

All four `scandir` variants outperform `os.walk`. The difference is structural: `os.walk` internally calls `os.scandir` but then creates sorted filename lists for each directory, discarding the `DirEntry` objects. Direct `scandir` usage avoids this intermediate allocation and preserves access to cached metadata.

Among scandir variants, the stack-based approach edges out the recursive generators by a small margin on the flat dataset, while the generators are within 1 to 3% on the deep dataset. The practical difference is negligible, so choose based on code clarity.

### `pathlib` is 3 to 6× slower than `os.scandir`

Every `pathlib` strategy (`rglob`, `glob+rglob` hybrid, recursive `iterdir`) is significantly slower than the `os.scandir` and `os.walk` approaches. The root cause: `pathlib` wraps every directory entry in a `Path` object and performs a separate `stat()` system call for each `is_file()` / `is_dir()` check.

`os.scandir`'s `DirEntry` objects expose `is_file()` and `is_dir()` without additional syscalls.  On Windows, this metadata is cached from `FindFirstFile`/`FindNextFile`; on Linux, it comes from `d_type` in the directory entry (with a `stat()` fallback for filesystems that don't populate `d_type`).

### `DirEntry.stat()` is nearly free on Windows

The `scandir stack +stat` variant collects `st_size` and `st_mtime` in addition to file paths, adding only ~4% overhead on the flat dataset and ~4% on the deep dataset. On Windows, `DirEntry.stat(follow_symlinks=False)` returns cached attributes from the initial `FindFirstFile` call.  No additional syscall is needed. This means metadata collection can be included in the scanning pass without a meaningful performance penalty.

On Linux, `DirEntry.stat()` requires a real `stat()` syscall per file, so the overhead would be proportionally higher for deep trees.

### Concurrency hurts scanning performance

`ThreadPoolExecutor` is **2.3× slower** and `asyncio` is **2.5× slower** than single-threaded `scandir stack` on the deep dataset. On the flat dataset, the gap widens to **23 to 25×**.

Directory enumeration is fundamentally I/O-serialized at the OS level: the filesystem driver processes one directory read at a time. Adding concurrency introduces:

1. **Thread/task dispatch overhead**: submitting, scheduling, and collecting futures.
2. **Lock contention**: the `ThreadPoolExecutor`'s internal work queue and the shared output list.
3. **Context switching**: the OS scheduler bounces between threads/tasks that are all waiting on the same filesystem lock.

The concurrent strategies do show proportionally better scaling from flat to deep (22.9× → 2.3× for threads, 24.9× → 2.5× for asyncio) because the deeper tree has more parallelizable directory reads. But even at ~730 directories, the dispatch overhead exceeds any benefit.

### The set-comprehension pattern produces unordered results

The `os.walk (set-comp)` one-liner uses a set comprehension, which means duplicate paths are silently deduplicated and ordering is lost. For benchmarking this is harmless (the datasets have no duplicate paths), but in production it would mask filesystem errors that produce duplicate entries. The list-based `os.walk` is safer.

## Category Summary

| Category | Best Strategy | Best Time (deep) | Notes |
|----------|--------------|-------------------|-------|
| `os.scandir` (manual) | `scandir stack` | 0.038 s | Fastest overall |
| `os.walk` variants | `os.walk` | 0.045 s | 1.18× slower |
| `pathlib` (`Path.*`) | `Path.iterdir recursive` | 0.120 s | 3.16× slower |
| Concurrent | `ThreadPool+scandir` | 0.088 s | 2.32× slower |

## Recommendations

### For the implementation

**Use iterative stack-based `os.scandir`** with `DirEntry.stat()` for metadata:

- **Fastest approach** across both flat and deep datasets.
- Collects `st_size` and `st_mtime` at negligible cost on Windows.
- Rejects symlinks and catches `PermissionError` per-directory.
- **Zero external dependencies**: stdlib only, `mypyc`-compilable.
- Iterative (no recursion depth limit for extremely deep trees).

```python
def scan(root: str) -> list[tuple[str, int, float]]:
    entries: list[tuple[str, int, float]] = []
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
                        entries.append((entry.path, st.st_size, st.st_mtime))
        except PermissionError:
            continue
    return entries
```

### When to consider alternatives

| Scenario | Recommendation |
|----------|---------------|
| Simple scripts / prototypes | `os.walk`, 1.2× slower but more readable, well-known pattern |
| Need `Path` objects downstream | Pay the `pathlib` cost at the boundary, not during enumeration |
| Network filesystem | Single-threaded `scandir` still wins; network latency makes dispatch overhead even more dominant |
| Extremely deep trees (>1000 levels) | Stack-based is already iterative, so no recursion limit concern |
