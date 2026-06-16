# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""End-to-end tests for the ``dirindex`` CLI invoked via subprocess.

Library-level tests in ``test_scanner.py`` / ``test_hasher.py`` /
``test_index.py`` cover the Python API.  These tests cover the CLI
itself — argument parsing, output-path resolution, format inference,
and the sidecar manifest — by spawning the real entry point and
inspecting its stdout/stderr/exit code and the files it writes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import polars as pl
import pytest

from directory_indexing_util import __version__

_CLI = (sys.executable, "-m", "directory_indexing_util")


def _run(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run the CLI and return the completed process.

    Parameters
    ----------
    *args : str
        Arguments to pass after the module invocation.
    cwd : Path, optional
        Working directory for the subprocess.
    check : bool, default ``True``
        Raise ``CalledProcessError`` on non-zero exit.

    Returns
    -------
    subprocess.CompletedProcess
        Result with captured stdout / stderr / returncode.
    """
    return subprocess.run(
        [*_CLI, *args],
        capture_output=True,
        text=True,
        check=check,
        cwd=cwd,
    )


def test_version_flag_long() -> None:
    """``--version`` prints ``dirindex <version>`` and exits 0."""
    result = _run("--version")
    assert result.returncode == 0
    assert "dirindex" in result.stdout
    assert __version__ in result.stdout


def test_version_flag_short() -> None:
    """``-V`` is the short form for ``--version``."""
    result = _run("-V")
    assert result.returncode == 0
    assert __version__ in result.stdout


def test_version_does_not_print_to_stderr() -> None:
    """``--version`` writes only to stdout; stderr stays empty."""
    result = _run("--version")
    assert result.stderr == ""


def test_index_manifest_reports_zero_failed_when_all_readable(tmp_path: Path) -> None:
    """``failed_count`` is ``0`` when every file in the scan hashes successfully."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.bin").write_bytes(b"alpha")
    (src / "b.bin").write_bytes(b"beta")

    out = tmp_path / "index.parquet"
    _run("index", str(src), "-o", str(out))

    manifest = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert manifest["file_count"] == 2
    assert manifest["failed_count"] == 0


def test_hash_manifest_reports_unreadable_failures(tmp_path: Path) -> None:
    """``failed_count`` counts rows whose ``file_hash`` came back ``null``.

    The scan input is a hand-built parquet referencing one real file and
    one non-existent path; hashing the non-existent path returns ``None``,
    so the manifest's ``failed_count`` must report exactly one failure.
    """
    real = tmp_path / "real.bin"
    real.write_bytes(b"payload")
    ghost = tmp_path / "ghost.bin"

    scan_path = tmp_path / "scan.parquet"
    pl.DataFrame(
        {
            "file_name": ["real.bin", "ghost.bin"],
            "file_path": [str(real), str(ghost)],
        }
    ).write_parquet(scan_path)

    out = tmp_path / "hashed.parquet"
    _run("hash", str(scan_path), "-o", str(out))

    manifest = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert manifest["file_count"] == 2
    assert manifest["failed_count"] == 1

    hashed = pl.read_parquet(out)
    nulls = hashed.get_column("file_hash").is_null().to_list()
    assert nulls == [False, True]


def test_index_summary_flags_unreadable_count(tmp_path: Path) -> None:
    """When some files fail, the stdout summary surfaces the failure count.

    Uses a scan input with a non-existent path to force one failure, so
    the CLI prints the ``(N unreadable)`` annotation.  Bypasses scan and
    feeds the synthetic scan file directly to ``hash``.
    """
    real = tmp_path / "real.bin"
    real.write_bytes(b"x")
    scan_path = tmp_path / "scan.parquet"
    pl.DataFrame(
        {
            "file_name": ["real.bin", "missing.bin"],
            "file_path": [str(real), str(tmp_path / "missing.bin")],
        }
    ).write_parquet(scan_path)

    out = tmp_path / "hashed.parquet"
    result = _run("hash", str(scan_path), "-o", str(out))
    assert "1 unreadable" in result.stdout


