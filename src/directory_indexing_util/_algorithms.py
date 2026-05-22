# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Hash algorithm constants.

Isolated in a stdlib-only module so importing the algorithm choices does not
transitively load polars or any other heavy dependency.  This is what allows
``dirindex --version`` and ``dirindex --help`` — both of which need
:data:`ALGORITHMS` to construct the argparse choices but no actual hashing
machinery — to return without paying the cost of loading ``hasher`` and its
``polars`` import.
"""

from __future__ import annotations

ALGORITHMS: tuple[str, ...] = ("sha256", "sha512", "blake2b", "md5")
"""Curated set of hash algorithms exposed by the CLI and library.

Limited to algorithms supported by :func:`hashlib.file_digest` that are either
modern integrity standards (``sha256``, ``sha512``), the fastest in-stdlib
option (``blake2b``), or available for legacy interoperability (``md5``).
"""

DEFAULT_ALGORITHM: str = "sha256"
"""Default algorithm — universal integrity standard, ~2.4 GB/s in benchmarks."""
