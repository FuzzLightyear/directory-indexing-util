# Copyright (c) 2025 Mercury. All rights reserved.
# SPDX-License-Identifier: MIT

"""Tests for :mod:`directory_indexing_util.scanner`."""

from __future__ import annotations

from pathlib import Path

import pytest

from directory_indexing_util import scan_directory


def test_empty_directory(tmp_path: Path) -> None:
    """An empty directory yields an empty DataFrame with the correct schema."""
    df = scan_directory(tmp_path)
    assert df.height == 0
    assert df.columns == ["file_name", "file_path"]


def test_multi_file(tmp_path: Path) -> None:
    """All regular files under *tmp_path* are enumerated."""
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.py").write_text("b")
    df = scan_directory(tmp_path)
    assert df.height == 2
    assert set(df.get_column("file_name").to_list()) == {"a.txt", "b.py"}


def test_nested_directories_traversed(tmp_path: Path) -> None:
    """The traversal recurses through subdirectories."""
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b")
    (tmp_path / "sub" / "deep").mkdir()
    (tmp_path / "sub" / "deep" / "c.txt").write_text("c")
    df = scan_directory(tmp_path)
    assert df.height == 3


def test_include_filter_whitelists_extensions(tmp_path: Path) -> None:
    """``include`` restricts the result to the listed extensions."""
    (tmp_path / "keep.py").write_text("a")
    (tmp_path / "drop.txt").write_text("b")
    df = scan_directory(tmp_path, include={"py"})
    assert df.height == 1
    assert df.get_column("file_name")[0] == "keep.py"


def test_accepts_str_path(tmp_path: Path) -> None:
    """``root`` may be a plain ``str`` as well as ``Path``."""
    (tmp_path / "a.txt").write_text("a")
    df = scan_directory(str(tmp_path))
    assert df.height == 1


def test_missing_directory_raises(tmp_path: Path) -> None:
    """A non-existent root raises :class:`FileNotFoundError`."""
    with pytest.raises(FileNotFoundError):
        scan_directory(tmp_path / "does-not-exist")


def test_file_path_raises(tmp_path: Path) -> None:
    """Passing a regular file (not a directory) raises NotADirectoryError."""
    f = tmp_path / "regular.txt"
    f.write_text("a")
    with pytest.raises(NotADirectoryError):
        scan_directory(f)
