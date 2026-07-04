# directory-indexing-util

A performant, security-minded utility for recursively walking directory trees, hashing files, and producing a structured index. Results land in a Polars DataFrame exportable as Parquet, CSV, JSON, or NDJSON, driven by a single `dirindex` command or three library functions.

![One-shot indexing with dirindex](assets/index.gif)

!!! note "These demos cannot lie"
    Every GIF on this site is re-rendered by CI on each deploy from a scripted [VHS](https://github.com/charmbracelet/vhs) tape, running the real CLI against a synthetic directory tree. If the behavior changed, the recording would change with it.

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

- [CLI usage](usage.md): animated demos and the full flag reference.
- [Python library](library.md): the three-function API with signatures rendered from the docstrings.
- [Changelog](changelog.md) and [security policy](security.md).
