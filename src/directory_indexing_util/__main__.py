# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""CLI entry point for directory-indexing-util.

Run via ``dirindex`` (installed script) or ``python -m directory_indexing_util``.

Notes
-----
Module-level imports are intentionally limited to stdlib plus the dependency-free
:mod:`directory_indexing_util._algorithms` module.  This keeps ``dirindex --version``
and ``dirindex --help`` fast by avoiding the cost of loading polars, rich, and
loguru when no command will actually run.  Command handlers import what they
need at call time.
"""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING

from directory_indexing_util._algorithms import ALGORITHMS, DEFAULT_ALGORITHM
from directory_indexing_util.formats import (
    _DEFAULT_FORMAT,
    _FORMATS,
    _read_dataframe,
    _resolve_output_path,
    _write_dataframe,
    _write_manifest,
)

if TYPE_CHECKING:
    import polars as pl
    from rich.console import Console

_UNSET = object()
"""Sentinel default for profile-overridable options, marking "not given"."""

_OVERRIDABLE = ("format", "algorithm", "workers")
_BUILTIN_DEFAULTS: dict[str, object] = {
    "format": _DEFAULT_FORMAT,
    "algorithm": DEFAULT_ALGORITHM,
    "workers": None,
}


def _get_version() -> str:
    """Return the installed package version, or a sentinel if uninstalled.

    Returns
    -------
    str
        Package version string read from installed metadata, or
        ``"0.0.0+unknown"`` if the package cannot be located (e.g.,
        running directly from source without an editable install).
    """
    try:
        return version("directory-indexing-util")
    except PackageNotFoundError:  # pragma: no cover - only without install
        return "0.0.0+unknown"


def _infer_format(args: argparse.Namespace) -> str:
    """Determine the effective output format for a command invocation.

    When the user supplied ``-o`` as a *file path* (not a directory) and
    its extension is one of the recognised formats, that extension wins
    over the argparse-default format, letting ``-o report.csv`` Just
    Work without also requiring ``-f csv``.  An explicit ``-f`` (i.e.,
    something other than the default) is always respected.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.  Must have ``output`` (``str`` or ``None``)
        and ``format`` (member of :data:`_FORMATS`) attributes.

    Returns
    -------
    str
        Final format string (one of :data:`_FORMATS`).
    """
    fmt = args.format
    if args.output and not Path(args.output).is_dir():
        suffix = Path(args.output).suffix.lstrip(".").lower()
        if suffix in _FORMATS and fmt == _DEFAULT_FORMAT:
            fmt = suffix
    return fmt


def _parse_extensions(value: str | None) -> set[str] | None:
    """Parse a comma-separated extension list into a normalized set.

    Strips whitespace, drops leading dots, lowercases each entry, and
    discards empty fragments.  Returns ``None`` when the input yields
    no usable extensions so the scanner can short-circuit filtering.

    Parameters
    ----------
    value : str or None
        Raw CLI argument value (e.g., ``".JPG, png, gif"``).

    Returns
    -------
    set of str or None
        Normalized extension set, or ``None`` when empty.
    """
    if not value:
        return None
    exts = {part.strip().lstrip(".").lower() for part in value.split(",") if part.strip()}
    return exts or None


def _require_directory(value: str) -> Path:
    """Return *value* as an existing directory, or exit with an error.

    Parameters
    ----------
    value : str
        User-supplied path expected to be an existing directory.

    Returns
    -------
    Path
        The path, confirmed to exist and to be a directory.

    Raises
    ------
    SystemExit
        With code 1 if the path is missing or is not a directory.
    """
    from loguru import logger  # noqa: PLC0415 - lazy

    path = Path(value)
    if not path.exists():
        logger.error("Directory does not exist: {}", path)
        raise SystemExit(1)
    if not path.is_dir():
        logger.error("Not a directory: {}", path)
        raise SystemExit(1)
    return path


def _require_file(value: str) -> Path:
    """Return *value* as an existing file, or exit with an error.

    Parameters
    ----------
    value : str
        User-supplied path expected to be an existing regular file.

    Returns
    -------
    Path
        The path, confirmed to exist and to be a file.

    Raises
    ------
    SystemExit
        With code 1 if the path is missing or is not a file.
    """
    from loguru import logger  # noqa: PLC0415 - lazy

    path = Path(value)
    if not path.exists():
        logger.error("Input file does not exist: {}", path)
        raise SystemExit(1)
    if not path.is_file():
        logger.error("Not a file: {}", path)
        raise SystemExit(1)
    return path


def _scan_with_status(
    console: Console,
    root: Path,
    include: set[str] | None,
    exclude: set[str] | None,
) -> pl.DataFrame:
    """Scan *root* under a Rich status spinner and return the result.

    Parameters
    ----------
    console : rich.console.Console
        Console used to render the transient status line.
    root : Path
        Directory to scan.
    include : set of str or None
        Extension whitelist passed through to the scanner.
    exclude : set of str or None
        Extension blacklist passed through to the scanner.

    Returns
    -------
    pl.DataFrame
        The scan result.
    """
    from directory_indexing_util.scanner import scan_directory  # noqa: PLC0415 - lazy

    with console.status("[bold cyan]Scanning…") as status:
        df = scan_directory(root, include=include, exclude=exclude)
        status.update(f"[bold cyan]Scanned {df.height:,} files")
    return df


def _emit(
    console: Console,
    df: pl.DataFrame,
    *,
    output: str | None,
    fmt: str,
    prefix: str,
    noun: str,
    manifest: tuple[str, str, str] | None = None,
) -> None:
    """Write *df* to disk and print a one-line summary.

    Parameters
    ----------
    console : rich.console.Console
        Console used for the summary line.
    df : pl.DataFrame
        DataFrame to write.
    output : str or None
        User-supplied output path or directory.
    fmt : str
        Output format.
    prefix : str
        Filename stem prefix for a generated timestamped name.
    noun : str
        Word describing the rows in the summary (e.g., ``"files"``).
    manifest : tuple of (command, input_path, algorithm) or None
        When given, a sidecar ``.meta.json`` is written and the summary
        reports any rows whose ``file_hash`` is ``null``.
    """
    output_path = _resolve_output_path(output, fmt, prefix=prefix)
    _write_dataframe(df, output_path, fmt)

    failed_count = 0
    if manifest is not None:
        command, input_path, algorithm = manifest
        failed_count = int(df.get_column("file_hash").null_count())
        _write_manifest(
            output_path.with_suffix(".meta.json"),
            command=command,
            input_path=input_path,
            output_path=str(output_path),
            algorithm=algorithm,
            file_count=df.height,
            failed_count=failed_count,
        )

    summary = f"[green]{df.height:,}[/green] {noun}"
    if failed_count:
        summary += f" ([yellow]{failed_count} unreadable[/yellow])"
    console.print(f"{summary} -> [bold]{output_path}[/bold]")


def _apply_filter(args: argparse.Namespace, profile: dict[str, object]) -> None:
    """Fill the extension filter from *profile* unless the user set one.

    Applies the profile's ``mode``/``ext`` to ``include`` or ``exclude`` only
    when the command offers the filter and the user passed neither, preserving
    the mutually exclusive contract.  Any still-unset filter resolves to
    ``None``.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments, mutated in place.
    profile : dict
        The profile being applied (may be empty).
    """
    has_inc = hasattr(args, "include")
    has_exc = hasattr(args, "exclude")
    if not (has_inc or has_exc):
        return
    user_set = (has_inc and args.include is not _UNSET) or (has_exc and args.exclude is not _UNSET)
    if not user_set:
        mode, ext = profile.get("mode"), profile.get("ext")
        if mode and ext:
            joined = ",".join(ext)
            if mode == "whitelist" and has_inc:
                args.include = joined
            elif mode == "blacklist" and has_exc:
                args.exclude = joined
    if has_inc and args.include is _UNSET:
        args.include = None
    if has_exc and args.exclude is _UNSET:
        args.exclude = None


def _apply_config(args: argparse.Namespace) -> Path:
    """Resolve profile settings into *args* in place and return the profiles dir.

    Loads ``--profile`` (or the configured default), fills each
    profile-overridable option the user did not pass, applies the extension
    filter under the mutual-exclusion guard, and bounds the worker count.  The
    config module is imported here, never at parse time, so the
    ``--help``/``--version`` fast path stays free of it.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments, mutated in place.

    Returns
    -------
    Path
        The resolved profiles directory, for a later ``--save-profile``.

    Raises
    ------
    SystemExit
        If ``--profile`` names no profile or is invalid, or ``--workers`` is
        out of range.
    """
    from loguru import logger  # noqa: PLC0415 - lazy

    from directory_indexing_util import config  # noqa: PLC0415 - lazy

    profiles_dir = config._profiles_dir(getattr(args, "profiles_dir", None))

    name = getattr(args, "profile", None)
    if name:
        try:
            profile = config._get_profile(name, profiles_dir=profiles_dir)
        except KeyError:
            logger.error("No such profile: {}", name)
            raise SystemExit(1) from None
        except config.ConfigError as exc:
            logger.error("{}", exc)
            raise SystemExit(1) from exc
    else:
        profile = {}
        default = config._get_default()
        if default:
            try:
                profile = config._get_profile(default, profiles_dir=profiles_dir)
                logger.info("Using default profile {!r}.", default)
            except (KeyError, config.ConfigError):
                profile = {}

    for dest in _OVERRIDABLE:
        if hasattr(args, dest) and getattr(args, dest) is _UNSET:
            setattr(args, dest, profile.get(dest, _BUILTIN_DEFAULTS[dest]))
    _apply_filter(args, profile)

    workers = getattr(args, "workers", None)
    if isinstance(workers, int) and not 1 <= workers <= config._MAX_WORKERS:
        logger.error("workers must be 1 to {}, got {}", config._MAX_WORKERS, workers)
        raise SystemExit(1)
    return profiles_dir


def _save_captured_profile(args: argparse.Namespace, profiles_dir: Path) -> None:
    """Save the run's resolved settings as a profile when ``--save-profile`` is set.

    Captures the resolved algorithm, workers, and format plus the active
    extension filter, then reports whether the profile was created or updated.

    Parameters
    ----------
    args : argparse.Namespace
        Resolved arguments (after :func:`_apply_config`).
    profiles_dir : Path
        Directory to save into, from :func:`_apply_config`.

    Raises
    ------
    SystemExit
        If the captured settings fail validation.
    """
    name = getattr(args, "save_profile", None)
    if not name:
        return
    from loguru import logger  # noqa: PLC0415 - lazy

    from directory_indexing_util import config  # noqa: PLC0415 - lazy

    fields: dict[str, object] = {
        "format": getattr(args, "format", None),
        "algorithm": getattr(args, "algorithm", None),
        "workers": getattr(args, "workers", None),
    }
    if getattr(args, "include", None):
        fields["mode"], fields["ext"] = "whitelist", args.include
    elif getattr(args, "exclude", None):
        fields["mode"], fields["ext"] = "blacklist", args.exclude
    try:
        existed = config._resolve_profile_file(name, profiles_dir=profiles_dir) is not None
        config._save_profile(name, fields, profiles_dir=profiles_dir)
    except config.ConfigError as exc:
        logger.error("{}", exc)
        raise SystemExit(1) from exc
    verb = "Replaced" if existed else "Saved"
    logger.info("{} profile {!r}.", verb, config._require_name(name))


def _cmd_scan(args: argparse.Namespace) -> None:
    """Execute the ``scan`` subcommand."""
    from rich.console import Console  # noqa: PLC0415 - lazy

    console = Console()

    profiles_dir = _apply_config(args)
    root = _require_directory(args.directory)
    fmt = _infer_format(args)
    include = _parse_extensions(args.include)
    exclude = _parse_extensions(args.exclude)

    df = _scan_with_status(console, root, include, exclude)
    _emit(console, df, output=args.output, fmt=fmt, prefix="scan", noun="files")
    _save_captured_profile(args, profiles_dir)


def _cmd_hash(args: argparse.Namespace) -> None:
    """Execute the ``hash`` subcommand."""
    from loguru import logger  # noqa: PLC0415 - lazy
    from rich.console import Console  # noqa: PLC0415 - lazy

    from directory_indexing_util.hasher import hash_dataframe  # noqa: PLC0415

    console = Console()

    profiles_dir = _apply_config(args)
    input_path = _require_file(args.input)

    fmt = _infer_format(args)

    try:
        df = _read_dataframe(input_path)
    except ValueError as exc:
        logger.error("{}", exc)
        raise SystemExit(1) from exc

    if "file_path" not in df.columns:
        logger.error("Input file missing required 'file_path' column.")
        raise SystemExit(1)

    df = hash_dataframe(df, algorithm=args.algorithm, workers=args.workers, desc="Hashing")

    _emit(
        console,
        df,
        output=args.output,
        fmt=fmt,
        prefix="hash",
        noun="hashes",
        manifest=("hash", str(input_path.resolve()), args.algorithm),
    )
    _save_captured_profile(args, profiles_dir)


def _cmd_index(args: argparse.Namespace) -> None:
    """Execute the ``index`` subcommand: scan + hash in a single pass."""
    from rich.console import Console  # noqa: PLC0415 - lazy

    from directory_indexing_util.hasher import hash_dataframe  # noqa: PLC0415

    console = Console()

    profiles_dir = _apply_config(args)
    root = _require_directory(args.directory)
    fmt = _infer_format(args)
    include = _parse_extensions(args.include)
    exclude = _parse_extensions(args.exclude)

    df = _scan_with_status(console, root, include, exclude)
    df = hash_dataframe(df, algorithm=args.algorithm, workers=args.workers, desc="Hashing")

    _emit(
        console,
        df,
        output=args.output,
        fmt=fmt,
        prefix="index",
        noun="indexed",
        manifest=("index", str(root.resolve()), args.algorithm),
    )
    _save_captured_profile(args, profiles_dir)


def _profile_flags(profile: dict[str, object]) -> str:
    """Render a profile as the ``dirindex`` flags that reproduce it.

    Parameters
    ----------
    profile : dict
        Validated profile fields.

    Returns
    -------
    str
        A space-joined flag string (empty for a profile with no settings).
    """
    parts: list[str] = []
    if profile.get("algorithm"):
        parts += ["-a", str(profile["algorithm"])]
    if profile.get("workers") is not None:
        parts += ["-w", str(profile["workers"])]
    if profile.get("format"):
        parts += ["-f", str(profile["format"])]
    mode, ext = profile.get("mode"), profile.get("ext")
    if mode and ext:
        parts += ["-i" if mode == "whitelist" else "-x", ",".join(ext)]
    return " ".join(parts)


def _cmd_profile_list(args: argparse.Namespace) -> None:
    """Execute ``profile list``: print profile names, marking the default."""
    from loguru import logger  # noqa: PLC0415 - lazy

    from directory_indexing_util import config  # noqa: PLC0415 - lazy

    profiles_dir = config._profiles_dir(getattr(args, "profiles_dir", None))
    names = config._list_profiles(profiles_dir)
    if not names:
        logger.info("No profiles in {}.", profiles_dir)
        return
    default = config._get_default()
    for name in names:
        print(f"{name} (default)" if name == default else name)


def _cmd_profile_show(args: argparse.Namespace) -> None:
    """Execute ``profile show``: print a profile's settings as flags."""
    from loguru import logger  # noqa: PLC0415 - lazy

    from directory_indexing_util import config  # noqa: PLC0415 - lazy

    profiles_dir = config._profiles_dir(getattr(args, "profiles_dir", None))
    try:
        profile = config._get_profile(args.name, profiles_dir=profiles_dir)
    except KeyError:
        logger.error("No such profile: {}", args.name)
        raise SystemExit(1) from None
    except config.ConfigError as exc:
        logger.error("{}", exc)
        raise SystemExit(1) from exc
    print(f"{config._require_name(args.name)}: {_profile_flags(profile) or '(no settings)'}")


