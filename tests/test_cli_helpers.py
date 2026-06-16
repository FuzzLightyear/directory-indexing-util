# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Unit tests for the internal CLI helpers in :mod:`directory_indexing_util.__main__`.

These cover the pure-Python branching logic — format inference, output-path
resolution, extension-list parsing, and the read-dataframe dispatcher —
without spawning subprocesses.  The subprocess-level integration tests
live in :mod:`test_cli`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl
import pytest

from directory_indexing_util import config
from directory_indexing_util.__main__ import (
    _DEFAULT_FORMAT,
    _FORMATS,
    _UNSET,
    _apply_config,
    _infer_format,
    _parse_extensions,
    _read_dataframe,
    _resolve_output_path,
    _save_captured_profile,
    _write_dataframe,
)


def _ns(output: str | None, fmt: str = _DEFAULT_FORMAT) -> argparse.Namespace:
    """Build a minimal Namespace with the fields ``_infer_format`` reads."""
    return argparse.Namespace(output=output, format=fmt)


# ---------------------------------------------------------------------------
# _infer_format
# ---------------------------------------------------------------------------


def test_infer_format_no_output_uses_default() -> None:
    """When ``-o`` is omitted the argparse default format wins."""
    assert _infer_format(_ns(output=None)) == _DEFAULT_FORMAT


def test_infer_format_directory_output_uses_default(tmp_path: Path) -> None:
    """A directory target cannot disambiguate format; default is preserved."""
    assert _infer_format(_ns(output=str(tmp_path))) == _DEFAULT_FORMAT


def test_infer_format_recognised_extension_overrides_default(tmp_path: Path) -> None:
    """``-o file.csv`` switches the default parquet to csv automatically."""
    target = tmp_path / "report.csv"
    assert _infer_format(_ns(output=str(target))) == "csv"


def test_infer_format_recognised_extension_case_insensitive(tmp_path: Path) -> None:
    """Extension matching is case-insensitive (``.NDJSON`` → ``ndjson``)."""
    target = tmp_path / "report.NDJSON"
    assert _infer_format(_ns(output=str(target))) == "ndjson"


def test_infer_format_unknown_extension_keeps_format(tmp_path: Path) -> None:
    """An unrecognised extension does not override the format flag."""
    target = tmp_path / "report.bogus"
    assert _infer_format(_ns(output=str(target))) == _DEFAULT_FORMAT


def test_infer_format_explicit_non_default_wins(tmp_path: Path) -> None:
    """An explicit ``-f json`` is respected even when ``-o report.csv``."""
    target = tmp_path / "report.csv"
    assert _infer_format(_ns(output=str(target), fmt="json")) == "json"


def test_infer_format_extensionless_output_uses_default(tmp_path: Path) -> None:
    """A file path with no extension falls through to the default format."""
    target = tmp_path / "report"
    assert _infer_format(_ns(output=str(target))) == _DEFAULT_FORMAT


# ---------------------------------------------------------------------------
# _resolve_output_path
# ---------------------------------------------------------------------------


def test_resolve_output_path_none_returns_cwd_timestamped() -> None:
    """``None`` lands in the current working directory with a timestamped name."""
    result = _resolve_output_path(None, "parquet")
    assert result.parent == Path.cwd()
    assert result.name.startswith("scan_")
    assert result.suffix == ".parquet"


def test_resolve_output_path_uses_prefix() -> None:
    """The *prefix* kwarg controls the generated filename stem prefix."""
    result = _resolve_output_path(None, "csv", prefix="hash")
    assert result.name.startswith("hash_")
    assert result.suffix == ".csv"


def test_resolve_output_path_directory_target_gets_timestamped_name(tmp_path: Path) -> None:
    """When *output* names an existing directory, a file is generated inside it."""
    result = _resolve_output_path(str(tmp_path), "json", prefix="index")
    assert result.parent == tmp_path
    assert result.name.startswith("index_")
    assert result.suffix == ".json"


def test_resolve_output_path_file_target_returned_verbatim(tmp_path: Path) -> None:
    """A non-directory *output* is returned as-is, regardless of *prefix*."""
    target = tmp_path / "custom.parquet"
    result = _resolve_output_path(str(target), "parquet", prefix="hash")
    assert result == target


def test_resolve_output_path_uses_format_extension(tmp_path: Path) -> None:
    """The *fmt* arg drives the generated filename's extension."""
    for fmt in _FORMATS:
        result = _resolve_output_path(str(tmp_path), fmt)
        assert result.suffix == f".{fmt}"


