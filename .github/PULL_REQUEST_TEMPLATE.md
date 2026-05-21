## Summary

<!-- One or two sentences on what this PR does and why. The diff shows the *what*; explain the *why*. -->

## Changes

<!-- Bulleted list of the substantive changes. -->

-
-

## Checklist

- [ ] Commits are atomic with imperative-mood subjects and why-not-what bodies
- [ ] `uv run pytest` passes
- [ ] `uv run ruff check` and `uv run ruff format --check` pass
- [ ] Pre-commit hooks pass locally (`uv run pre-commit run --all-files`)
- [ ] New behaviour is covered by tests under `tests/`
- [ ] Public API changes are reflected in numpydoc docstrings and the README
- [ ] `CHANGELOG.md` `[Unreleased]` section updated under the appropriate heading
- [ ] No inline comments added (use docstring `Notes` for behavioural detail)
- [ ] If the change touches paths, scanning, or hashing: behaviour verified on both Windows and Linux paths (mentally or actually)

## Related

<!-- Link to issues, prior discussions, related PRs, or research artifacts. -->