def _fields_from_args(args: argparse.Namespace) -> dict[str, object]:
    """Build a profile-field mapping from the how-flags the user supplied.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed ``profile save`` or ``profile update`` arguments.

    Returns
    -------
    dict
        Only the fields the user passed (``-a``, ``-w``, ``-f``, and the
        ``-i``/``-x`` filter); unset options are omitted.
    """
    fields: dict[str, object] = {}
    for dest in ("algorithm", "workers", "format"):
        value = getattr(args, dest, _UNSET)
        if value is not _UNSET:
            fields[dest] = value
    include = getattr(args, "include", _UNSET)
    exclude = getattr(args, "exclude", _UNSET)
    if include is not _UNSET and include:
        fields["mode"], fields["ext"] = "whitelist", include
    elif exclude is not _UNSET and exclude:
        fields["mode"], fields["ext"] = "blacklist", exclude
    return fields


def _cmd_profile_save(args: argparse.Namespace) -> None:
    """Execute ``profile save``: define a profile as exactly the given flags."""
    from loguru import logger  # noqa: PLC0415 - lazy

    from directory_indexing_util import config  # noqa: PLC0415 - lazy

    profiles_dir = config._profiles_dir(getattr(args, "profiles_dir", None))
    try:
        existed = config._resolve_profile_file(args.name, profiles_dir=profiles_dir) is not None
        config._save_profile(args.name, _fields_from_args(args), profiles_dir=profiles_dir)
    except config.ConfigError as exc:
        logger.error("{}", exc)
        raise SystemExit(1) from exc
    verb = "Replaced" if existed else "Saved"
    logger.info("{} profile {!r}.", verb, config._require_name(args.name))


