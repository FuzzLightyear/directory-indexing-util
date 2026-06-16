# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Unit tests for :mod:`directory_indexing_util.config`.

Every test runs with `$DIRINDEX_CONFIG_DIR` redirected to a temporary directory
(an autouse fixture), so settings and profile files are always read and written
inside the temp tree, never the real per-user configuration location.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from directory_indexing_util.config import (
    ConfigError,
    _clean_field,
    _clean_profile,
    _config_dir,
    _delete_profile,
    _emit_toml,
    _get_default,
    _get_profile,
    _list_profiles,
    _normalize_extensions,
    _profiles_dir,
    _read_profile,
    _require_name,
    _save_profile,
    _set_default,
    _set_profiles_dir,
    _toml_str,
)


@pytest.fixture(autouse=True)
def cfg(monkeypatch, tmp_path: Path) -> Path:
    """Redirect config and profile storage into a temp dir for every test."""
    monkeypatch.setenv("DIRINDEX_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DIRINDEX_PROFILES_DIR", raising=False)
    return tmp_path


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
# _require_name
# ---------------------------------------------------------------------------


def test_require_name_lowercases() -> None:
    """A valid name is returned lowercased, so names are case-insensitive."""
    assert _require_name("Photos") == "photos"


@pytest.mark.parametrize("bad", ["", "has space", "../etc", "a/b", ".hidden", "x" * 65])
def test_require_name_rejects_unsafe(bad: str) -> None:
    """Names that could traverse or look like a path are rejected."""
    with pytest.raises(ConfigError):
        _require_name(bad)


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


# ---------------------------------------------------------------------------
# _clean_field
# ---------------------------------------------------------------------------


def test_clean_field_accepts_known_choices() -> None:
    """Mode, algorithm, and format pass when within their allowed set."""
    assert _clean_field("mode", "blacklist") == "blacklist"
    assert _clean_field("algorithm", "blake3") == "blake3"
    assert _clean_field("format", "csv") == "csv"


@pytest.mark.parametrize(
    ("key", "value"),
    [("mode", "sideways"), ("algorithm", "rot13"), ("format", "yaml")],
)
def test_clean_field_rejects_unknown_choice(key: str, value: str) -> None:
    """A value outside the allowed set raises with the field named."""
    with pytest.raises(ConfigError, match=key):
        _clean_field(key, value)


def test_clean_field_workers_bounds() -> None:
    """Workers must be an integer from 1 to the cap; bools and floats reject."""
    assert _clean_field("workers", 1) == 1
    assert _clean_field("workers", 1024) == 1024
    for bad in (0, -1, 1025, True, "4", 1.5):
        with pytest.raises(ConfigError):
            _clean_field("workers", bad)


# ---------------------------------------------------------------------------
# _clean_profile
# ---------------------------------------------------------------------------


def test_clean_profile_drops_unknown_keys() -> None:
    """Keys outside the profile schema (including the dropped output) go away."""
    assert _clean_profile({"algorithm": "sha512", "output": "x"}, strict=True) == {
        "algorithm": "sha512"
    }


def test_clean_profile_strict_raises_on_bad_field() -> None:
    """In strict mode an invalid known field aborts the whole profile."""
    with pytest.raises(ConfigError):
        _clean_profile({"workers": 0}, strict=True)


def test_clean_profile_lenient_drops_bad_field() -> None:
    """In lenient mode a bad field is dropped and the good ones survive."""
    assert _clean_profile({"workers": 0, "algorithm": "sha256"}, strict=False) == {
        "algorithm": "sha256"
    }


# ---------------------------------------------------------------------------
# TOML emitter
# ---------------------------------------------------------------------------


def test_emit_toml_empty_is_blank() -> None:
    """An empty mapping renders to an empty string (a valid empty profile)."""
    assert _emit_toml({}) == ""


def test_toml_str_escapes_backslashes() -> None:
    """A Windows-style path survives the escaper and round-trips via tomllib."""
    raw = r"C:\Users\new\tab\profiles"
    assert tomllib.loads(f"p = {_toml_str(raw)}")["p"] == raw


def test_emit_toml_round_trips_through_tomllib() -> None:
    """A cleaned profile re-parses and re-cleans to itself (the store invariant)."""
    profile = _clean_profile(
        {
            "mode": "whitelist",
            "ext": ["png", "jpg"],
            "algorithm": "blake3",
            "workers": 8,
            "format": "csv",
        },
        strict=True,
    )
    assert _clean_profile(tomllib.loads(_emit_toml(profile)), strict=True) == profile


# ---------------------------------------------------------------------------
# Profiles directory resolution
# ---------------------------------------------------------------------------


def test_profiles_dir_default(cfg: Path) -> None:
    """With nothing set, profiles live under the config dir's ``profiles``."""
    assert _profiles_dir() == cfg / "profiles"


