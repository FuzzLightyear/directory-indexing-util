# Copyright (c) 2025 FuzzLightyear. All rights reserved.
# SPDX-License-Identifier: MIT

"""Rich progress utilities with millisecond elapsed and items-per-second columns.

Designed as a drop-in replacement for ``tqdm`` over arbitrary iterables.  The
column layout was validated during research against ``ThreadPoolExecutor.map``
and ``ThreadPoolExecutor + as_completed`` drivers to confirm the bar advances
incrementally rather than jumping at completion.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Generic, TypeVar

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    TaskID,
    TextColumn,
)
from rich.text import Text

T = TypeVar("T")


class _ElapsedMsColumn(ProgressColumn):
    """Elapsed time column rendered with millisecond precision."""

    def render(self, task) -> Text:
        elapsed = task.finished_time if task.finished else task.elapsed
        if elapsed is None:
            return Text("0:00:00.000")
        delta = timedelta(seconds=elapsed)
        total_seconds = int(delta.total_seconds())
        h, remainder = divmod(total_seconds, 3600)
        m, s = divmod(remainder, 60)
        ms = int(delta.microseconds / 1000)
        return Text(f"{h}:{m:02d}:{s:02d}.{ms:03d}")


class _SpeedColumn(ProgressColumn):
    """Throughput column displaying items per second."""

    def render(self, task) -> Text:
        if task.speed is None:
            return Text("? it/s")
        return Text(f"{task.speed:.1f} it/s")


class _RichIterator(Generic[T]):
    """Iterator wrapper that advances a Rich progress bar per item yielded.

    Parameters
    ----------
    iterable : iterable of T
        Underlying iterable to consume.
    desc : str, default ``"Working"``
        Description shown beside the bar.
    total : int, optional
        Expected item count.  Falls back to ``len(iterable)`` when the
        iterable supports ``__len__``.
    console : Console, optional
        Rich console instance.  A new one is created when omitted.
    transient : bool, default ``False``
        When ``True``, the bar disappears after iteration completes.
    """

    def __init__(
        self,
        iterable,
        desc: str = "Working",
        total: int | None = None,
        console: Console | None = None,
        transient: bool = False,
    ) -> None:
        self._iterator = iter(iterable)
        self._total = (
            total
            if total is not None
            else (len(iterable) if hasattr(iterable, "__len__") else None)
        )
        self._progress = Progress(
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=None),
            MofNCompleteColumn(),
            TextColumn("•"),
            _ElapsedMsColumn(),
            TextColumn("•"),
            _SpeedColumn(),
            transient=transient,
            console=console or Console(),
        )
        self._started = False
        self._task_id: TaskID | None = None
        self._desc = desc

    def close(self) -> None:
        """Stop the underlying Rich progress display."""
        if self._started:
            self._progress.stop()
            self._started = False

    def _start_if_needed(self) -> None:
        if not self._started:
            self._progress.start()
            self._task_id = self._progress.add_task(self._desc, total=self._total)
            self._started = True

    def __iter__(self):
        return self

    def __next__(self) -> T:
        self._start_if_needed()
        try:
            item = next(self._iterator)
        except StopIteration:
            self.close()
            raise
        if self._task_id is not None:
            self._progress.update(self._task_id, advance=1)
        return item


def rprogress(
    iterable,
    *,
    desc: str = "Working",
    total: int | None = None,
) -> _RichIterator:
    """Wrap *iterable* with a Rich progress display.

    Drop-in equivalent of ``tqdm`` rendering a bar with millisecond-precision
    elapsed time and items-per-second throughput.

    Parameters
    ----------
    iterable : iterable
        Iterable to wrap.
    desc : str, default ``"Working"``
        Description displayed beside the bar.
    total : int, optional
        Total expected items.  Inferred via ``len(iterable)`` when omitted.

    Returns
    -------
    _RichIterator
        Iterator that drives a Rich progress bar per item yielded.
    """
    return _RichIterator(iterable, desc=desc, total=total)