def _cmd_profile_update(args: argparse.Namespace) -> None:
    """Execute ``profile update``: change fields of an existing profile, keeping the rest."""
    from loguru import logger  # noqa: PLC0415 - lazy

    from directory_indexing_util import config  # noqa: PLC0415 - lazy

    profiles_dir = config._profiles_dir(getattr(args, "profiles_dir", None))
    try:
        profile = config._get_profile(args.name, profiles_dir=profiles_dir)
    except KeyError:
        logger.error("No such profile: {}", args.name)
        raise SystemExit(1) from None
    except config.ConfigError as exc:
        logger.error("{}", exc)
        raise SystemExit(1) from exc
    merged = {**profile, **_fields_from_args(args)}
    try:
        config._save_profile(args.name, merged, profiles_dir=profiles_dir)
    except config.ConfigError as exc:
        logger.error("{}", exc)
        raise SystemExit(1) from exc
    logger.info("Updated profile {!r}.", config._require_name(args.name))


def _cmd_profile_delete(args: argparse.Namespace) -> None:
    """Execute ``profile delete``: remove a profile and print how to recover it."""
    from loguru import logger  # noqa: PLC0415 - lazy

    from directory_indexing_util import config  # noqa: PLC0415 - lazy

    profiles_dir = config._profiles_dir(getattr(args, "profiles_dir", None))
    try:
        profile = config._get_profile(args.name, profiles_dir=profiles_dir)
    except KeyError:
        logger.error("No such profile: {}", args.name)
        raise SystemExit(1) from None
    except config.ConfigError:
        profile = {}

    name = config._require_name(args.name)
    was_default = config._get_default() == name
    config._delete_profile(args.name, profiles_dir=profiles_dir)

    recover = f"dirindex profile save {name} {_profile_flags(profile)}".rstrip()
    message = f"Deleted profile {name!r}. Recover with: {recover}"
    if was_default:
        message += " (it was the default, now cleared)"
    logger.info(message)