# ---------------------------------------------------------------------------
# scan subcommand
# ---------------------------------------------------------------------------


def test_scan_writes_parquet_with_documented_schema(tmp_path: Path) -> None:
    """``dirindex scan`` produces the two-column scan output spec."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.txt").write_text("a")
    (src / "b.txt").write_text("b")

    out = tmp_path / "scan.parquet"
    _run("scan", str(src), "-o", str(out))

    df = pl.read_parquet(out)
    assert df.height == 2
    assert df.columns == ["file_name", "file_path"]


def test_scan_with_include_filter_via_cli(tmp_path: Path) -> None:
    """``-i py`` whitelists only .py extensions; behaviour parallels the library API."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "keep.py").write_text("a")
    (src / "drop.txt").write_text("b")

    out = tmp_path / "scan.parquet"
    _run("scan", str(src), "-o", str(out), "-i", "py")

    df = pl.read_parquet(out)
    assert df.height == 1
    assert df.get_column("file_name")[0] == "keep.py"


def test_scan_format_inferred_from_extension(tmp_path: Path) -> None:
    """``-o output.csv`` infers CSV without needing ``-f csv``."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.txt").write_text("a")

    out = tmp_path / "out.csv"
    _run("scan", str(src), "-o", str(out))

    assert out.exists()
    df = pl.read_csv(out)
    assert df.height == 1


def test_scan_to_directory_creates_timestamped_file(tmp_path: Path) -> None:
    """When ``-o`` is a directory, a timestamped ``scan_*.parquet`` is written inside."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.txt").write_text("a")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _run("scan", str(src), "-o", str(out_dir))

    files = list(out_dir.iterdir())
    assert len(files) == 1
    assert files[0].name.startswith("scan_")
    assert files[0].suffix == ".parquet"


def test_scan_missing_directory_exits_nonzero(tmp_path: Path) -> None:
    """A non-existent source directory fails fast with exit code 1."""
    result = _run("scan", str(tmp_path / "nope"), check=False)
    assert result.returncode == 1


def test_scan_file_argument_exits_nonzero(tmp_path: Path) -> None:
    """Passing a file instead of a directory fails fast with exit code 1."""
    f = tmp_path / "file.txt"
    f.write_text("x")
    result = _run("scan", str(f), check=False)
    assert result.returncode == 1


# ---------------------------------------------------------------------------
# hash subcommand
# ---------------------------------------------------------------------------


