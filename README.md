# directory-indexing-util

A maximally performant, security-minded utility for recursively walking directory trees, hashing files, and producing a structured index. Collects file hashes, paths, sizes, and metadata into a Polars DataFrame exportable as Parquet, CSV, JSON, or NDJSON.

Designed for two primary use cases:
1. **Full index** — enumerate files and compute content hashes for deduplication or integrity verification.
2. **Collection only** — enumerate files and metadata without hashing.

## Usage

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
| `-i`, `--include` | No | Comma-separated whitelist of file extensions to keep (e.g. `jpg,png,gif`). Leading dots and case are normalized. Files with no extension match the empty string `""`. |

> **Why whitelist only?** Pre-scan filtering matters most when you have a specific intent ("hash my photos"). The opposite case — "scan everything except a few noise extensions" — is cheap to express downstream with a single Polars filter on the resulting index, so a dedicated blacklist flag would add API surface without a meaningful performance win.

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

**Design rationale:** Parquet is the default output format because it preserves column types, compresses well, and is the fastest format for Polars to read back — critical when the scan output feeds into the hashing pipeline.

### Hashing

Compute content hashes for files referenced by a scan output:

```bash
# Hash a previously produced scan file
dirindex hash scan_20260521.parquet -o hashed.parquet

# Use a different algorithm
dirindex hash scan_20260521.parquet -a blake2b -o hashed.parquet
```

### Combined workflow (`index`)

Run scan + hash in a single process — no intermediate file, single command:

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
| `-i`, `--include` *(index only)* | No | Comma-separated extension whitelist, identical semantics to `scan`. |
| `-a`, `--algorithm` | No | One of `sha256` (default), `sha512`, `blake2b`, `md5`. Per the project benchmarks, SHA-256 via `hashlib.file_digest` hits ~2.4 GB/s on a `ThreadPoolExecutor.map` pool of `min(cpu_count * 2, 32)` workers — fast enough that BLAKE3 (extra dep) is not warranted. |

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
  "created_at": "2026-05-21T06:47:44.000000+00:00"
}
```

**Why a sidecar instead of an extra column?** Run metadata (algorithm, input directory, output path, timestamp) is per-run, not per-row. A constant column would be a strict subset of this information *and* redundant on every row. The sidecar captures full provenance once.

## Running via uv

The CLI is registered as a `[project.scripts]` entry point, so both forms work:

```bash
# After `uv sync`, dirindex is on PATH inside the venv
dirindex index /some/directory

# Without explicit install, uv resolves the entry point on demand
uv run dirindex index /some/directory
```

## Infrastructure

| Tool | Purpose |
|------|---------|
| `uv` | Package management, virtual environments, script execution |
| `polars` | High-performance DataFrames for collection, processing, and export |
| `rich` | Terminal progress display |
| `pytest` | Unit testing |
| `loguru` | Structured logging |
| `ruff` | Linting and formatting |

### Future

- `mypyc` compilation for hot-path acceleration (stdlib-only design enables this)

## Project Structure

```
src/directory_indexing_util/
    __init__.py         Package metadata
    __main__.py         CLI entry point (dirindex)
    scanner.py          Iterative os.scandir directory traversal
    hasher.py           Parallel file hashing (ThreadPoolExecutor + hashlib.file_digest)
    progress.py         Rich progress utilities (ms-precision elapsed, it/s)
research/               Pre-implementation benchmarks, methodology, and findings
tests/                  Test suite (forthcoming)
pyproject.toml          Project metadata and dependency specification
```

## Research

The `research/` directory contains reproducible benchmarks and analysis comparing parallelism strategies, hash algorithms, chunk sizes, and directory scanning methods. Findings informed every design decision in the implementation. See [`research/README.md`](research/README.md) for details.