def _cmd_profile_default(args: argparse.Namespace) -> None:
    """Execute ``profile default``: show, set, or clear the default profile."""
    from loguru import logger  # noqa: PLC0415 - lazy

    from directory_indexing_util import config  # noqa: PLC0415 - lazy

    if args.clear:
        config._set_default(None)
        logger.info("Default profile cleared.")
        return
    if args.name is None:
        default = config._get_default()
        print(default if default else "(none)")
        return
    profiles_dir = config._profiles_dir(getattr(args, "profiles_dir", None))
    try:
        if config._resolve_profile_file(args.name, profiles_dir=profiles_dir) is None:
            logger.error("No such profile: {}", args.name)
            raise SystemExit(1) from None
        config._set_default(args.name)
    except config.ConfigError as exc:
        logger.error("{}", exc)
        raise SystemExit(1) from exc
    logger.info("Default profile set to {!r}.", config._require_name(args.name))


def _cmd_profile_dir(args: argparse.Namespace) -> None:
    """Execute ``profile dir``: show or persist the profiles directory."""
    from loguru import logger  # noqa: PLC0415 - lazy

    from directory_indexing_util import config  # noqa: PLC0415 - lazy

    if args.path is None:
        print(config._profiles_dir())
        return
    config._set_profiles_dir(args.path)
    logger.info("Profiles directory set to {}.", config._profiles_dir())


