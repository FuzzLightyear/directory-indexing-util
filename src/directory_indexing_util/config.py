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
import sys
from pathlib import Path

_APP_DIR = "dirindex"
_PROFILES_FILENAME = "profiles.json"


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