def test_hash_round_trip_after_scan(tmp_path: Path) -> None:
    """End-to-end: scan → hash file via subprocess → verify schema extends scan."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.bin").write_bytes(b"alpha")

    scan_out = tmp_path / "scan.parquet"
    _run("scan", str(src), "-o", str(scan_out))

    hash_out = tmp_path / "hash.parquet"
    _run("hash", str(scan_out), "-o", str(hash_out))

    df = pl.read_parquet(hash_out)
    assert df.columns == ["file_name", "file_path", "file_hash"]
    assert df.get_column("file_hash")[0] is not None


def test_hash_missing_file_path_column_fails(tmp_path: Path) -> None:
    """An input file without ``file_path`` is rejected with exit code 1."""
    bad = tmp_path / "bad.parquet"
    pl.DataFrame({"file_name": ["x"], "other": ["y"]}).write_parquet(bad)

    out = tmp_path / "hash.parquet"
    result = _run("hash", str(bad), "-o", str(out), check=False)
    assert result.returncode == 1
    assert "file_path" in result.stderr


def test_hash_missing_input_file_fails(tmp_path: Path) -> None:
    """A non-existent input file fails fast with exit code 1."""
    result = _run("hash", str(tmp_path / "nope.parquet"), check=False)
    assert result.returncode == 1


@pytest.mark.parametrize("algorithm", ["sha256", "sha512", "blake2b", "md5"])
def test_hash_with_each_algorithm(tmp_path: Path, algorithm: str) -> None:
    """The ``-a`` flag exercises each supported algorithm end-to-end."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.bin").write_bytes(b"x")

    scan_out = tmp_path / "scan.parquet"
    _run("scan", str(src), "-o", str(scan_out))

    hash_out = tmp_path / "hash.parquet"
    _run("hash", str(scan_out), "-o", str(hash_out), "-a", algorithm)

    manifest = json.loads(hash_out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert manifest["hash_algorithm"] == algorithm


def test_hash_unsupported_input_format_fails(tmp_path: Path) -> None:
    """An input with an unrecognised extension fails with exit code 1."""
    bad = tmp_path / "data.bogus"
    bad.write_text("not anything")

    result = _run("hash", str(bad), check=False)
    assert result.returncode == 1


def test_hash_explicit_workers_flag_works(tmp_path: Path) -> None:
    """``-w 2`` is accepted and produces correct results."""
    src = tmp_path / "data"
    src.mkdir()
    for i in range(5):
        (src / f"f{i}.bin").write_bytes(b"x")

    scan_out = tmp_path / "scan.parquet"
    _run("scan", str(src), "-o", str(scan_out))

    hash_out = tmp_path / "hash.parquet"
    _run("hash", str(scan_out), "-o", str(hash_out), "-w", "2")

    df = pl.read_parquet(hash_out)
    assert df.height == 5
    assert df.get_column("file_hash").null_count() == 0


# ---------------------------------------------------------------------------
# index subcommand
# ---------------------------------------------------------------------------


def test_index_produces_full_schema(tmp_path: Path) -> None:
    """``dirindex index`` writes the full three-column schema in one pass."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.bin").write_bytes(b"alpha")
    (src / "b.bin").write_bytes(b"beta")

    out = tmp_path / "index.parquet"
    _run("index", str(src), "-o", str(out))

    df = pl.read_parquet(out)
    assert df.columns == ["file_name", "file_path", "file_hash"]
    assert df.height == 2


def test_index_with_all_options(tmp_path: Path) -> None:
    """``index`` with -i / -a / -w / -f / -o all wired correctly together."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "keep.py").write_bytes(b"x")
    (src / "drop.txt").write_bytes(b"x")

    out = tmp_path / "out.json"
    _run("index", str(src), "-o", str(out), "-i", "py", "-a", "sha512", "-w", "1", "-f", "json")

    assert out.exists()
    manifest = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert manifest["hash_algorithm"] == "sha512"
    assert manifest["file_count"] == 1


# ---------------------------------------------------------------------------
# Manifest contract
# ---------------------------------------------------------------------------


def test_manifest_has_all_documented_fields(tmp_path: Path) -> None:
    """Every documented manifest key is present and well-typed."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.bin").write_bytes(b"x")

    out = tmp_path / "index.parquet"
    _run("index", str(src), "-o", str(out))

    manifest = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    expected_keys = {
        "command",
        "input_path",
        "output_path",
        "hash_algorithm",
        "file_count",
        "failed_count",
        "created_at",
    }
    assert set(manifest.keys()) == expected_keys
    assert manifest["command"] == "index"
    assert isinstance(manifest["file_count"], int)
    assert isinstance(manifest["failed_count"], int)
    assert isinstance(manifest["created_at"], str)
    # ISO 8601 timestamps end with a timezone designator
    assert "+" in manifest["created_at"] or manifest["created_at"].endswith("Z")


def test_manifest_input_path_is_absolute(tmp_path: Path) -> None:
    """``input_path`` is recorded as an absolute path for unambiguous provenance."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.bin").write_bytes(b"x")

    out = tmp_path / "out.parquet"
    _run("index", str(src), "-o", str(out))

    manifest = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert Path(manifest["input_path"]).is_absolute()


