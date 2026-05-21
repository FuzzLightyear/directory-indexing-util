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
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `directory` | Yes | Source directory to scan recursively |
| `-o`, `--output` | No | Output file path or directory. Directories receive a timestamped filename (`scan_YYYYMMDD_HHMMSS.ext`). Defaults to the current working directory. |
| `-f`, `--format` | No | Output format: `parquet` (default), `csv`, `json`, `ndjson`. When `-o` specifies a file with a recognized extension, the format is inferred automatically. |

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
research/               Pre-implementation benchmarks, methodology, and findings
tests/                  Test suite (forthcoming)
pyproject.toml          Project metadata and dependency specification
```

## Research

The `research/` directory contains reproducible benchmarks and analysis comparing parallelism strategies, hash algorithms, chunk sizes, and directory scanning methods. Findings informed every design decision in the implementation. See [`research/README.md`](research/README.md) for details.
