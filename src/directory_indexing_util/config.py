# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Per-user configuration directory and the saved-profile store.

Stdlib only, by design.  This module resolves the OS-specific per-user
configuration directory and reads and writes the CLI's saved profiles: a
``settings.toml`` (the profiles directory and the default profile) and one TOML
file per profile.  It imports no third-party package, so loading it never pulls
in polars, rich, or loguru and the ``dirindex --help`` and ``dirindex
--version`` fast path is preserved.  It is imported only by the CLI handlers,
never at library import time, so using the package as a library has no
configuration side effects.

The configuration directory follows the platform convention:

- Windows: ``%APPDATA%\\dirindex``
- macOS: ``~/Library/Application Support/dirindex``
- other: ``$XDG_CONFIG_HOME/dirindex`` or ``~/.config/dirindex``

``$DIRINDEX_CONFIG_DIR`` overrides the configuration directory and
``$DIRINDEX_PROFILES_DIR`` overrides the profiles directory; the test suite uses
both to redirect storage to a temporary directory.  No path is ever derived from
the package install location, so the store works identically from a source
checkout, a pip install, or a uvx run.  Profile files are parsed with
:mod:`tomllib`, which executes no code, and validated against a closed schema, so
a hand-edited or hostile file cannot run code or crash a run.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import tomllib
from pathlib import Path

from directory_indexing_util._algorithms import ALGORITHMS
from directory_indexing_util.formats import _FORMATS

_APP_DIR = "dirindex"
_SETTINGS_FILENAME = "settings.toml"
_PROFILES_SUBDIR = "profiles"
_PROFILE_SUFFIX = ".toml"

_MODES = ("whitelist", "blacklist")
"""The two extension-filter modes a profile may record."""

_PROFILE_FIELDS = ("mode", "ext", "algorithm", "workers", "format")
_SETTINGS_KEYS = ("profiles_dir", "default_profile")
_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

_MAX_WORKERS = 1024
_MAX_PROFILE_BYTES = 64 * 1024
_MAX_PROFILES = 4096


class ConfigError(ValueError):
    """Raised when a profile name or field value fails validation."""