def _add_format_arg(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``-f/--format`` option to *parser*."""
    parser.add_argument(
        "-f",
        "--format",
        choices=_FORMATS,
        default=_UNSET,
        help=f"Output file format (default: {_DEFAULT_FORMAT}).",
    )


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``-o/--output`` and ``-f/--format`` options to *parser*."""
    parser.add_argument(
        "-o",
        "--output",
        help=(
            "Output file path or directory.  When a directory is given, a "
            "timestamped filename is generated automatically.  "
            "Defaults to the current working directory."
        ),
    )
    _add_format_arg(parser)


def _add_filter_args(parser: argparse.ArgumentParser) -> None:
    """Add the mutually exclusive ``-i/--include`` and ``-x/--exclude`` options.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Subparser to extend.  The two extension filters are mutually
        exclusive: a whitelist that keeps only the listed extensions, or a
        blacklist that drops them, never both at once.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-i",
        "--include",
        default=_UNSET,
        help=(
            "Comma-separated whitelist of file extensions to keep "
            "(e.g., 'jpg,png,gif').  Leading dots and case are normalized."
        ),
    )
    group.add_argument(
        "-x",
        "--exclude",
        default=_UNSET,
        help=(
            "Comma-separated blacklist of file extensions to drop "
            "(e.g., 'tmp,log').  Mutually exclusive with --include.  "
            "Leading dots and case are normalized."
        ),
    )


def _add_hash_args(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``-a/--algorithm`` and ``-w/--workers`` options to *parser*."""
    parser.add_argument(
        "-a",
        "--algorithm",
        choices=ALGORITHMS,
        default=_UNSET,
        help=f"Hash algorithm (default: {DEFAULT_ALGORITHM}).",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=_UNSET,
        help=(
            "Worker thread count for hashing.  Defaults to an auto-tuned "
            "value of min(cpu_count * 2, 32).  Lower it under CPU quotas "
            "or when running multiple instances concurrently."
        ),
    )


def _add_profiles_dir_arg(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``--profiles-dir`` override to *parser*."""
    parser.add_argument(
        "--profiles-dir",
        metavar="DIR",
        help="Directory holding profile files, overriding the configured location.",
    )


def _add_profile_args(parser: argparse.ArgumentParser) -> None:
    """Add ``--profile``, ``--save-profile``, and ``--profiles-dir`` to *parser*."""
    parser.add_argument(
        "--profile",
        metavar="NAME",
        help="Apply a saved profile's settings.  Explicit flags override it.",
    )
    parser.add_argument(
        "--save-profile",
        metavar="NAME",
        help="Save the run's resolved settings as a profile of this name.",
    )
    _add_profiles_dir_arg(parser)


def _add_profile_subcommand(sub: argparse._SubParsersAction) -> None:
    """Add the ``profile`` subcommand group: list, show, save, delete, default, dir."""
    profile = sub.add_parser("profile", help="Create, inspect, and manage saved profiles.")
    actions = profile.add_subparsers(dest="profile_action", metavar="ACTION", required=True)

    listing = actions.add_parser("list", help="List saved profiles.")
    _add_profiles_dir_arg(listing)
    listing.set_defaults(func=_cmd_profile_list)

    show = actions.add_parser("show", help="Show a profile's settings.")
    show.add_argument("name")
    _add_profiles_dir_arg(show)
    show.set_defaults(func=_cmd_profile_show)

    save = actions.add_parser("save", help="Create or replace a profile from flags.")
    save.add_argument("name")
    _add_hash_args(save)
    _add_filter_args(save)
    _add_format_arg(save)
    _add_profiles_dir_arg(save)
    save.set_defaults(func=_cmd_profile_save)

    update = actions.add_parser("update", help="Change fields of an existing profile.")
    update.add_argument("name")
    _add_hash_args(update)
    _add_filter_args(update)
    _add_format_arg(update)
    _add_profiles_dir_arg(update)
    update.set_defaults(func=_cmd_profile_update)

    delete = actions.add_parser("delete", help="Delete a profile.")
    delete.add_argument("name")
    _add_profiles_dir_arg(delete)
    delete.set_defaults(func=_cmd_profile_delete)

    default = actions.add_parser("default", help="Show, set, or clear the default profile.")
    default.add_argument("name", nargs="?")
    default.add_argument("--clear", action="store_true", help="Clear the default profile.")
    _add_profiles_dir_arg(default)
    default.set_defaults(func=_cmd_profile_default)

    directory = actions.add_parser("dir", help="Show or set the profiles directory.")
    directory.add_argument("path", nargs="?")
    directory.set_defaults(func=_cmd_profile_dir)


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with subcommands.

    Returns
    -------
    argparse.ArgumentParser
        Configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="dirindex",
        description="Performant, security-minded directory indexing utility.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="Recursively enumerate files in a directory.")
    scan.add_argument("directory", help="Source directory to scan.")
    _add_output_args(scan)
    _add_filter_args(scan)
    _add_profile_args(scan)
    scan.set_defaults(func=_cmd_scan)

    hash_cmd = sub.add_parser(
        "hash",
        help="Compute file hashes for paths referenced by a scan output.",
    )
    hash_cmd.add_argument(
        "input",
        help="Scan output file (parquet/csv/json/ndjson) containing a 'file_path' column.",
    )
    _add_output_args(hash_cmd)
    _add_hash_args(hash_cmd)
    _add_profile_args(hash_cmd)
    hash_cmd.set_defaults(func=_cmd_hash)

    index_cmd = sub.add_parser(
        "index",
        help="Scan a directory and hash all files in a single pass.",
    )
    index_cmd.add_argument("directory", help="Source directory to scan and hash.")
    _add_output_args(index_cmd)
    _add_filter_args(index_cmd)
    _add_hash_args(index_cmd)
    _add_profile_args(index_cmd)
    index_cmd.set_defaults(func=_cmd_index)

    _add_profile_subcommand(sub)

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = _build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(0)

    from loguru import logger  # noqa: PLC0415 - lazy, only when a command runs

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{message}")

    args.func(args)


if __name__ == "__main__":
    main()