def test_profiles_dir_override_beats_everything(cfg: Path, tmp_path: Path, monkeypatch) -> None:
    """The per-invocation override wins over env and setting."""
    monkeypatch.setenv("DIRINDEX_PROFILES_DIR", str(tmp_path / "env"))
    _set_profiles_dir(str(tmp_path / "setting"))
    assert _profiles_dir(str(tmp_path / "flag")) == tmp_path / "flag"


def test_profiles_dir_env_beats_setting(cfg: Path, tmp_path: Path, monkeypatch) -> None:
    """``$DIRINDEX_PROFILES_DIR`` wins over the persisted setting."""
    monkeypatch.setenv("DIRINDEX_PROFILES_DIR", str(tmp_path / "env"))
    _set_profiles_dir(str(tmp_path / "setting"))
    assert _profiles_dir() == tmp_path / "env"


def test_profiles_dir_setting_round_trips(cfg: Path, tmp_path: Path) -> None:
    """A persisted profiles dir reads back, exercising the path round-trip."""
    target = tmp_path / "my-profiles"
    _set_profiles_dir(str(target))
    assert _profiles_dir() == target.resolve()


# ---------------------------------------------------------------------------
# Default profile
# ---------------------------------------------------------------------------


def test_default_unset_is_none(cfg: Path) -> None:
    """With no settings file the default profile reads as ``None``."""
    assert _get_default() is None


def test_default_round_trips_lowercased(cfg: Path) -> None:
    """A default is stored case-insensitively and read back lowercased."""
    _set_default("MAIN")
    assert _get_default() == "main"


def test_default_cleared_with_none(cfg: Path) -> None:
    """Passing ``None`` clears the default."""
    _set_default("main")
    _set_default(None)
    assert _get_default() is None


def test_read_settings_drops_invalid_default(cfg: Path) -> None:
    """A hand-edited invalid default name reads as ``None``."""
    _config_dir().mkdir(parents=True, exist_ok=True)
    (_config_dir() / "settings.toml").write_text('default_profile = "bad name"\n', encoding="utf-8")
    assert _get_default() is None


# ---------------------------------------------------------------------------
# Profile CRUD (via the autouse temp config dir)
# ---------------------------------------------------------------------------


def test_save_profile_round_trips(cfg: Path) -> None:
    """A saved profile reads back with its fields normalized."""
    pdir = _profiles_dir()
    _save_profile(
        "photos", {"mode": "whitelist", "ext": ".JPG, png", "workers": 8}, profiles_dir=pdir
    )
    assert _get_profile("photos", profiles_dir=pdir) == {
        "mode": "whitelist",
        "ext": ["jpg", "png"],
        "workers": 8,
    }


def test_saved_file_is_valid_toml(cfg: Path) -> None:
    """The on-disk profile is valid TOML with the canonical lowercase name."""
    pdir = _profiles_dir()
    _save_profile("base", {"algorithm": "sha512"}, profiles_dir=pdir)
    assert tomllib.loads((pdir / "base.toml").read_text(encoding="utf-8")) == {
        "algorithm": "sha512"
    }


def test_save_drops_unknown_keys(cfg: Path) -> None:
    """Unknown keys never reach the stored profile."""
    pdir = _profiles_dir()
    _save_profile("p", {"algorithm": "sha256", "rogue": "x"}, profiles_dir=pdir)
    assert _get_profile("p", profiles_dir=pdir) == {"algorithm": "sha256"}


def test_save_rejects_bad_name_without_writing(cfg: Path) -> None:
    """An unsafe name is refused and nothing is written."""
    pdir = _profiles_dir()
    with pytest.raises(ConfigError):
        _save_profile("has space", {"algorithm": "sha256"}, profiles_dir=pdir)
    assert not pdir.exists() or list(pdir.glob("*.toml")) == []


def test_save_rejects_bad_field_without_writing(cfg: Path) -> None:
    """A strict validation failure leaves the store untouched."""
    pdir = _profiles_dir()
    with pytest.raises(ConfigError):
        _save_profile("p", {"workers": 0}, profiles_dir=pdir)
    assert not (pdir / "p.toml").exists()


def test_list_profiles_sorted_and_lowercased(cfg: Path) -> None:
    """Names come back sorted, lowercased, and de-duplicated."""
    pdir = _profiles_dir()
    for name in ("Charlie", "alpha", "bravo"):
        _save_profile(name, {"algorithm": "sha256"}, profiles_dir=pdir)
    assert _list_profiles(pdir) == ["alpha", "bravo", "charlie"]


def test_get_missing_raises(cfg: Path) -> None:
    """Reading an absent profile raises ``KeyError``."""
    with pytest.raises(KeyError):
        _get_profile("nope", profiles_dir=_profiles_dir())


