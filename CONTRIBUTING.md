# Contributing

Thanks for your interest in improving `directory-indexing-util`. This is a small, opinionated project; the guidance below keeps the bar high and the iteration fast.

## Development setup

Requirements: Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/FuzzLightyear/directory-indexing-util.git
cd directory-indexing-util
uv sync --extra dev          # installs runtime + dev dependencies
uv run pre-commit install    # one-time: enables hooks for every commit
```

Run the test suite:

```bash
uv run pytest
```

Run the linters manually (pre-commit does this automatically on commit):

```bash
uv run ruff check
uv run ruff format --check
```

Reproduce the research benchmarks:

```bash
uv sync --group research
uv run research/benchmarks/hashing_benchmark.py
uv run research/benchmarks/scanning_benchmark.py
```

## Branching and commits

- **Branch from `main`**, never commit to it directly. Name branches after the work: `feat/<feature>`, `fix/<issue>`, `docs/<topic>`, `perf/<area>`, `research/<topic>`.
- **Atomic commits.** Each commit should be one logical change with a focused message. Avoid "WIP" or "fixes" — squash locally before pushing.
- **Commit message style** matches the existing history: imperative subject (≤ 72 chars), blank line, body explaining the *why* (not the *what* — the diff already shows what). Co-author trailer for collaborators.
- **No comments in code** other than the file-header copyright/SPDX banner; behavioural notes belong in numpydoc-style docstrings (`Notes`, `Parameters`, `Returns`).

## Pull requests

- One PR per logical change.
- Update `CHANGELOG.md`'s `[Unreleased]` section with a one-line entry under the appropriate heading (`Added`, `Changed`, `Fixed`, `Removed`, `Security`).
- Ensure `uv run pytest` and `uv run ruff check` both pass.
- The PR template will prompt you to confirm the above.

## Merge strategy

- We **squash-merge** PRs to keep `main` linear.
- For substantive phase milestones (feature complete, research complete, refactor complete), the maintainer tags the **tip of the feature branch before merge** with an annotated tag (e.g., `mvp-complete`, `library-ready`). This preserves the granular commit history that the squash would otherwise collapse. Tag names are short, descriptive, and unversioned; release tags use semver (`v0.1.0`).

## Code style

- Public functions and classes have numpydoc-style docstrings with `Parameters`, `Returns`, `Raises`, and `Notes` as applicable.
- Type hints on every public signature; the package ships a `py.typed` marker so consumers' type checkers pick them up.
- Cross-platform: any code touching paths must work on Windows and Linux (no hardcoded separators, no platform-specific syscalls without a guard).

## Security

If you believe you've found a vulnerability, please **do not** open a public issue. See `SECURITY.md` for the private reporting process.