# ---------------------------------------------------------------------------
# _parse_extensions
# ---------------------------------------------------------------------------


def test_parse_extensions_none_returns_none() -> None:
    """``None`` short-circuits to ``None`` for cheap is-filtering checks."""
    assert _parse_extensions(None) is None


def test_parse_extensions_empty_string_returns_none() -> None:
    """An empty string is treated the same as ``None``."""
    assert _parse_extensions("") is None


def test_parse_extensions_whitespace_only_returns_none() -> None:
    """Strings that contain only whitespace yield no usable extensions."""
    assert _parse_extensions("   ") is None


def test_parse_extensions_strips_leading_dots() -> None:
    """``.py`` and ``py`` produce identical sets."""
    assert _parse_extensions(".py") == {"py"}
    assert _parse_extensions("py") == {"py"}


def test_parse_extensions_lowercases() -> None:
    """Comparison is case-insensitive; uppercase input is normalised."""
    assert _parse_extensions("PY") == {"py"}
    assert _parse_extensions("JPG,PNG") == {"jpg", "png"}


def test_parse_extensions_handles_whitespace_around_entries() -> None:
    """Whitespace around comma-separated entries is stripped."""
    assert _parse_extensions(" .jpg , png , .gif ") == {"jpg", "png", "gif"}


def test_parse_extensions_discards_empty_fragments() -> None:
    """Adjacent commas do not produce empty-string entries in the set."""
    assert _parse_extensions("jpg,,png") == {"jpg", "png"}


def test_parse_extensions_collapses_duplicates() -> None:
    """A repeated extension appears once in the set."""
    assert _parse_extensions("jpg,JPG,.JpG") == {"jpg"}


# ---------------------------------------------------------------------------
# _read_dataframe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", _FORMATS)
def test_read_dataframe_round_trips_each_format(tmp_path: Path, fmt: str) -> None:
    """Each format Polars writes is readable back via the dispatcher."""
    src_df = pl.DataFrame({"file_name": ["a"], "file_path": [str(tmp_path / "a")]})
    path = tmp_path / f"data.{fmt}"
    if fmt == "parquet":
        src_df.write_parquet(path)
    elif fmt == "csv":
        src_df.write_csv(path)
    elif fmt == "json":
        src_df.write_json(path)
    elif fmt == "ndjson":
        src_df.write_ndjson(path)

    out = _read_dataframe(path)
    assert out.columns == ["file_name", "file_path"]
    assert out.height == 1


