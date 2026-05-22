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

import json
import subprocess
import sys
from pathlib import Path

import polars as pl

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


def test_index_manifest_reports_zero_failed_when_all_readable(tmp_path: Path) -> None:
    """``failed_count`` is ``0`` when every file in the scan hashes successfully."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.bin").write_bytes(b"alpha")
    (src / "b.bin").write_bytes(b"beta")

    out = tmp_path / "index.parquet"
    _run("index", str(src), "-o", str(out))

    manifest = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert manifest["file_count"] == 2
    assert manifest["failed_count"] == 0


def test_hash_manifest_reports_unreadable_failures(tmp_path: Path) -> None:
    """``failed_count`` counts rows whose ``file_hash`` came back ``null``.

    The scan input is a hand-built parquet referencing one real file and
    one non-existent path; hashing the non-existent path returns ``None``,
    so the manifest's ``failed_count`` must report exactly one failure.
    """
    real = tmp_path / "real.bin"
    real.write_bytes(b"payload")
    ghost = tmp_path / "ghost.bin"

    scan_path = tmp_path / "scan.parquet"
    pl.DataFrame(
        {
            "file_name": ["real.bin", "ghost.bin"],
            "file_path": [str(real), str(ghost)],
        }
    ).write_parquet(scan_path)

    out = tmp_path / "hashed.parquet"
    _run("hash", str(scan_path), "-o", str(out))

    manifest = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert manifest["file_count"] == 2
    assert manifest["failed_count"] == 1

    hashed = pl.read_parquet(out)
    nulls = hashed.get_column("file_hash").is_null().to_list()
    assert nulls == [False, True]


def test_index_summary_flags_unreadable_count(tmp_path: Path) -> None:
    """When some files fail, the stdout summary surfaces the failure count.

    Uses a scan input with a non-existent path to force one failure, so
    the CLI prints the ``(N unreadable)`` annotation.  Bypasses scan and
    feeds the synthetic scan file directly to ``hash``.
    """
    real = tmp_path / "real.bin"
    real.write_bytes(b"x")
    scan_path = tmp_path / "scan.parquet"
    pl.DataFrame(
        {
            "file_name": ["real.bin", "missing.bin"],
            "file_path": [str(real), str(tmp_path / "missing.bin")],
        }
    ).write_parquet(scan_path)

    out = tmp_path / "hashed.parquet"
    result = _run("hash", str(scan_path), "-o", str(out))
    assert "1 unreadable" in result.stdout
