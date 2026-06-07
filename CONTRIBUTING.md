# Contributing

This is a personal project, maintained casually. **External pull requests are not accepted, but issues are welcome and the supported channel for reporting bugs or suggesting features.**

## Filing an issue

The "New Issue" page offers two templates:

- **Bug report**: for incorrect or surprising behaviour.
- **Feature request**: for missing capabilities or API gaps.

A good issue includes enough information for a single-pass fix: minimal reproduction, expected vs. actual output, environment details. The templates prompt for these.

## Security

If you believe you've found a vulnerability, please **do not** open a public issue. See [`SECURITY.md`](SECURITY.md) for the private reporting process.

## Working with the code locally

The MIT license permits you to fork and modify the project freely. These instructions are provided for your convenience if you want to run the dev setup on your own copy; merging your changes back upstream is not the intended workflow.

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
uv sync --extra research
uv run research/benchmarks/hashing_benchmark.py
uv run research/benchmarks/scanning_benchmark.py
```

## Maintainer conventions

These apply to the maintainer's own commits; they're documented here so the project's history stays legible.

- **Branch from `main`**, never commit directly. Name branches after the work: `feat/<feature>`, `fix/<issue>`, `docs/<topic>`, `perf/<area>`, `research/<topic>`.
- **Atomic commits.** Each commit is one logical change with a focused message. Imperative subject (≤ 72 chars), blank line, body explaining the *why* (not the *what*; the diff already shows what).
- **No comments in code** other than the file-header copyright/SPDX banner; behavioural notes belong in numpydoc-style docstrings (`Notes`, `Parameters`, `Returns`).
- **Merge strategy:** rebase-and-merge to keep `main` linear while preserving each PR's atomic commits. Squash only when a branch's commits are not individually meaningful. Release tags use semver (`v0.1.0`) and are applied to `main` after the release PR merges.

## Maintenance status

This project is maintained on a personal schedule with no commercial response-time commitment. Issues will be triaged and addressed when time and interest allow.
