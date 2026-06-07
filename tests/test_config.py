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

import pytest

from directory_indexing_util.config import (
    ConfigError,
    _clean_field,
    _clean_profile,
    _config_dir,
    _normalize_extensions,
    _profiles_path,
)

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


# ---------------------------------------------------------------------------
# _normalize_extensions
# ---------------------------------------------------------------------------


def test_normalize_extensions_none_returns_none() -> None:
    """``None`` normalizes to ``None`` so an unset filter stays unset."""
    assert _normalize_extensions(None) is None


def test_normalize_extensions_parses_comma_string() -> None:
    """A comma-separated string is split, normalized, and sorted."""
    assert _normalize_extensions(" .JPG, png ,jpg") == ["jpg", "png"]


def test_normalize_extensions_accepts_list() -> None:
    """A stored list is normalized the same way as a string."""
    assert _normalize_extensions([".TMP", "log", "tmp"]) == ["log", "tmp"]


def test_normalize_extensions_empty_becomes_none() -> None:
    """Input that yields no usable extensions collapses to ``None``."""
    assert _normalize_extensions(" , . ,") is None


def test_normalize_extensions_rejects_wrong_type() -> None:
    """A value that is neither string, list, tuple, nor ``None`` is rejected."""
    with pytest.raises(ConfigError):
        _normalize_extensions(5)


def test_normalize_extensions_rejects_non_string_member() -> None:
    """A list with a non-string member is rejected rather than coerced."""
    with pytest.raises(ConfigError):
        _normalize_extensions(["ok", 7])


# ---------------------------------------------------------------------------
# _clean_field
# ---------------------------------------------------------------------------


def test_clean_field_none_is_dropped() -> None:
    """A ``None`` value normalizes to ``None`` for any field."""
    assert _clean_field("algorithm", None) is None


def test_clean_field_accepts_known_choices() -> None:
    """Mode, algorithm, and format pass when within their allowed set."""
    assert _clean_field("mode", "blacklist") == "blacklist"
    assert _clean_field("algorithm", "sha256") == "sha256"
    assert _clean_field("format", "csv") == "csv"


@pytest.mark.parametrize(
    ("key", "value"),
    [("mode", "sideways"), ("algorithm", "rot13"), ("format", "yaml")],
)
def test_clean_field_rejects_unknown_choice(key: str, value: str) -> None:
    """A value outside the allowed set raises with the field named."""
    with pytest.raises(ConfigError, match=key):
        _clean_field(key, value)


def test_clean_field_workers_requires_positive_int() -> None:
    """Workers must be an integer of at least one; bools and floats are rejected."""
    assert _clean_field("workers", 4) == 4
    for bad in (0, -1, True, "4", 1.5):
        with pytest.raises(ConfigError):
            _clean_field("workers", bad)


def test_clean_field_output_requires_string() -> None:
    """Output is kept verbatim when a string, blanked to ``None`` when empty."""
    assert _clean_field("output", "out.parquet") == "out.parquet"
    assert _clean_field("output", "") is None
    with pytest.raises(ConfigError):
        _clean_field("output", 3)


# ---------------------------------------------------------------------------
# _clean_profile
# ---------------------------------------------------------------------------


def test_clean_profile_drops_unknown_keys() -> None:
    """Keys outside the profile schema are silently discarded."""
    cleaned = _clean_profile({"algorithm": "sha512", "rogue": "x"}, strict=True)
    assert cleaned == {"algorithm": "sha512"}


def test_clean_profile_omits_empty_fields() -> None:
    """Fields that normalize to ``None`` do not appear in the result."""
    cleaned = _clean_profile({"ext": " , ", "output": ""}, strict=True)
    assert cleaned == {}


def test_clean_profile_strict_raises_on_bad_field() -> None:
    """In strict mode an invalid known field aborts the whole profile."""
    with pytest.raises(ConfigError):
        _clean_profile({"workers": 0}, strict=True)


def test_clean_profile_lenient_drops_bad_field() -> None:
    """In lenient mode a bad field is dropped and the good ones survive."""
    cleaned = _clean_profile({"workers": 0, "algorithm": "sha256"}, strict=False)
    assert cleaned == {"algorithm": "sha256"}
