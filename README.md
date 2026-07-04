# directory-indexing-util

[![CI](https://github.com/FuzzLightyear/directory-indexing-util/actions/workflows/ci.yml/badge.svg)](https://github.com/FuzzLightyear/directory-indexing-util/actions/workflows/ci.yml)
[![Docs](https://github.com/FuzzLightyear/directory-indexing-util/actions/workflows/docs.yml/badge.svg)](https://fuzzlightyear.github.io/directory-indexing-util/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

A performant, security-minded utility for recursively walking directory trees, hashing files, and producing a structured index. Collects file paths and content hashes into a Polars DataFrame exportable as Parquet, CSV, JSON, or NDJSON.

Designed for two primary use cases:
1. **Full index**: enumerate files and compute content hashes for deduplication or integrity verification.
2. **Collection only**: enumerate files without computing hashes.

> **Maintenance status:** Personal project, casually maintained. **Issues are welcome** for bugs and feature requests. **External pull requests are not accepted**.  Fork freely under MIT for your own changes. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

**Documentation:** guides, animated terminal demos, and the full API reference live at [fuzzlightyear.github.io/directory-indexing-util](https://fuzzlightyear.github.io/directory-indexing-util/).

## Usage

<!-- --8<-- [start:cli] -->

### Scanning

Recursively enumerate all files in a directory and export the index:

```bash
# Default: parquet output in the current directory (timestamped filename)
dirindex scan /path/to/directory

# Export to a specific file (format inferred from extension)
dirindex scan /path/to/directory -o index.csv

# Export to a directory with explicit format
dirindex scan /path/to/directory -o /output/dir -f json

# Whitelist only image extensions
dirindex scan /path/to/directory -i jpg,png,gif
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `directory` | Yes | Source directory to scan recursively |
| `-o`, `--output` | No | Output file path or directory. Directories receive a timestamped filename (`scan_YYYYMMDD_HHMMSS.ext`). Defaults to the current working directory. |
| `-f`, `--format` | No | Output format: `parquet` (default), `csv`, `json`, `ndjson`. When `-o` specifies a file with a recognized extension, the format is inferred automatically. |
| `-i`, `--include` | No | Comma-separated whitelist of file extensions to keep (e.g. `jpg,png,gif`). Leading dots and case are normalized. Files with no extension match the empty string `""`. Mutually exclusive with `--exclude`. |
| `-x`, `--exclude` | No | Comma-separated blacklist of file extensions to drop (e.g. `tmp,log`). Same normalization as `--include`, and mutually exclusive with it. |

> **Whitelist or blacklist:** use `--include` to keep only certain extensions ("hash my photos") or `--exclude` to drop noise extensions ("skip tmp and log"). The two are mutually exclusive on the command line, since one pass needs a single rule. The library `scan_directory` accepts both `include` and `exclude` if you want to combine them: include is applied first, then exclude.

### Scan Output Format

The scan produces a two-column DataFrame that serves as the canonical input for downstream operations (e.g., file hashing):

| Column | Type | Description |
|--------|------|-------------|
| `file_name` | `Utf8` | File basename (e.g., `report.pdf`) |
| `file_path` | `Utf8` | Absolute resolved path (e.g., `D:\Documents\report.pdf`) |

**Security guarantees:**
- Symlinks are skipped entirely
- Every resolved path is validated to remain within the scan root, preventing directory-junction escapes
- Inaccessible directories are silently skipped (no `PermissionError` propagation)

**Design rationale:** Parquet is the default output format because it preserves column types, compresses well, and is the fastest format for Polars to read back, which is critical when the scan output feeds into the hashing pipeline.

### Hashing

Compute content hashes for files referenced by a scan output:

```bash
# Hash a previously produced scan file
dirindex hash scan_20260521.parquet -o hashed.parquet

# Use a different algorithm
dirindex hash scan_20260521.parquet -a blake2b -o hashed.parquet
```

### Combined workflow (`index`)

Run scan + hash in a single process, with no intermediate file and a single command:

```bash
# One-shot index of a directory
dirindex index /path/to/directory -o index.parquet

# With extension whitelist and explicit algorithm
dirindex index /path/to/directory -i jpg,png,heic -a sha512 -o /output/dir
```

**Arguments for `hash` and `index`:**

| Argument | Required | Description |
|----------|----------|-------------|
| `input` *(hash)* / `directory` *(index)* | Yes | Scan output file (`hash`) or source directory (`index`) |
| `-o`, `--output` | No | Output file path or directory. Directories receive a timestamped filename (`hash_YYYYMMDD_HHMMSS.ext` or `index_YYYYMMDD_HHMMSS.ext`). |
| `-f`, `--format` | No | Output format: `parquet` (default), `csv`, `json`, `ndjson`. Inferred from extension when `-o` is a file. |
| `-i`, `--include` *(index only)* | No | Comma-separated extension whitelist, identical semantics to `scan`.  Mutually exclusive with `--exclude`. |
| `-x`, `--exclude` *(index only)* | No | Comma-separated extension blacklist, identical semantics to `scan`. |
| `-a`, `--algorithm` | No | One of `sha256` (default), `sha512`, `blake2b`, `md5`, plus `blake3` when the optional `blake3` extra is installed (`uv sync --extra blake3`). SHA-256 via `hashlib.file_digest` is the default; blake3 hashes faster on a mixed-size benchmark and is offered as an opt-in rather than a required dependency. |
| `-w`, `--workers` | No | Worker thread count for hashing. Auto-tunes to `min(cpu_count * 2, 32)` when omitted. Lower it under CPU quotas, when running multiple instances concurrently, or on hardware where the default saturates disk I/O. |

### Hash Output Format

`hash` and `index` produce a three-column DataFrame extending the scan schema:

| Column | Type | Description |
|--------|------|-------------|
| `file_name` | `Utf8` | from scan (basename) |
| `file_path` | `Utf8` | from scan (absolute resolved path) |
| `file_hash` | `Utf8` (nullable) | Lowercase hex digest. `null` when the file could not be read (permission denied, deleted between scan and hash, etc.). |

### Sidecar Manifest

Every `hash` or `index` invocation also writes a JSON manifest beside the data file, named `{output_stem}.meta.json`:

```json
{
  "command": "index",
  "input_path": "D:\\Photos",
  "output_path": "index_20260521_064744.parquet",
  "hash_algorithm": "sha256",
  "file_count": 1234,
  "failed_count": 0,
  "created_at": "2026-05-21T06:47:44.000000+00:00"
}
```

| Field | Purpose |
|---|---|
| `command` | Subcommand that produced the output (`"hash"` or `"index"`). |
| `input_path` | Absolute path of the input: scan file for `hash`, source directory for `index`. |
| `output_path` | Data file written alongside this manifest. |
| `hash_algorithm` | Algorithm used for the run (one of the recognized names, including `blake3`). |
| `file_count` | Total rows in the produced index. |
| `failed_count` | Subset of `file_count` whose `file_hash` is `null` (file unreadable at hash time). `0` when every file hashed cleanly. |
| `created_at` | ISO 8601 UTC timestamp. |

The manifest is UTF-8 encoded with LF line endings on every platform, so the file is byte-identical regardless of the producing OS.

**Why a sidecar instead of an extra column?** Run metadata (algorithm, input directory, output path, timestamp, counts) is per-run, not per-row. Constant columns would be a strict subset of this information *and* redundant on every row. The sidecar captures full provenance once.

## Profiles

A profile is a saved preset of the *how* of a run: algorithm, worker count, output format, and extension filter. It travels by name across directories, so you stop retyping the same flags.

```bash
# Save a preset: capture the flags from a run, or define one directly
dirindex index /path/to/photos -i jpg,png -a blake3 -f csv --save-profile photos
dirindex profile save photos -i jpg,png -a blake3 -f csv

# Apply it; explicit flags still win
dirindex index /path/to/other --profile photos
dirindex scan /path/to/other --profile photos -f json   # -f json overrides the profile

# Manage profiles
dirindex profile list              # names, with the default marked
dirindex profile show photos       # the flags the profile applies
dirindex profile update photos -a sha512   # change one field, keep the rest
dirindex profile default photos    # auto-applied when no --profile is given
dirindex profile delete photos     # prints the command to recreate it
```

You can also hand-author a profile: drop a `<name>.toml` into the profiles directory.

```toml
# photos.toml
algorithm = "blake3"
mode      = "whitelist"      # or "blacklist"
ext       = ["jpg", "png"]   # or: ext = "jpg,png"
format    = "csv"
```

**Precedence:** an explicit flag beats a `--profile` value, which beats the configured default profile, which beats the built-in default. A profile stores only the *how* (`mode`, `ext`, `algorithm`, `workers`, `format`), never the directory, input, or output: where a run reads and writes is per-run.

**Where profiles live.** By default the per-user config directory (`%APPDATA%\dirindex` on Windows, `~/Library/Application Support/dirindex` on macOS, `$XDG_CONFIG_HOME/dirindex` or `~/.config/dirindex` elsewhere), in a `profiles/` subdirectory, alongside a `settings.toml` recording the chosen directory and default. Point it elsewhere for one run with `--profiles-dir` or `$DIRINDEX_PROFILES_DIR`, or persist a location with `dirindex profile dir <path>`. The location is never derived from where the package is installed, so profiles behave identically from a source checkout, a `pip install`, or a `uvx` run, and are never written into a scanned repository.

| `profile` action | Description |
|---|---|
| `list` | List profile names; the default is marked. |
| `show <name>` | Print the flags a profile applies. |
| `save <name> [flags]` | Define a profile from `-a`, `-w`, `-f`, and `-i`/`-x`: it becomes exactly those flags, replacing any existing profile of that name. |
| `update <name> [flags]` | Change only the given fields of an existing profile, keeping the rest. A new `-i`/`-x` replaces the whole filter. |
| `delete <name>` | Delete a profile and print the `profile save` command that recreates it. |
| `default [<name>] [--clear]` | Show, set, or clear the auto-applied default. |
| `dir [<path>]` | Show or persist the profiles directory. |

Profile files are TOML, parsed with the standard library `tomllib`, which executes no code. They are validated against a closed schema and bounded in size and count, so a hand-edited or hostile file cannot run code or crash a run.

## Running via uv

The CLI is registered as a `[project.scripts]` entry point, so both forms work:

```bash
# After `uv sync`, dirindex is on PATH inside the venv
dirindex index /some/directory

# Without explicit install, uv resolves the entry point on demand
uv run dirindex index /some/directory

# Inspect the installed version (instant, no heavy imports)
dirindex --version
```

<!-- --8<-- [end:cli] -->

## Use as a Library

<!-- --8<-- [start:library] -->

The CLI is a thin wrapper over a stable Python API.  Add the package to your project (`uv add directory-indexing-util`) and import directly:

```python
from directory_indexing_util import (
    scan_directory,
    hash_dataframe,
    index_directory,
    ALGORITHMS,
    DEFAULT_ALGORITHM,
)

# Scan only: returns a Polars DataFrame with file_name and file_path columns
df = scan_directory("/path/to/dir", include={"jpg", "png"})

# Hash an existing scan result: adds a file_hash column
df = hash_dataframe(df, algorithm="sha256")

# One-shot: scan + hash in a single call
df = index_directory("/path/to/dir", algorithm="blake2b", include={"py"})

# Write with Polars however you like
df.write_parquet("index.parquet")
```

All path-accepting functions accept either `pathlib.Path` or `str`.  Functions are silent by default; pass `desc="Hashing"` (or any label) to `hash_dataframe`/`index_directory` to drive a Rich progress bar:

```python
df = index_directory("/big/library", desc="Indexing photos")
```

The package ships inline type hints with a [PEP 561](https://peps.python.org/pep-0561/) `py.typed` marker, so mypy, pyright, and IDE language servers in consuming projects pick up the annotations automatically.

**Public API surface:**

| Symbol | Kind | Purpose |
|---|---|---|
| `scan_directory(root, *, include=None, exclude=None)` | function | Recursively enumerate files into a DataFrame |
| `hash_dataframe(df, *, algorithm="sha256", workers=None, desc=None)` | function | Hash files referenced by a DataFrame's `file_path` column |
| `index_directory(root, *, algorithm="sha256", include=None, exclude=None, workers=None, desc=None)` | function | Scan + hash in one call |
| `ALGORITHMS` | tuple[str, ...] | Tuple of supported hash algorithm names |
| `DEFAULT_ALGORITHM` | str | Default algorithm (`"sha256"`) |
| `__version__` | str | Installed package version |

Anything not in this list (internal modules, CLI helpers, the `progress` utilities) is an implementation detail and may change without notice.

<!-- --8<-- [end:library] -->

## Platform Support

Tested on Windows 11 and Linux. The implementation uses only cross-platform stdlib APIs (`os.scandir`, `hashlib.file_digest`, `concurrent.futures`) plus Polars, Rich, and Loguru, all of which support both platforms natively.

Notable cross-platform considerations the package already handles:

- **Path separators**: `os.sep` is used for prefix construction; both Windows backslash and POSIX forward slash work transparently.
- **Filesystem roots**: POSIX `/` and Windows drive roots (`C:\`) are valid scan inputs.
- **Symlinks and Windows junctions**: both are skipped before traversal; the resolved-path containment check is the second-line defense against junction escapes.
- **Case sensitivity**: `Path.resolve()` canonicalizes to filesystem case, so the within-root containment check works consistently on case-insensitive (Windows) and case-sensitive (Linux) filesystems.
- **Unicode in paths**: manifest JSON is written as UTF-8 with LF line endings on every platform, so non-ASCII filenames round-trip safely and the file is byte-identical regardless of the producing OS.

## Infrastructure

| Tool | Purpose |
|------|---------|
| `uv` | Package management, virtual environments, script execution |
| `polars` | High-performance DataFrames for collection, processing, and export |
| `rich` | Terminal progress display |
| `pytest` | Unit testing |
| `loguru` | Structured logging |
| `ruff` | Linting and formatting |
| `mypy` | Static type checking |

## Project Structure

```
src/directory_indexing_util/
    __init__.py         Public API and __version__
    __main__.py         CLI entry point (dirindex)
    _algorithms.py      Stdlib-only hash algorithm constants
    config.py           Per-user config directory and the saved-profile store
    formats.py          Output-path resolution, format-aware I/O, run manifest
    scanner.py          Iterative os.scandir directory traversal
    hasher.py           Parallel file hashing (ThreadPoolExecutor + hashlib.file_digest)
    progress.py         Rich progress utilities (ms-precision elapsed, it/s)
tests/                  pytest suite covering library + CLI
research/               Pre-implementation benchmarks, methodology, and findings
pyproject.toml          Project metadata and dependency specification
```

## Research

The `research/` directory contains reproducible benchmarks and analysis comparing parallelism strategies, hash algorithms, chunk sizes, and directory scanning methods. Findings informed every design decision in the implementation. See [`research/README.md`](research/README.md) for details.

## Development

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full developer guide. The short version:

```bash
uv sync --extra dev
uv run pre-commit install
uv run pytest
```

Security policy: [`SECURITY.md`](SECURITY.md). Release notes: [`CHANGELOG.md`](CHANGELOG.md). License: MIT, see [`LICENSE`](LICENSE).
