# directory-indexing-util

A performant, security-minded utility for recursively walking directory trees, hashing files, and producing a structured index. Results land in a Polars DataFrame exportable as Parquet, CSV, JSON, or NDJSON, driven by a single `dirindex` command or three library functions.

## Install

Not yet on PyPI. Install straight from GitHub:

```bash
uv tool install git+https://github.com/FuzzLightyear/directory-indexing-util
dirindex --version
```

Or work from a clone:

```bash
git clone https://github.com/FuzzLightyear/directory-indexing-util
cd directory-indexing-util
uv sync
uv run dirindex --version
```

## Highlights

- Iterative `os.scandir` traversal that skips symlinks and defends against directory-junction escapes.
- Parallel hashing through `ThreadPoolExecutor` and `hashlib.file_digest`, auto-tuned worker pool, optional blake3.
- Parquet, CSV, JSON, or NDJSON output, plus a JSON sidecar manifest recording full run provenance.
- Saved [profiles](usage.md#profiles) so repeat runs stop retyping the same flags.
- A typed, `py.typed` library API; the CLI is a thin wrapper over it.

## Where next

- [CLI usage](usage.md): the full flag reference.
- [Python library](library.md): the three-function API with signatures rendered from the docstrings.
- [Changelog](changelog.md) and [security policy](security.md).
