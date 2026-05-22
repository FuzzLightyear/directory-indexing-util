# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Integration tests covering the combined :func:`index_directory` workflow."""

from __future__ import annotations

from pathlib import Path

from directory_indexing_util import index_directory


def test_combined_scan_and_hash(tmp_path: Path) -> None:
    """``index_directory`` produces the extended three-column schema."""
    (tmp_path / "a.bin").write_bytes(b"alpha")
    (tmp_path / "b.bin").write_bytes(b"beta")

    df = index_directory(tmp_path)

    assert df.height == 2
    assert df.columns == ["file_name", "file_path", "file_hash"]
    assert all(h is not None for h in df.get_column("file_hash").to_list())


def test_include_filter_propagates(tmp_path: Path) -> None:
    """Extension filtering applies to the scan phase of the combined call."""
    (tmp_path / "keep.py").write_bytes(b"keep")
    (tmp_path / "drop.txt").write_bytes(b"drop")

    df = index_directory(tmp_path, include={"py"})

    assert df.height == 1
    assert df.get_column("file_name")[0] == "keep.py"


def test_workers_override_propagates(tmp_path: Path) -> None:
    """Explicit ``workers`` reaches the hashing phase."""
    (tmp_path / "a.bin").write_bytes(b"data")

    df = index_directory(tmp_path, workers=1)

    assert df.height == 1
    assert df.get_column("file_hash")[0] is not None


def test_empty_directory_returns_empty_extended_schema(tmp_path: Path) -> None:
    """``index_directory`` on an empty tree returns 0 rows with the full schema."""
    df = index_directory(tmp_path)
    assert df.height == 0
    assert df.columns == ["file_name", "file_path", "file_hash"]


def test_algorithm_override_propagates_to_hashing(tmp_path: Path) -> None:
    """The ``algorithm`` kwarg reaches the hash phase and changes digest length."""
    (tmp_path / "a.bin").write_bytes(b"x")

    sha256_df = index_directory(tmp_path, algorithm="sha256")
    sha512_df = index_directory(tmp_path, algorithm="sha512")

    assert len(sha256_df.get_column("file_hash")[0]) == 64
    assert len(sha512_df.get_column("file_hash")[0]) == 128
    assert sha256_df.get_column("file_hash")[0] != sha512_df.get_column("file_hash")[0]


def test_str_input_equivalent_to_path(tmp_path: Path) -> None:
    """``str`` and ``Path`` inputs return equal output."""
    (tmp_path / "a.bin").write_bytes(b"x")
    (tmp_path / "b.bin").write_bytes(b"y")

    df_path = index_directory(tmp_path).sort("file_name")
    df_str = index_directory(str(tmp_path)).sort("file_name")

    assert df_path.equals(df_str)


def test_combined_call_equals_separate_calls(tmp_path: Path) -> None:
    """``index_directory`` is exactly ``hash_dataframe(scan_directory(...))``."""
    from directory_indexing_util import hash_dataframe, scan_directory

    (tmp_path / "a.bin").write_bytes(b"alpha")
    (tmp_path / "b.bin").write_bytes(b"beta")

    combined = index_directory(tmp_path).sort("file_name")
    separate = hash_dataframe(scan_directory(tmp_path)).sort("file_name")

    assert combined.equals(separate)