def _config_dir() -> Path:
    """Resolve the per-user configuration directory for the tool.

    Resolution order is the ``DIRINDEX_CONFIG_DIR`` override when set,
    otherwise the platform-native per-user configuration directory.  The
    directory is not created here; writers create it on demand.

    Returns
    -------
    Path
        Configuration directory.  May not exist yet.
    """
    override = os.environ.get("DIRINDEX_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(base) / _APP_DIR
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_DIR
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / _APP_DIR


def _require_name(name: str) -> str:
    """Validate a profile name and return it lowercased.

    Names are case-insensitive everywhere so behavior is identical on
    case-sensitive and case-folding filesystems.  The conservative character
    set keeps a name from ever being mistaken for a path: this is the
    anti-traversal guarantee, since the name becomes a filename component.

    Parameters
    ----------
    name : str
        Candidate profile name.

    Returns
    -------
    str
        The validated name, lowercased.

    Raises
    ------
    ConfigError
        If *name* is not a string of 1 to 64 characters drawn from letters,
        digits, dot, underscore, or hyphen, starting with a letter or digit.
    """
    if not isinstance(name, str) or _NAME_PATTERN.match(name) is None:
        raise ConfigError(
            f"Invalid profile name {name!r}: use 1 to 64 characters from letters, "
            "digits, dot, underscore, or hyphen, starting with a letter or digit."
        )
    return name.lower()


def _normalize_extensions(value: object) -> list[str] | None:
    """Normalize an extension filter into a sorted list of bare extensions.

    Accepts either a comma-separated string (the form the CLI uses) or a list
    of strings (the form stored in a profile).  Each token is stripped of
    surrounding whitespace and leading dots, lowercased, and dropped when
    empty.  This mirrors the CLI ``_parse_extensions`` rules so a profile and a
    command line produce the same filter.

    Parameters
    ----------
    value : object
        A ``str``, a list or tuple of ``str``, or ``None``.

    Returns
    -------
    list of str or None
        Sorted, de-duplicated extensions, or ``None`` when none remain.

    Raises
    ------
    ConfigError
        If *value* is not a string, a list or tuple of strings, or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, str):
        tokens: list[str] = value.split(",")
    elif isinstance(value, (list, tuple)) and all(isinstance(token, str) for token in value):
        tokens = list(value)
    else:
        raise ConfigError(f"Invalid extension list: {value!r}")
    cleaned = {token.strip().lstrip(".").lower() for token in tokens}
    cleaned.discard("")
    return sorted(cleaned) or None


def _clean_field(key: str, value: object) -> object | None:
    """Validate and normalize a single profile field.

    Parameters
    ----------
    key : str
        Field name, one of :data:`_PROFILE_FIELDS`.
    value : object
        Raw value as read from a TOML file or supplied by a caller.

    Returns
    -------
    object or None
        The normalized value, or ``None`` when the field carries no
        information and should be omitted from the stored profile.

    Raises
    ------
    ConfigError
        If *value* has the wrong type or falls outside the allowed set for
        *key*.
    """
    if value is None:
        return None
    if key == "ext":
        return _normalize_extensions(value)
    if key == "workers":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"Invalid workers {value!r}: expected an integer.")
        if not 1 <= value <= _MAX_WORKERS:
            raise ConfigError(f"Invalid workers {value!r}: expected 1 to {_MAX_WORKERS}.")
        return value
    choices = {"mode": _MODES, "algorithm": ALGORITHMS, "format": _FORMATS}[key]
    if value not in choices:
        raise ConfigError(f"Invalid {key} {value!r}: expected one of {', '.join(choices)}.")
    return value


def _clean_profile(fields: dict[str, object], *, strict: bool) -> dict[str, object]:
    """Validate a profile's fields, discarding unknown keys.

    Parameters
    ----------
    fields : dict
        Raw field mapping for a single profile (as parsed from TOML).
    strict : bool
        When ``True`` an invalid known field raises; when ``False`` the
        offending field is dropped so one corrupt entry never breaks loading.

    Returns
    -------
    dict
        The cleaned profile, holding only known fields that carry a value.
        Unknown keys are always discarded.

    Raises
    ------
    ConfigError
        If *strict* is ``True`` and a known field fails validation.
    """
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if key not in _PROFILE_FIELDS:
            continue
        try:
            normalized = _clean_field(key, value)
        except ConfigError:
            if strict:
                raise
            continue
        if normalized is not None:
            cleaned[key] = normalized
    return cleaned


def _toml_str(value: str) -> str:
    """Render *value* as a quoted TOML basic string.

    Escapes backslash, the double-quote delimiter, and control characters, so
    a value such as a Windows path (``C:\\Users\\...``) round-trips through
    :mod:`tomllib` instead of being mangled by stray escape sequences.

    Parameters
    ----------
    value : str
        String to encode.

    Returns
    -------
    str
        A double-quoted TOML basic string.
    """
    out: list[str] = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch < " " or ch == "\x7f":
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _emit_toml(fields: dict[str, object]) -> str:
    """Render a flat mapping as ``key = value`` TOML lines, sorted by key.

    Handles exactly the value types in the profile and settings schema:
    ``str``, ``int``, and ``list`` of ``str``.  Keys come from the closed
    schema and are bare-key safe.

    Parameters
    ----------
    fields : dict
        Validated, flat mapping to serialize.

    Returns
    -------
    str
        TOML text, empty when *fields* is empty.

    Raises
    ------
    ConfigError
        If a value is not a supported type.
    """
    lines: list[str] = []
    for key in sorted(fields):
        value = fields[key]
        if isinstance(value, bool):
            raise ConfigError(f"Cannot serialize a boolean for {key!r}.")
        if isinstance(value, int):
            lines.append(f"{key} = {value}")
        elif isinstance(value, str):
            lines.append(f"{key} = {_toml_str(value)}")
        elif isinstance(value, (list, tuple)):
            items = ", ".join(_toml_str(item) for item in value)
            lines.append(f"{key} = [{items}]")
        else:
            raise ConfigError(f"Cannot serialize {type(value).__name__} for {key!r}.")
    return "".join(f"{line}\n" for line in lines)


def _ensure_dir(path: Path) -> None:
    """Create *path* if needed, restricting it to the owner on POSIX."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(path, 0o700)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically.

    The payload goes to a temporary file in the same directory, is flushed to
    disk, then moved into place with :func:`os.replace`, so a reader never sees
    a half-written file.  On POSIX the temporary file is owner-only by virtue
    of :func:`tempfile.mkstemp`.

    Parameters
    ----------
    path : Path
        Destination file.  Its parent directory is created if missing.
    text : str
        Content to write (UTF-8, LF newlines).
    """
    _ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _settings_path() -> Path:
    """Return the settings file path inside :func:`_config_dir`."""
    return _config_dir() / _SETTINGS_FILENAME


def _read_settings() -> dict[str, object]:
    """Read the settings file, tolerant of a missing or corrupt file.

    Returns
    -------
    dict
        A mapping holding only the recognized keys: ``profiles_dir`` (a
        non-empty string) and ``default_profile`` (a validated name).  Anything
        else is dropped; a missing or unparseable file yields ``{}``.
    """
    try:
        raw = tomllib.loads(_settings_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    settings: dict[str, object] = {}
    profiles_dir = raw.get("profiles_dir")
    if isinstance(profiles_dir, str) and profiles_dir:
        settings["profiles_dir"] = profiles_dir
    default = raw.get("default_profile")
    if isinstance(default, str):
        try:
            settings["default_profile"] = _require_name(default)
        except ConfigError:
            pass
    return settings


def _write_settings(updates: dict[str, object]) -> None:
    """Merge *updates* into the settings file and write it atomically.

    A key whose value is ``None`` is removed.

    Parameters
    ----------
    updates : dict
        Settings keys to set or clear.
    """
    settings = _read_settings()
    for key, value in updates.items():
        if value is None:
            settings.pop(key, None)
        else:
            settings[key] = value
    _atomic_write_text(_settings_path(), _emit_toml(settings))


def _get_default() -> str | None:
    """Return the configured default profile name, or ``None``.

    The name is validated on read, so a hand-edited invalid value reads as
    ``None``.  Whether the profile still exists is the caller's concern; a
    deleted default is cleared by :func:`_delete_profile`.
    """
    default = _read_settings().get("default_profile")
    return default if isinstance(default, str) else None


def _set_default(name: str | None) -> None:
    """Set the default profile name, or clear it with ``None``.

    Parameters
    ----------
    name : str or None
        Profile name to mark as default (validated), or ``None`` to clear.
    """
    _write_settings({"default_profile": _require_name(name) if name is not None else None})


def _profiles_dir(override: str | None = None) -> Path:
    """Resolve the profiles directory.

    Resolution order, highest first: *override* (the ``--profiles-dir`` flag),
    ``$DIRINDEX_PROFILES_DIR``, the ``profiles_dir`` setting, then the
    ``profiles`` subdirectory of :func:`_config_dir`.

    Parameters
    ----------
    override : str or None
        A per-invocation directory, typically from the CLI.

    Returns
    -------
    Path
        Profiles directory.  May not exist yet.
    """
    if override:
        return Path(override).expanduser()
    env = os.environ.get("DIRINDEX_PROFILES_DIR")
    if env:
        return Path(env).expanduser()
    setting = _read_settings().get("profiles_dir")
    if isinstance(setting, str) and setting:
        return Path(setting).expanduser()
    return _config_dir() / _PROFILES_SUBDIR


def _set_profiles_dir(path: str | None) -> None:
    """Persist (or clear, with ``None``) the profiles directory setting.

    A given path is stored absolute and ``~``-expanded so later resolution is
    never relative to the working directory.

    Parameters
    ----------
    path : str or None
        Directory to remember, or ``None`` to fall back to the default.
    """
    if path is None:
        _write_settings({"profiles_dir": None})
        return
    _write_settings({"profiles_dir": str(Path(path).expanduser().resolve())})


def _iter_profile_files(profiles_dir: Path) -> list[tuple[str, Path]]:
    """Return ``(lowercased stem, path)`` for valid profile files.

    Skips non-``.toml`` entries, symlinks, non-regular files, and names that
    fail the profile-name pattern.  Reads names only, never contents, and
    considers at most :data:`_MAX_PROFILES` entries so a hostile directory
    cannot drive unbounded work.  Sorted for deterministic output.

    Parameters
    ----------
    profiles_dir : Path
        Directory to enumerate.

    Returns
    -------
    list of (str, Path)
        One entry per valid profile file.
    """
    results: list[tuple[str, Path]] = []
    try:
        scan = os.scandir(profiles_dir)
    except OSError:
        return results
    with scan:
        for entry in scan:
            if len(results) >= _MAX_PROFILES:
                break
            if not entry.name.endswith(_PROFILE_SUFFIX):
                continue
            stem = entry.name[: -len(_PROFILE_SUFFIX)]
            if _NAME_PATTERN.match(stem) is None:
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            results.append((stem.lower(), Path(entry.path)))
    results.sort()
    return results


def _list_profiles(profiles_dir: Path) -> list[str]:
    """Return the profile names in *profiles_dir*, lowercased, sorted, deduped."""
    return sorted({stem for stem, _ in _iter_profile_files(profiles_dir)})


def _resolve_profile_file(name: str, *, profiles_dir: Path) -> Path | None:
    """Return the file backing profile *name* (case-insensitive), or ``None``."""
    target = _require_name(name)
    for stem, path in _iter_profile_files(profiles_dir):
        if stem == target:
            return path
    return None


def _read_profile(path: Path, *, strict: bool) -> dict[str, object]:
    """Read and validate one profile file.

    Bounds the read at :data:`_MAX_PROFILE_BYTES`, decodes UTF-8 (tolerating a
    byte-order mark), parses with :mod:`tomllib` (no code execution), then
    validates the fields.

    Parameters
    ----------
    path : Path
        Profile file to read.
    strict : bool
        When ``True`` any problem raises; when ``False`` it yields ``{}``.

    Returns
    -------
    dict
        The cleaned profile fields.

    Raises
    ------
    ConfigError
        If *strict* and the file is oversized, unreadable, not valid TOML, or
        holds an invalid field.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read(_MAX_PROFILE_BYTES + 1)
    except OSError as exc:
        if strict:
            raise ConfigError(f"Cannot read profile {path.name}: {exc}") from exc
        return {}
    if len(data) > _MAX_PROFILE_BYTES:
        if strict:
            raise ConfigError(f"Profile {path.name} exceeds {_MAX_PROFILE_BYTES} bytes.")
        return {}
    try:
        raw = tomllib.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        if strict:
            raise ConfigError(f"Profile {path.name} is not valid TOML: {exc}") from exc
        return {}
    return _clean_profile(raw, strict=strict)


def _get_profile(name: str, *, profiles_dir: Path) -> dict[str, object]:
    """Return the validated fields of profile *name*.

    Parameters
    ----------
    name : str
        Profile to read.
    profiles_dir : Path
        Directory to look in.

    Returns
    -------
    dict
        The profile's validated fields.

    Raises
    ------
    KeyError
        If no profile named *name* exists.
    ConfigError
        If the profile file is invalid.
    """
    path = _resolve_profile_file(name, profiles_dir=profiles_dir)
    if path is None:
        raise KeyError(name)
    return _read_profile(path, strict=True)


def _save_profile(name: str, fields: dict[str, object], *, profiles_dir: Path) -> None:
    """Validate and write profile *name* as a TOML file.

    The name and fields are validated before any write, so a rejected save
    leaves existing files untouched.  Writes to the canonical lowercase
    filename and removes any differently-cased file for the same name.

    Parameters
    ----------
    name : str
        Profile name (validated, lowercased).
    fields : dict
        Profile fields, validated strictly; unknown keys are dropped.
    profiles_dir : Path
        Directory to write into.

    Raises
    ------
    ConfigError
        If *name* or any known field is invalid.
    """
    target = _require_name(name)
    cleaned = _clean_profile(fields, strict=True)
    canonical = profiles_dir / f"{target}{_PROFILE_SUFFIX}"
    for stem, path in _iter_profile_files(profiles_dir):
        if stem == target and path != canonical:
            path.unlink(missing_ok=True)
    _atomic_write_text(canonical, _emit_toml(cleaned))


def _delete_profile(name: str, *, profiles_dir: Path) -> None:
    """Delete profile *name*, clearing the default if it pointed there.

    Parameters
    ----------
    name : str
        Profile to delete.
    profiles_dir : Path
        Directory to delete from.

    Raises
    ------
    KeyError
        If no profile named *name* exists.
    """
    target = _require_name(name)
    removed = False
    for stem, path in _iter_profile_files(profiles_dir):
        if stem == target:
            path.unlink(missing_ok=True)
            removed = True
    if not removed:
        raise KeyError(name)
    if _get_default() == target:
        _set_default(None)
