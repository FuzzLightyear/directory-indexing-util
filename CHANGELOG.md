# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Extension blacklist. `scan` and `index` accept `-x/--exclude` (mutually exclusive with `-i/--include`), and `scan_directory`/`index_directory` accept `exclude=`, to drop files by extension. The library can combine include and exclude (include applied first, then exclude); the CLI keeps the two mutually exclusive.
- Continuous integration. Every pull request and push to main runs the full quality gate on GitHub Actions: ruff lint and format checks, mypy, the test suite, and a `pip-audit` vulnerability scan of the exported lockfile. Actions are pinned to commit SHAs and refreshed monthly by Dependabot.
- Configuration profiles. Save the *how* of a run (algorithm, workers, format, extension filter) as a named preset and reuse it with `--profile` on `scan`/`hash`/`index`, or capture it from a run with `--save-profile`. A `dirindex profile` subcommand lists, shows, saves (replace) or updates (merge), deletes, and sets a default; the profiles directory is settable via `dirindex profile dir`, `--profiles-dir`, or `$DIRINDEX_PROFILES_DIR`. Profiles are per-user TOML files parsed with the standard library `tomllib`, and explicit flags always override a profile.

### Fixed

- Output-format inference from the `-o` extension now applies whenever `-f` is absent, where previously a profile-supplied format silently suppressed it, and an explicit `-f` is always respected even when it names the default format.
- The `hash` and `index` commands report a rejected hashing input (a `file_path` column of the wrong type, or the blake3 backend missing) as a one-line error with exit code 1 instead of a Python traceback.

### Changed

- All runtime and development dependencies are pinned to exact versions, and a hash-verified `uv.lock` is now committed, so installs are reproducible and tamper-evident. `pip-audit` reports no known vulnerabilities for the pinned set.
- `blake3` is now always a recognized algorithm name on the CLI and in profiles, with its optional backend checked at hash time: selecting it without the package installed reports a clear "install the blake3 extra" message instead of a cryptic argument error, and a profile naming `blake3` stays portable across installs.

## [0.2.0] - 2026-06-07

### Added

- Optional `blake3` hash algorithm, selectable as `-a blake3` on the CLI and `algorithm="blake3"` in the library when the new `blake3` extra is installed (`uv sync --extra blake3`). It hashes faster than SHA-256 on a mixed-size benchmark and stays an opt-in dependency; the default remains SHA-256.

### Security

- The `hash` subcommand validates each path from an untrusted scan file before opening it: UNC and network paths, symlinks, and non-regular files are skipped. This prevents an outbound SMB credential leak from a crafted UNC path and hangs on FIFOs or devices.
- CSV output neutralizes spreadsheet formula injection: any field beginning with `=`, `+`, `-`, `@`, a tab, or a carriage return is prefixed with a quote, so a hostile file name cannot execute when the CSV is opened in a spreadsheet.
- The scanner survives NTFS junction cycles. It records visited resolved directories and skips repeats, and a malformed or cyclic entry is skipped rather than aborting the scan.
- `hash_dataframe` requires the `file_path` column to be `Utf8`, rejecting a crafted integer column that `open()` would otherwise treat as a file descriptor.

### Performance

- Importing the package no longer eagerly loads polars and rich, so `dirindex --help` and `--version` run at about 68 ms cold start rather than about 288 ms.
- The scanner resolves each directory once instead of resolving every file, cutting scan time from about 123 ms to about 15 ms on a 1572-file tree, with the same output and containment guarantees.

### Fixed

- The documented benchmark commands use `--extra research` instead of the non-existent `--group research`.
- The README intro and API table match the actual output: file paths and content hashes, and the `algorithm="sha256"` default. `pre-commit` is now declared in the `dev` extra.

### Changed

- Documentation reworded for clarity and consistency, and the CLI internals were refactored (a `formats` module and shared command helpers) with no change in behavior.

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

[Unreleased]: https://github.com/FuzzLightyear/directory-indexing-util/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/FuzzLightyear/directory-indexing-util/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/FuzzLightyear/directory-indexing-util/releases/tag/v0.1.0
