# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Tests for package-level import behavior."""

from __future__ import annotations

import subprocess
import sys


def test_import_does_not_load_polars_or_rich() -> None:
    """Importing the package keeps the fast path: no polars or rich loaded.

    Runs in a fresh interpreter so the check is not contaminated by other
    tests that import polars within this process.
    """
    code = (
        "import sys, directory_indexing_util as d; "
        "print('polars' in sys.modules, 'rich' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False"


def test_lazy_exports_are_callable() -> None:
    """The lazily re-exported functions resolve and are callable."""
    from directory_indexing_util import hash_dataframe, index_directory, scan_directory

    assert callable(scan_directory)
    assert callable(hash_dataframe)
    assert callable(index_directory)


def test_import_does_not_load_config() -> None:
    """Importing the package does not load the config module (no profile I/O on import)."""
    code = (
        "import sys, directory_indexing_util; "
        "print('directory_indexing_util.config' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_build_parser_stays_on_fast_path() -> None:
    """Building the CLI parser loads no config, polars, rich, or loguru.

    This is what ``--help``/``--version`` do, so the fast path must not pull
    in the profile machinery or any heavy dependency.
    """
    code = (
        "import sys; from directory_indexing_util.__main__ import _build_parser; _build_parser(); "
        "heavy = ('polars', 'rich', 'loguru', 'directory_indexing_util.config'); "
        "print([m for m in heavy if m in sys.modules])"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