def test_read_dataframe_rejects_unknown_extension(tmp_path: Path) -> None:
    """Unsupported extensions raise ValueError with a clear message."""
    path = tmp_path / "data.bogus"
    path.write_text("not a real serialization", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported input format"):
        _read_dataframe(path)


def test_read_dataframe_extension_case_insensitive(tmp_path: Path) -> None:
    """Extension dispatch is case-insensitive (``.PARQUET`` works)."""
    src_df = pl.DataFrame({"file_name": ["a"], "file_path": ["a"]})
    path = tmp_path / "data.PARQUET"
    src_df.write_parquet(path)
    out = _read_dataframe(path)
    assert out.height == 1


# ---------------------------------------------------------------------------
# CSV formula-injection neutralization (SEC-4)
# ---------------------------------------------------------------------------


def test_write_csv_neutralizes_formula_injection(tmp_path: Path) -> None:
    """A field beginning with a formula character is written as text in CSV."""
    df = pl.DataFrame(
        {
            "file_name": ["=1+1", "safe.txt"],
            "file_path": ["C:/data/=1+1", "C:/data/safe.txt"],
        }
    )
    out = tmp_path / "indexed.csv"
    _write_dataframe(df, out, "csv")
    text = out.read_text(encoding="utf-8")

    assert "'=1+1" in text  # leading-formula file name is prefixed with a quote
    assert "C:/data/=1+1" in text  # absolute path has no leading formula char, untouched
    assert "safe.txt" in text  # benign value is unchanged


def test_write_parquet_does_not_alter_values(tmp_path: Path) -> None:
    """Non-CSV formats are written verbatim, with no formula prefixing."""
    df = pl.DataFrame({"file_name": ["=1+1"], "file_path": ["C:/data/=1+1"]})
    out = tmp_path / "indexed.parquet"
    _write_dataframe(df, out, "parquet")
    back = _read_dataframe(out)
    assert back.get_column("file_name")[0] == "=1+1"


# ---------------------------------------------------------------------------
# Profile application (_apply_config / _save_captured_profile)
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg(monkeypatch, tmp_path: Path) -> Path:
    """Isolate config and profile storage in a temp dir for one test."""
    monkeypatch.setenv("DIRINDEX_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DIRINDEX_PROFILES_DIR", raising=False)
    return tmp_path


def _index_ns(**overrides: object) -> argparse.Namespace:
    """Build an index-shaped namespace with every overridable option unset."""
    ns = argparse.Namespace(
        directory=".",
        output=None,
        profile=None,
        save_profile=None,
        profiles_dir=None,
        format=_UNSET,
        algorithm=_UNSET,
        workers=_UNSET,
        include=_UNSET,
        exclude=_UNSET,
    )
    ns.__dict__.update(overrides)
    return ns


def test_apply_config_fills_builtin_defaults(cfg: Path) -> None:
    """With no profile, every unset option resolves to its built-in default."""
    ns = _index_ns()
    _apply_config(ns)
    assert (ns.format, ns.algorithm, ns.workers) == ("parquet", "sha256", None)
    assert ns.include is None
    assert ns.exclude is None


def test_apply_config_profile_fills_unset_options(cfg: Path) -> None:
    """A named profile fills the options the user did not pass."""
    config._save_profile(
        "p",
        {"algorithm": "blake3", "workers": 4, "format": "csv"},
        profiles_dir=config._profiles_dir(),
    )
    ns = _index_ns(profile="p")
    _apply_config(ns)
    assert (ns.format, ns.algorithm, ns.workers) == ("csv", "blake3", 4)


def test_apply_config_explicit_flag_beats_profile(cfg: Path) -> None:
    """An explicit flag wins over the profile; unset options still fill."""
    config._save_profile(
        "p", {"algorithm": "sha512", "format": "csv"}, profiles_dir=config._profiles_dir()
    )
    ns = _index_ns(profile="p", algorithm="md5")
    _apply_config(ns)
    assert ns.algorithm == "md5"
    assert ns.format == "csv"


def test_apply_config_applies_configured_default(cfg: Path) -> None:
    """With no --profile, a configured default profile applies."""
    pdir = config._profiles_dir()
    config._save_profile("d", {"algorithm": "sha512"}, profiles_dir=pdir)
    config._set_default("d")
    ns = _index_ns()
    _apply_config(ns)
    assert ns.algorithm == "sha512"


def test_apply_config_unknown_profile_exits(cfg: Path) -> None:
    """``--profile`` naming nothing exits non-zero."""
    with pytest.raises(SystemExit):
        _apply_config(_index_ns(profile="ghost"))


def test_apply_config_whitelist_profile_sets_include(cfg: Path) -> None:
    """A whitelist profile fills --include and leaves --exclude unset."""
    config._save_profile(
        "imgs", {"mode": "whitelist", "ext": ["jpg", "png"]}, profiles_dir=config._profiles_dir()
    )
    ns = _index_ns(profile="imgs")
    _apply_config(ns)
    assert ns.include == "jpg,png"
    assert ns.exclude is None


def test_apply_config_explicit_filter_blocks_profile_filter(cfg: Path) -> None:
    """An explicit -i suppresses a profile's blacklist, preserving exclusivity."""
    config._save_profile(
        "drop", {"mode": "blacklist", "ext": ["tmp"]}, profiles_dir=config._profiles_dir()
    )
    ns = _index_ns(profile="drop", include="py")
    _apply_config(ns)
    assert ns.include == "py"
    assert ns.exclude is None


def test_apply_config_rejects_out_of_range_workers(cfg: Path) -> None:
    """An explicit --workers beyond the cap exits non-zero."""
    with pytest.raises(SystemExit):
        _apply_config(_index_ns(workers=10**6))


def test_save_captured_profile_records_resolved_settings(cfg: Path) -> None:
    """--save-profile persists the resolved how, mapping include to mode and ext."""
    pdir = config._profiles_dir()
    ns = _index_ns(
        save_profile="cap", algorithm="sha512", workers=2, format="csv", include="py", exclude=None
    )
    _save_captured_profile(ns, pdir)
    assert config._get_profile("cap", profiles_dir=pdir) == {
        "algorithm": "sha512",
        "workers": 2,
        "format": "csv",
        "mode": "whitelist",
        "ext": ["py"],
    }