def test_delete_removes_and_clears_default(cfg: Path) -> None:
    """Deleting a profile removes it and clears it as the default."""
    pdir = _profiles_dir()
    _save_profile("main", {"algorithm": "sha256"}, profiles_dir=pdir)
    _set_default("main")
    _delete_profile("main", profiles_dir=pdir)
    assert _list_profiles(pdir) == []
    assert _get_default() is None
    with pytest.raises(KeyError):
        _get_profile("main", profiles_dir=pdir)


def test_delete_missing_raises(cfg: Path) -> None:
    """Deleting an absent profile raises ``KeyError``."""
    with pytest.raises(KeyError):
        _delete_profile("ghost", profiles_dir=_profiles_dir())


# ---------------------------------------------------------------------------
# Case-insensitive names
# ---------------------------------------------------------------------------


def test_save_and_get_are_case_insensitive(cfg: Path) -> None:
    """``Photos`` saves to the canonical lowercase file and reads under any case."""
    pdir = _profiles_dir()
    _save_profile("Photos", {"algorithm": "blake3"}, profiles_dir=pdir)
    assert (pdir / "photos.toml").is_file()
    assert _get_profile("PHOTOS", profiles_dir=pdir) == {"algorithm": "blake3"}
    assert _list_profiles(pdir) == ["photos"]


def test_hand_authored_uppercase_file_is_found(cfg: Path) -> None:
    """A hand-authored ``Backups.toml`` is found by ``backups`` on any platform."""
    pdir = _profiles_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "Backups.toml").write_text('algorithm = "md5"\n', encoding="utf-8")
    assert _list_profiles(pdir) == ["backups"]
    assert _get_profile("backups", profiles_dir=pdir) == {"algorithm": "md5"}


# ---------------------------------------------------------------------------
# Security: untrusted / hand-edited files
# ---------------------------------------------------------------------------


def test_oversized_profile_rejected(cfg: Path) -> None:
    """A file beyond the size cap is rejected before parsing."""
    pdir = _profiles_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    big = pdir / "big.toml"
    big.write_text('x = "' + "a" * (64 * 1024) + '"\n', encoding="utf-8")
    assert _read_profile(big, strict=False) == {}
    with pytest.raises(ConfigError):
        _get_profile("big", profiles_dir=pdir)


def test_list_skips_non_profile_and_bad_names(cfg: Path) -> None:
    """Non-``.toml`` files and unsafe stems are skipped during enumeration."""
    pdir = _profiles_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "good.toml").write_text("", encoding="utf-8")
    (pdir / "notes.txt").write_text("hi", encoding="utf-8")
    (pdir / "bad name.toml").write_text("", encoding="utf-8")
    assert _list_profiles(pdir) == ["good"]


def test_read_profile_tolerates_utf8_bom(cfg: Path) -> None:
    """A file saved with a UTF-8 byte-order mark still parses."""
    pdir = _profiles_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "bom.toml").write_bytes(b"\xef\xbb\xbf" + b'algorithm = "sha512"\n')
    assert _get_profile("bom", profiles_dir=pdir) == {"algorithm": "sha512"}


def test_empty_profile_is_valid_and_empty(cfg: Path) -> None:
    """A zero-byte profile is a valid no-op preset."""
    pdir = _profiles_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "empty.toml").write_text("", encoding="utf-8")
    assert _get_profile("empty", profiles_dir=pdir) == {}


def test_corrupt_profile_lists_but_fails_to_load(cfg: Path) -> None:
    """A corrupt file appears in the listing (names only) but errors on load."""
    pdir = _profiles_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "broken.toml").write_text("this is = = not toml", encoding="utf-8")
    assert "broken" in _list_profiles(pdir)
    with pytest.raises(ConfigError):
        _get_profile("broken", profiles_dir=pdir)


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks")
def test_symlinked_profile_is_ignored(cfg: Path, tmp_path: Path) -> None:
    """A symlink in the profiles directory is never listed or loaded."""
    pdir = _profiles_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    real = tmp_path / "real.toml"
    real.write_text('algorithm = "sha256"\n', encoding="utf-8")
    (pdir / "linked.toml").symlink_to(real)
    assert _list_profiles(pdir) == []
    with pytest.raises(KeyError):
        _get_profile("linked", profiles_dir=pdir)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_written_files_are_owner_only(cfg: Path) -> None:
    """On POSIX the settings and profile files are 0o600 in a 0o700 dir."""
    pdir = _profiles_dir()
    _save_profile("main", {"algorithm": "sha256"}, profiles_dir=pdir)
    _set_default("main")
    assert (pdir / "main.toml").stat().st_mode & 0o777 == 0o600
    assert (_config_dir() / "settings.toml").stat().st_mode & 0o777 == 0o600
    assert pdir.stat().st_mode & 0o777 == 0o700


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
