# Copyright (c) 2025 Mercury. All rights reserved.
# SPDX-License-Identifier: MIT

"""Tests for :mod:`directory_indexing_util.hasher`."""

from __future__ import annotations

import hashlib
from pathlib import Path

import polars as pl
import pytest

from directory_indexing_util import hash_dataframe, scan_directory


def test_hash_matches_hashlib_sha256(tmp_path: Path) -> None:
    """Computed hashes match a direct ``hashlib.sha256`` of the same bytes."""
    content = b"directory-indexing-util reference content"
    (tmp_path / "f.bin").write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()

    df = scan_directory(tmp_path)
    df = hash_dataframe(df)

    assert df.get_column("file_hash")[0] == expected


def test_different_algorithms_produce_different_digests(tmp_path: Path) -> None:
    """SHA-256 and SHA-512 produce distinct digests of the documented lengths."""
    (tmp_path / "f.bin").write_bytes(b"payload")
    df = scan_directory(tmp_path)

    sha256_hash = hash_dataframe(df, algorithm="sha256").get_column("file_hash")[0]
    sha512_hash = hash_dataframe(df, algorithm="sha512").get_column("file_hash")[0]

    assert sha256_hash != sha512_hash
    assert len(sha256_hash) == 64
    assert len(sha512_hash) == 128


def test_missing_file_path_column_raises() -> None:
    """The ``file_path`` column is required for hashing."""
    df = pl.DataFrame({"name": ["x"]})
    with pytest.raises(ValueError, match="file_path"):
        hash_dataframe(df)


def test_invalid_algorithm_raises(tmp_path: Path) -> None:
    """Unsupported algorithms are rejected with a clear ValueError."""
    df = scan_directory(tmp_path)
    with pytest.raises(ValueError, match="algorithm"):
        hash_dataframe(df, algorithm="not-a-real-hash")


def test_invalid_workers_raises(tmp_path: Path) -> None:
    """Worker count must be a positive integer when explicitly supplied."""
    df = scan_directory(tmp_path)
    with pytest.raises(ValueError, match="workers"):
        hash_dataframe(df, workers=0)


def test_unreadable_path_yields_null(tmp_path: Path) -> None:
    """Files that cannot be opened produce ``None`` rather than raising."""
    df = pl.DataFrame({"file_path": [str(tmp_path / "absent.bin")]})
    df = hash_dataframe(df)
    assert df.get_column("file_hash")[0] is None


def test_explicit_workers_count_accepted(tmp_path: Path) -> None:
    """An explicit ``workers`` count is honoured without altering results."""
    (tmp_path / "f.bin").write_bytes(b"x")
    df = scan_directory(tmp_path)
    df = hash_dataframe(df, workers=2)
    assert df.get_column("file_hash")[0] is not None
    assert len(df.get_column("file_hash")[0]) == 64
