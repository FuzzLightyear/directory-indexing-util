# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Unit tests for :mod:`directory_indexing_util.config`.

The profile store is exercised through the ``DIRINDEX_CONFIG_DIR`` override so
every test reads and writes inside a temporary directory, never the real
per-user configuration location.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from directory_indexing_util.config import _config_dir, _profiles_path

# ---------------------------------------------------------------------------
# _config_dir
# ---------------------------------------------------------------------------


def test_config_dir_env_override_wins(monkeypatch, tmp_path: Path) -> None:
    """``DIRINDEX_CONFIG_DIR`` takes precedence over the platform default."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("DIRINDEX_CONFIG_DIR", str(tmp_path))
    assert _config_dir() == tmp_path


def test_config_dir_windows_uses_appdata(monkeypatch, tmp_path: Path) -> None:
    """On Windows the directory sits under ``%APPDATA%``."""
    monkeypatch.delenv("DIRINDEX_CONFIG_DIR", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert _config_dir() == tmp_path / "dirindex"


def test_config_dir_macos_uses_application_support(monkeypatch) -> None:
    """On macOS the directory sits under Application Support."""
    monkeypatch.delenv("DIRINDEX_CONFIG_DIR", raising=False)
    monkeypatch.setattr("sys.platform", "darwin")
    assert _config_dir() == Path.home() / "Library" / "Application Support" / "dirindex"


def test_config_dir_linux_honours_xdg(monkeypatch, tmp_path: Path) -> None:
    """On Linux ``$XDG_CONFIG_HOME`` selects the base directory."""
    monkeypatch.delenv("DIRINDEX_CONFIG_DIR", raising=False)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert _config_dir() == tmp_path / "dirindex"


def test_config_dir_linux_defaults_to_dot_config(monkeypatch) -> None:
    """Without ``$XDG_CONFIG_HOME`` the base falls back to ``~/.config``."""
    monkeypatch.delenv("DIRINDEX_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("sys.platform", "linux")
    assert _config_dir() == Path.home() / ".config" / "dirindex"


# ---------------------------------------------------------------------------
# _profiles_path
# ---------------------------------------------------------------------------


def test_profiles_path_is_inside_config_dir(monkeypatch, tmp_path: Path) -> None:
    """The profiles file is ``profiles.json`` under the configuration directory."""
    monkeypatch.setenv("DIRINDEX_CONFIG_DIR", str(tmp_path))
    assert _profiles_path() == tmp_path / "profiles.json"


# ---------------------------------------------------------------------------
# Fast path: importing config must not load heavy dependencies
# ---------------------------------------------------------------------------


def test_import_config_stays_stdlib_only() -> None:
    """Importing the config module pulls in no heavy third-party dependency.

    Runs in a fresh interpreter so the check is not contaminated by other
    tests that import polars or rich within this process.
    """
    code = (
        "import sys, directory_indexing_util.config; "
        "heavy = ('polars', 'rich', 'loguru', 'cmd2'); "
        "print([m for m in heavy if m in sys.modules])"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
