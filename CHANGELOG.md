# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `dirindex scan <dir>` — iterative `os.scandir` traversal producing a Polars DataFrame of `file_name` and `file_path`, with symlink and directory-junction defenses.
- `dirindex hash <scan_file>` — parallel SHA-256 (default) hashing of files referenced by a scan output, using `ThreadPoolExecutor.map` + `hashlib.file_digest` (~2.4 GB/s per benchmarks).
- `dirindex index <dir>` — one-shot scan + hash in a single process.
- Public Python API: `scan_directory`, `hash_dataframe`, `index_directory`, `ALGORITHMS`, `DEFAULT_ALGORITHM` re-exported from the package root.
- `index_directory(root, *, algorithm, include, workers, desc)` convenience wrapper for library use.
- Configurable worker thread count via `workers=` parameter and `-w/--workers` CLI flag. Defaults to the research-validated `min(os.cpu_count() * 2, 32)`.
- Extension whitelist via `include=` and `-i/--include`, supporting comma-separated lists with normalized case and optional leading dots.
- Output formats: Parquet (default), CSV, JSON, NDJSON, with extension-based inference when `-o` points to a file.
- Hash algorithms: `sha256` (default), `sha512`, `blake2b`, `md5`.
- Sidecar JSON manifest written alongside `hash`/`index` outputs capturing command, input path, output path, algorithm, file count, and timestamp.
- PEP 561 `py.typed` marker for typed package support in downstream type checkers.
- Cross-platform support verified on Windows 11 and Linux; filesystem-root scanning (POSIX `/`, Windows drive roots) handled correctly.

### Project history

- Performance research phase tagged as `research-complete` — benchmark suite comparing hashing parallelism strategies, scanning enumeration methods, and dependency tiers.
- MVP feature set tagged as `mvp-complete` — scan, hash, index subcommands operational.
- Library API surface tagged as `library-ready` — silent-by-default APIs, `Path | str` inputs, public re-exports, py.typed marker.

[Unreleased]: https://github.com/FuzzLightyear/directory-indexing-util/compare/...HEAD
