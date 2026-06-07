# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-22

### Added

#### CLI

- `dirindex scan <dir>`: iterative `os.scandir` traversal producing a Polars DataFrame of `file_name` and `file_path`, with symlink and directory-junction defences.
- `dirindex hash <scan_file>`: parallel hashing of files referenced by a scan output, using `ThreadPoolExecutor.map` + `hashlib.file_digest` (~2.4 GB/s on SHA-256 per benchmarks).
- `dirindex index <dir>`: one-shot scan + hash in a single process.
- `-V` / `--version` flag: instant, no heavy imports loaded.
- `-i` / `--include`: comma-separated extension whitelist with normalised case and optional leading dots.
- `-a` / `--algorithm`: choose between `sha256` (default), `sha512`, `blake2b`, `md5`.
- `-w` / `--workers`: override the auto-tuned worker count.
- `-f` / `--format`: explicit output format, with inference from the `-o` extension when omitted.

#### Library API

- Public surface re-exported from the package root: `scan_directory`, `hash_dataframe`, `index_directory`, `ALGORITHMS`, `DEFAULT_ALGORITHM`, `__version__`.
- `index_directory(root, *, algorithm, include, workers, desc)` convenience wrapper for the scan + hash workflow.
- Silent-by-default APIs: pass `desc=` to opt into a Rich progress bar.
- `Path | str` inputs accepted on path-taking functions.
- PEP 561 `py.typed` marker shipped in the wheel for downstream type-checker support.

#### Output

- Polars DataFrame output exportable as Parquet (default), CSV, JSON, or NDJSON.
- Hash output schema is a strict extension of scan: `file_name`, `file_path`, `file_hash` (Utf8, nullable on unreadable files).
- Sidecar JSON manifest (`{output_stem}.meta.json`) captures `command`, `input_path`, `output_path`, `hash_algorithm`, `file_count`, `failed_count`, `created_at`, and is written as UTF-8 with LF line endings for byte-identical output across platforms.

#### Quality

- 99-test pytest suite (plus 2 POSIX-only symlink tests) covering scanner, hasher, combined index, internal CLI helpers, and subprocess-level CLI behaviour. Filesystem-root and edge-case coverage included.
- Pre-commit configuration with ruff, ruff-format, codespell, and standard hygiene hooks as the local quality gate.
- Cross-platform support verified on Windows 11 and Linux; filesystem-root scanning (POSIX `/`, Windows drive roots) handled correctly.

### Performance

- `dirindex --version` and `dirindex --help` measured at ~70 ms cold start.  Heavy dependencies (polars, rich, loguru) are lazy-imported inside command handlers so non-command invocations do not pay for them.
- Hashing pool defaults to `min(os.cpu_count() * 2, 32)` workers, the research-validated sweet spot.

### Project history

- Performance research phase tagged as `research-complete`: benchmark suite comparing hashing parallelism strategies, scanning enumeration methods, and dependency tiers.
- MVP feature set tagged as `mvp-complete`: scan, hash, index subcommands operational.
- Library API surface tagged as `library-ready`: silent-by-default APIs, `Path | str` inputs, public re-exports, py.typed marker.

[Unreleased]: https://github.com/FuzzLightyear/directory-indexing-util/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/FuzzLightyear/directory-indexing-util/releases/tag/v0.1.0
