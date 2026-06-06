# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Tests for :mod:`directory_indexing_util.scanner`."""

from __future__ import annotations

import os
import sys
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


# ---------------------------------------------------------------------------
# Path-input edge cases
# ---------------------------------------------------------------------------


def test_root_with_trailing_separator_works(tmp_path: Path) -> None:
    """A root whose resolved string ends with ``os.sep`` (e.g., a filesystem root)
    must not trip the prefix-containment check — covers the bug previously fixed
    where ``"C:\\\\" + os.sep`` produced a prefix nothing could match."""
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b")

    sep_terminated = str(tmp_path.resolve()) + os.sep
    df = scan_directory(sep_terminated)

    assert df.height == 2


def test_path_and_str_inputs_produce_identical_output(tmp_path: Path) -> None:
    """``Path`` and ``str`` inputs return the same data, just constructed differently."""
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")

    df_path = scan_directory(tmp_path).sort("file_name")
    df_str = scan_directory(str(tmp_path)).sort("file_name")

    assert df_path.equals(df_str)


# ---------------------------------------------------------------------------
# Filename / extension extraction edge cases
# ---------------------------------------------------------------------------


def test_hidden_dotfile_treated_as_no_extension(tmp_path: Path) -> None:
    """``.gitignore`` and similar have no extension — ``include={""}`` matches them."""
    (tmp_path / ".gitignore").write_text("x")
    (tmp_path / "regular.py").write_text("x")

    df = scan_directory(tmp_path, include={""})

    assert df.height == 1
    assert df.get_column("file_name")[0] == ".gitignore"


def test_files_without_extension_match_empty_include(tmp_path: Path) -> None:
    """Files like ``Makefile`` (no dot at all) also have extension ``""``."""
    (tmp_path / "Makefile").write_text("x")
    (tmp_path / "config.toml").write_text("x")

    df = scan_directory(tmp_path, include={""})

    assert df.height == 1
    assert df.get_column("file_name")[0] == "Makefile"


def test_multi_dot_filename_uses_last_extension(tmp_path: Path) -> None:
    """``archive.tar.gz`` matches ``include={"gz"}``, not ``{"tar"}``."""
    (tmp_path / "archive.tar.gz").write_text("x")

    assert scan_directory(tmp_path, include={"gz"}).height == 1
    assert scan_directory(tmp_path, include={"tar"}).height == 0


# ---------------------------------------------------------------------------
# Include filter semantics
# ---------------------------------------------------------------------------


def test_empty_include_set_filters_everything(tmp_path: Path) -> None:
    """An empty set is *not* the same as None — it whitelists nothing."""
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.txt").write_text("x")

    df = scan_directory(tmp_path, include=set())

    assert df.height == 0


def test_include_none_keeps_every_file(tmp_path: Path) -> None:
    """``include=None`` (default) returns all files including dotfiles."""
    (tmp_path / "a.py").write_text("x")
    (tmp_path / ".hidden").write_text("x")

    df = scan_directory(tmp_path, include=None)

    assert df.height == 2


def test_include_with_multiple_extensions(tmp_path: Path) -> None:
    """Multiple extensions in the whitelist are all honoured."""
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    (tmp_path / "c.md").write_text("x")
    (tmp_path / "d.bin").write_text("x")

    df = scan_directory(tmp_path, include={"py", "md"})

    assert df.height == 2
    assert set(df.get_column("file_name").to_list()) == {"a.py", "c.md"}


# ---------------------------------------------------------------------------
# Output schema invariants
# ---------------------------------------------------------------------------


def test_schema_is_two_utf8_columns(tmp_path: Path) -> None:
    """Schema is exactly the documented contract: file_name (Utf8), file_path (Utf8)."""
    import polars as pl

    (tmp_path / "a.txt").write_text("x")

    df = scan_directory(tmp_path)

    assert df.schema == {"file_name": pl.Utf8, "file_path": pl.Utf8}


def test_resolved_paths_are_absolute(tmp_path: Path) -> None:
    """Every returned ``file_path`` is absolute (resolution canonicalises the entry)."""
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("x")

    df = scan_directory(tmp_path)

    for path in df.get_column("file_path").to_list():
        assert Path(path).is_absolute()


def test_file_name_is_basename_not_path(tmp_path: Path) -> None:
    """``file_name`` is the file's basename, never the path."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.txt").write_text("x")

    df = scan_directory(tmp_path)

    assert df.get_column("file_name").to_list() == ["deep.txt"]
    assert df.get_column("file_path")[0].endswith("deep.txt")
    assert os.sep in df.get_column("file_path")[0]


# ---------------------------------------------------------------------------
# Platform-aware: symlinks (POSIX) and junctions (Windows)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation requires admin on Windows")
def test_symlink_to_file_is_skipped(tmp_path: Path) -> None:
    """A symlink pointing at a regular file is not enumerated (POSIX)."""
    target = tmp_path / "target.txt"
    target.write_text("x")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    df = scan_directory(tmp_path)

    names = set(df.get_column("file_name").to_list())
    assert names == {"target.txt"}


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation requires admin on Windows")
def test_symlink_to_directory_is_not_traversed(tmp_path: Path) -> None:
    """A symlinked directory is skipped — its contents must not appear (POSIX)."""
    other = tmp_path / "other"
    other.mkdir()
    (other / "deep.txt").write_text("x")
    (tmp_path / "main.txt").write_text("x")

    linked = tmp_path / "linked_dir"
    linked.symlink_to(other, target_is_directory=True)

    df = scan_directory(tmp_path)

    names = set(df.get_column("file_name").to_list())
    assert names == {"main.txt", "deep.txt"}
    # deep.txt appears only via the real `other` directory, never via the symlink


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS junctions are Windows-only")
def test_junction_cycle_does_not_crash(tmp_path: Path) -> None:
    """A self-referential NTFS junction is entered once, not followed into a loop."""
    import subprocess

    (tmp_path / "a.txt").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("y")
    loop = sub / "loop"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(loop), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"could not create junction: {result.stderr.strip()}")

    df = scan_directory(tmp_path)  # must return without raising

    names = df.get_column("file_name").to_list()
    assert "a.txt" in names
    assert "b.txt" in names
    assert names.count("a.txt") == 1  # the cycle does not duplicate entries
