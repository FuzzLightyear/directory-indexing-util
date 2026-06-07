# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Per-user configuration directory and saved-profile store.

Stdlib only, by design.  This module resolves the OS-specific per-user
configuration directory and reads and writes the interactive shell's saved
profiles.  It imports no third-party package, so loading it never pulls in
polars, rich, loguru, or cmd2 and the ``dirindex --help`` and
``dirindex --version`` fast path is preserved.

The configuration directory follows the platform convention:

- Windows: ``%APPDATA%\\dirindex``
- macOS: ``~/Library/Application Support/dirindex``
- other: ``$XDG_CONFIG_HOME/dirindex`` or ``~/.config/dirindex``

The ``DIRINDEX_CONFIG_DIR`` environment variable overrides the resolved
location, which is how the test suite redirects storage to a temporary
directory.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from directory_indexing_util._algorithms import ALGORITHMS
from directory_indexing_util.formats import _FORMATS

_APP_DIR = "dirindex"
_PROFILES_FILENAME = "profiles.json"

_MODES = ("whitelist", "blacklist")
"""The two extension-filter modes a profile may record."""

_PROFILE_FIELDS = ("mode", "ext", "algorithm", "workers", "format", "output")
_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


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


def _profiles_path() -> Path:
    """Return the path to the profiles file inside :func:`_config_dir`.

    Returns
    -------
    Path
        The ``profiles.json`` path under the resolved configuration
        directory.  May not exist yet.
    """
    return _config_dir() / _PROFILES_FILENAME


def _require_name(name: str) -> str:
    """Validate a profile name and return it unchanged.

    Names are dictionary keys, never path components, but they are held to a
    conservative character set so the stored file stays predictable and a name
    can never be mistaken for a path.

    Parameters
    ----------
    name : str
        Candidate profile name.

    Returns
    -------
    str
        The validated name.

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
    return name


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
        Raw value as read from JSON or supplied by a caller.

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
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ConfigError(f"Invalid workers {value!r}: expected an integer >= 1.")
        return value
    if key == "output":
        if not isinstance(value, str):
            raise ConfigError(f"Invalid output {value!r}: expected a path string.")
        return value or None
    choices = {"mode": _MODES, "algorithm": ALGORITHMS, "format": _FORMATS}[key]
    if value not in choices:
        raise ConfigError(f"Invalid {key} {value!r}: expected one of {', '.join(choices)}.")
    return value


def _clean_profile(fields: dict[str, object], *, strict: bool) -> dict[str, object]:
    """Validate a profile's fields, discarding unknown keys.

    Parameters
    ----------
    fields : dict
        Raw field mapping for a single profile.
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