def test_manifest_uses_utf8_and_lf(tmp_path: Path) -> None:
    """Manifest is byte-identical across platforms: UTF-8, LF line endings."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.bin").write_bytes(b"x")

    out = tmp_path / "out.parquet"
    _run("index", str(src), "-o", str(out))

    raw = out.with_suffix(".meta.json").read_bytes()
    # UTF-8 decodable
    raw.decode("utf-8")
    # No CRLF — write_text(newline="") preserved the json.dumps LF endings
    assert b"\r\n" not in raw


# ---------------------------------------------------------------------------
# Top-level CLI behaviour
# ---------------------------------------------------------------------------


def test_no_subcommand_prints_help_with_exit_zero() -> None:
    """Invoking ``dirindex`` with no subcommand prints help and exits 0."""
    result = _run(check=False)
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
    # All three subcommands are listed
    assert "scan" in result.stdout
    assert "hash" in result.stdout
    assert "index" in result.stdout


# ---------------------------------------------------------------------------
# Extension filters: include vs exclude
# ---------------------------------------------------------------------------


def test_scan_exclude_drops_extension(tmp_path: Path) -> None:
    """``scan -x`` excludes the listed extensions end-to-end."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "keep.py").write_text("a")
    (src / "drop.tmp").write_text("b")

    out = tmp_path / "scan.parquet"
    _run("scan", str(src), "-x", "tmp", "-o", str(out))

    names = set(pl.read_parquet(out).get_column("file_name").to_list())
    assert names == {"keep.py"}


def test_include_and_exclude_are_mutually_exclusive(tmp_path: Path) -> None:
    """Passing both -i and -x is rejected by argparse with exit code 2."""
    result = _run("scan", str(tmp_path), "-i", "py", "-x", "tmp", check=False)
    assert result.returncode == 2
    assert "not allowed with" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Profiles end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture
def profiles_env(monkeypatch, tmp_path: Path) -> Path:
    """Point the CLI's config and profiles at a temp dir (inherited by subprocesses)."""
    monkeypatch.setenv("DIRINDEX_CONFIG_DIR", str(tmp_path / "config"))
    profiles = tmp_path / "profiles"
    monkeypatch.setenv("DIRINDEX_PROFILES_DIR", str(profiles))
    return profiles


def test_save_then_apply_profile(profiles_env: Path, tmp_path: Path) -> None:
    """A profile saved from one run applies its algorithm and filter to another."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "keep.py").write_bytes(b"x")
    (src / "drop.txt").write_bytes(b"x")

    saved = _run(
        "index",
        str(src),
        "-i",
        "py",
        "-a",
        "sha512",
        "--save-profile",
        "code",
        "-o",
        str(tmp_path / "first.parquet"),
    )
    assert "Saved profile" in saved.stderr
    assert (profiles_env / "code.toml").is_file()

    out = tmp_path / "second.json"
    _run("index", str(src), "--profile", "code", "-f", "json", "-o", str(out))
    manifest = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert manifest["hash_algorithm"] == "sha512"
    assert manifest["file_count"] == 1


def test_explicit_flag_overrides_applied_profile(profiles_env: Path, tmp_path: Path) -> None:
    """An explicit ``-a`` on the run overrides the applied profile's algorithm."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.bin").write_bytes(b"x")

    _run(
        "index", str(src), "-a", "sha512", "--save-profile", "p", "-o", str(tmp_path / "a.parquet")
    )
    out = tmp_path / "b.parquet"
    _run("index", str(src), "--profile", "p", "-a", "md5", "-o", str(out))
    manifest = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert manifest["hash_algorithm"] == "md5"


