# directory-indexing-util

A maximally performant, security-minded utility for recursively walking directory trees, hashing files, and producing a structured index. Collects file hashes, paths, sizes, and metadata into a Polars DataFrame exportable as JSON.

Designed for two primary use cases:
1. **Full index** — enumerate files and compute content hashes for deduplication or integrity verification.
2. **Collection only** — enumerate files and metadata without hashing.

## Infrastructure

| Tool | Purpose |
|------|---------|
| `uv` | Package management, virtual environments, script execution |
| `polars` | High-performance DataFrames for collection, processing, and export |
| `pytest` | Unit testing |
| `loguru` | Structured logging |
| `ruff` | Linting and formatting |

### Future

- `mypyc` compilation for hot-path acceleration (stdlib-only design enables this)

## Project Structure

```
research/           Pre-implementation benchmarks, methodology, and findings
src/                Application source (forthcoming)
tests/              Test suite (forthcoming)
pyproject.toml      Project metadata and dependency specification
```

## Research

The `research/` directory contains reproducible benchmarks and analysis comparing parallelism strategies, hash algorithms, chunk sizes, and directory scanning methods. Findings informed every design decision in the implementation. See [`research/README.md`](research/README.md) for details.
