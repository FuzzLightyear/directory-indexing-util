# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Tests for :mod:`directory_indexing_util.hasher`."""

from __future__ import annotations

import hashlib
import sys
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


# ---------------------------------------------------------------------------
# Edge cases — empty inputs
# ---------------------------------------------------------------------------


def test_empty_dataframe_returns_empty_extended_schema() -> None:
    """A zero-row DataFrame is valid input and yields a zero-row result."""
    df = pl.DataFrame(
        {"file_name": [], "file_path": []},
        schema={"file_name": pl.Utf8, "file_path": pl.Utf8},
    )
    out = hash_dataframe(df)
    assert out.height == 0
    assert "file_hash" in out.columns


def test_empty_file_produces_known_sha256(tmp_path: Path) -> None:
    """A zero-byte file hashes to the canonical SHA-256 of empty input."""
    empty = tmp_path / "zero.bin"
    empty.write_bytes(b"")

    df = scan_directory(tmp_path)
    df = hash_dataframe(df)

    assert df.get_column("file_hash")[0] == hashlib.sha256(b"").hexdigest()
    assert df.get_column("file_hash")[0] == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


# ---------------------------------------------------------------------------
# Algorithm coverage — each curated choice produces the documented digest length
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("algorithm", "hex_length"),
    [
        ("sha256", 64),
        ("sha512", 128),
        ("blake2b", 128),
        ("md5", 32),
    ],
)
def test_each_supported_algorithm_produces_expected_hex_length(
    tmp_path: Path,
    algorithm: str,
    hex_length: int,
) -> None:
    """Every algorithm in :data:`ALGORITHMS` produces a digest of the right size."""
    (tmp_path / "f.bin").write_bytes(b"payload-for-algorithm-check")
    df = scan_directory(tmp_path)
    df = hash_dataframe(df, algorithm=algorithm)
    digest = df.get_column("file_hash")[0]
    assert digest is not None
    assert len(digest) == hex_length
    assert set(digest).issubset(set("0123456789abcdef"))


def test_algorithm_matches_hashlib_reference_for_each_choice(tmp_path: Path) -> None:
    """Each supported algorithm's digest equals a direct hashlib call."""
    content = b"reference-content-12345"
    (tmp_path / "f.bin").write_bytes(content)
    df = scan_directory(tmp_path)
    for algorithm in ("sha256", "sha512", "blake2b", "md5"):
        expected = hashlib.new(algorithm, content).hexdigest()
        actual = hash_dataframe(df, algorithm=algorithm).get_column("file_hash")[0]
        assert actual == expected, f"mismatch for {algorithm}"


# ---------------------------------------------------------------------------
# Order preservation
# ---------------------------------------------------------------------------


def test_hash_order_is_preserved(tmp_path: Path) -> None:
    """The appended ``file_hash`` column aligns row-for-row with input paths.

    ``ThreadPoolExecutor.map`` is documented to return results in submit
    order, but this test pins the behaviour explicitly so a future refactor
    to ``as_completed`` would be caught immediately.
    """
    for i in range(20):
        (tmp_path / f"file_{i:02d}.bin").write_bytes(f"content-{i}".encode())

    df = scan_directory(tmp_path).sort("file_name")
    df = hash_dataframe(df)

    for path, digest in zip(
        df.get_column("file_path").to_list(),
        df.get_column("file_hash").to_list(),
        strict=True,
    ):
        with open(path, "rb") as f:
            expected = hashlib.sha256(f.read()).hexdigest()
        assert digest == expected


# ---------------------------------------------------------------------------
# Workers parameter — boundary values
# ---------------------------------------------------------------------------


def test_workers_one_runs_sequentially(tmp_path: Path) -> None:
    """``workers=1`` is a valid degenerate pool (single thread)."""
    for i in range(5):
        (tmp_path / f"f{i}.bin").write_bytes(f"x{i}".encode())

    df = scan_directory(tmp_path)
    df = hash_dataframe(df, workers=1)

    assert df.height == 5
    assert df.get_column("file_hash").null_count() == 0


def test_workers_large_value_accepted(tmp_path: Path) -> None:
    """An over-large workers count is accepted; ThreadPoolExecutor caps internally."""
    (tmp_path / "f.bin").write_bytes(b"x")
    df = scan_directory(tmp_path)
    df = hash_dataframe(df, workers=128)
    assert df.get_column("file_hash")[0] is not None


def test_negative_workers_raises(tmp_path: Path) -> None:
    """Negative worker counts are rejected with a clear ValueError."""
    df = scan_directory(tmp_path)
    with pytest.raises(ValueError, match="workers"):
        hash_dataframe(df, workers=-1)


# ---------------------------------------------------------------------------
# Validation precedence
# ---------------------------------------------------------------------------


def test_algorithm_validation_runs_before_threading(tmp_path: Path) -> None:
    """Bad-algorithm rejection must happen before any pool work — fail fast."""
    for i in range(50):
        (tmp_path / f"f{i}.bin").write_bytes(b"x")

    df = scan_directory(tmp_path)

    with pytest.raises(ValueError, match="algorithm"):
        hash_dataframe(df, algorithm="not-real")


# ---------------------------------------------------------------------------
# Schema preservation
# ---------------------------------------------------------------------------


def test_existing_columns_are_preserved(tmp_path: Path) -> None:
    """Hashing extends the schema additively; pre-existing columns survive."""
    (tmp_path / "f.bin").write_bytes(b"x")

    df = scan_directory(tmp_path).with_columns(pl.lit("extra").alias("custom"))
    out = hash_dataframe(df)

    assert "custom" in out.columns
    assert out.get_column("custom").to_list() == ["extra"]
    assert "file_hash" in out.columns


def test_file_hash_column_is_utf8(tmp_path: Path) -> None:
    """``file_hash`` is always declared ``Utf8`` (nullable) per the spec."""
    (tmp_path / "f.bin").write_bytes(b"x")
    df = scan_directory(tmp_path)
    df = hash_dataframe(df)
    assert df.schema["file_hash"] == pl.Utf8


# ---------------------------------------------------------------------------
# Path safety — untrusted scan files (SEC-2)
# ---------------------------------------------------------------------------


def test_unc_path_is_skipped() -> None:
    """A UNC path is rejected without being opened, yielding ``None``.

    The check is a pure string test, so no network access occurs.
    """
    df = pl.DataFrame({"file_path": [r"\\203.0.113.1\share\secret"]})
    out = hash_dataframe(df)
    assert out.get_column("file_hash")[0] is None


def test_directory_path_yields_null(tmp_path: Path) -> None:
    """A path that is a directory, not a regular file, yields ``None``."""
    df = pl.DataFrame({"file_path": [str(tmp_path)]})
    out = hash_dataframe(df)
    assert out.get_column("file_hash")[0] is None


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation requires admin on Windows")
def test_symlink_path_is_not_followed(tmp_path: Path) -> None:
    """A symlink in the path column is skipped rather than followed (POSIX)."""
    target = tmp_path / "target.bin"
    target.write_bytes(b"x")
    link = tmp_path / "link.bin"
    link.symlink_to(target)
    df = pl.DataFrame({"file_path": [str(link)]})
    out = hash_dataframe(df)
    assert out.get_column("file_hash")[0] is None