def test_save_profile_reports_created_then_replaced(profiles_env: Path, tmp_path: Path) -> None:
    """The first ``--save-profile`` says Saved; a second one says Replaced."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.bin").write_bytes(b"x")

    first = _run(
        "index", str(src), "-a", "sha256", "--save-profile", "p", "-o", str(tmp_path / "1.parquet")
    )
    assert "Saved profile" in first.stderr
    second = _run(
        "index", str(src), "-a", "sha512", "--save-profile", "p", "-o", str(tmp_path / "2.parquet")
    )
    assert "Replaced profile" in second.stderr


def test_unknown_profile_exits_one(profiles_env: Path, tmp_path: Path) -> None:
    """``--profile`` naming nothing exits 1 with a clear message."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.bin").write_bytes(b"x")

    result = _run(
        "index", str(src), "--profile", "ghost", "-o", str(tmp_path / "x.parquet"), check=False
    )
    assert result.returncode == 1
    assert "No such profile" in result.stderr


# ---------------------------------------------------------------------------
# profile subcommand
# ---------------------------------------------------------------------------


def test_profile_save_show_list_delete(profiles_env: Path) -> None:
    """The save, list, show, delete cycle works and delete prints a recovery hint."""
    save = _run("profile", "save", "code", "-a", "sha512", "-i", "py", "-f", "json")
    assert "Saved profile" in save.stderr

    assert "code" in _run("profile", "list").stdout

    show = _run("profile", "show", "code")
    assert "-a sha512" in show.stdout
    assert "-i py" in show.stdout

    deleted = _run("profile", "delete", "code")
    assert "Recover with: dirindex profile save code" in deleted.stderr
    assert _run("profile", "list").stdout.strip() == ""


def test_profile_second_save_reports_replace(profiles_env: Path) -> None:
    """``save`` on an existing name reports Replaced, not Saved."""
    assert "Saved profile" in _run("profile", "save", "p", "-a", "sha256").stderr
    assert "Replaced profile" in _run("profile", "save", "p", "-a", "sha512").stderr


def test_profile_update_changes_one_field_keeping_rest(profiles_env: Path) -> None:
    """``update`` changes the named field and reports Updated, keeping the others."""
    _run("profile", "save", "p", "-a", "sha256", "-f", "csv", "-i", "py")
    updated = _run("profile", "update", "p", "-a", "blake3")
    assert "Updated profile" in updated.stderr
    shown = _run("profile", "show", "p").stdout
    assert "-a blake3" in shown
    assert "-f csv" in shown
    assert "-i py" in shown


def test_profile_update_missing_exits_one(profiles_env: Path) -> None:
    """``update`` on a profile that does not exist fails with exit code 1."""
    result = _run("profile", "update", "ghost", "-a", "sha256", check=False)
    assert result.returncode == 1


def test_profile_default_set_query_clear(profiles_env: Path) -> None:
    """A default can be set, queried, marked in the listing, and cleared."""
    _run("profile", "save", "p", "-a", "sha256")
    _run("profile", "default", "p")
    assert _run("profile", "default").stdout.strip() == "p"
    assert "(default)" in _run("profile", "list").stdout
    _run("profile", "default", "--clear")
    assert _run("profile", "default").stdout.strip() == "(none)"


def test_profile_default_unknown_exits_one(profiles_env: Path) -> None:
    """Defaulting to a profile that does not exist fails with exit code 1."""
    result = _run("profile", "default", "ghost", check=False)
    assert result.returncode == 1


def test_profile_delete_missing_exits_one(profiles_env: Path) -> None:
    """Deleting a profile that does not exist fails with exit code 1."""
    result = _run("profile", "delete", "ghost", check=False)
    assert result.returncode == 1


def test_profile_requires_an_action(profiles_env: Path) -> None:
    """``dirindex profile`` with no action is rejected by argparse (exit code 2)."""
    result = _run("profile", check=False)
    assert result.returncode == 2


def test_profile_dir_set_and_query(monkeypatch, tmp_path: Path) -> None:
    """``profile dir <path>`` persists the location and ``profile dir`` reads it back."""
    monkeypatch.setenv("DIRINDEX_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("DIRINDEX_PROFILES_DIR", raising=False)
    target = tmp_path / "custom-profiles"
    _run("profile", "dir", str(target))
    assert str(target.resolve()) in _run("profile", "dir").stdout
