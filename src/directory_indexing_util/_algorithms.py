# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Hash algorithm constants.

Isolated in a stdlib-only module so importing the algorithm choices does not
transitively load polars or any other heavy dependency.  This is what allows
``dirindex --version`` and ``dirindex --help`` (both of which need
:data:`ALGORITHMS` to construct the argparse choices but no actual hashing
machinery) to return without paying the cost of loading ``hasher`` and its
``polars`` import.
"""

from __future__ import annotations

ALGORITHMS: tuple[str, ...] = ("sha256", "sha512", "blake2b", "md5", "blake3")
"""Recognized hash algorithm names exposed by the CLI and library.

The stdlib options are modern integrity standards (``sha256``, ``sha512``), the
fastest in-stdlib choice (``blake2b``), and ``md5`` for legacy interoperability.
``blake3`` is a faster non-stdlib option that stays optional, yet it is always a
recognized name so a saved profile or CLI flag is portable across installs.
Whether the ``blake3`` backend is actually installed is checked at hash time in
:func:`directory_indexing_util.hasher.hash_dataframe`, where a missing package
yields a clear "install the blake3 extra" error rather than a load-time or
argument-parse failure.
"""

DEFAULT_ALGORITHM: str = "sha256"
"""Default algorithm: universal integrity standard, ~2.4 GB/s in benchmarks."""
