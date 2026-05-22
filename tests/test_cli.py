# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""End-to-end tests for the ``dirindex`` CLI invoked via subprocess.

Library-level tests in ``test_scanner.py`` / ``test_hasher.py`` /
``test_index.py`` cover the Python API.  These tests cover the CLI
itself — argument parsing, output-path resolution, format inference,
and the sidecar manifest — by spawning the real entry point and
inspecting its stdout/stderr/exit code and the files it writes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from directory_indexing_util import __version__

_CLI = (sys.executable, "-m", "directory_indexing_util")


def _run(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run the CLI and return the completed process.

    Parameters
    ----------
    *args : str
        Arguments to pass after the module invocation.
    cwd : Path, optional
        Working directory for the subprocess.
    check : bool, default ``True``
        Raise ``CalledProcessError`` on non-zero exit.

    Returns
    -------
    subprocess.CompletedProcess
        Result with captured stdout / stderr / returncode.
    """
    return subprocess.run(
        [*_CLI, *args],
        capture_output=True,
        text=True,
        check=check,
        cwd=cwd,
    )


def test_version_flag_long() -> None:
    """``--version`` prints ``dirindex <version>`` and exits 0."""
    result = _run("--version")
    assert result.returncode == 0
    assert "dirindex" in result.stdout
    assert __version__ in result.stdout


def test_version_flag_short() -> None:
    """``-V`` is the short form for ``--version``."""
    result = _run("-V")
    assert result.returncode == 0
    assert __version__ in result.stdout


def test_version_does_not_print_to_stderr() -> None:
    """``--version`` writes only to stdout; stderr stays empty."""
    result = _run("--version")
    assert result.stderr == ""
