"""The asyncio driver for :mod:`libtmux.capture`: incremental reads and waits.

:mod:`libtmux.capture` is split at its ``TMUX I/O BOUNDARY``. Above the line it
decides what a read means given values: whether a cursor's anchor survived,
which rows are new, which rows a text wait may match. This module is the half
below the line for ``async`` code. It asks tmux the same questions through an
:class:`~libtmux.engines.base.AsyncTmuxEngine` and hands the answers to the same
pure functions, so a cursor taken here is valid there and the other way around.

:func:`wait_for_text` differs from the blocking :meth:`libtmux.Pane.wait_for_text`
in one way: it does not poll. It subscribes to the pane's output first, reads
once so text that is already there is found, and then sleeps until the pane
prints. The decision still comes from a rendered ``capture-pane``, never from
the output bytes, so cursor movement, wrapping and redraws are seen as tmux
drew them.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import typing as t

from libtmux import exc
from libtmux.capture import (
    _POLL_MIN,
    _READ_TIMEOUT_FLOOR,
    _STABLE_READ_ATTEMPTS,
    HISTORY_LIMIT_FORMAT,
    PANE_STATE_FORMAT,
    CaptureCursor,
    CaptureSince,
    TextMatch,
    _above_row_count,
    _anchor_row_reported,
    _anchor_shift,
    _build_cursor,
    _compile_wait_pattern,
    _cursor_anchor_lost,
    _drop_previously_seen_rows,
    _find_unique_cursor_match,
    _first_row_match,
    _history_limit_trim_risk,
    _PaneRead,
    _PaneState,
    _parse_pane_state,
    _poll_delay,
    _raise_if_lifecycle_changed,
    _searchable_rows,
)
from libtmux.engines.base import CommandRequest

if t.TYPE_CHECKING:
    from libtmux.engines.base import AsyncTmuxEngine
    from libtmux.engines.control.aio import OutputWatch

logger = logging.getLogger(__name__)

#: Longest a wait sleeps without a wake-up. Output normally wakes a wait at
#: once; this bounds the cost of a missed wake-up, such as a pane in a session
#: the control client is not attached to, which sends it no output.
FALLBACK_INTERVAL = 1.0


class WatchSource(t.Protocol):
    """What :func:`wait_for_text` needs to be woken by a pane's output."""

    def watch_output(self, pane: str) -> OutputWatch:
        """Return a watch that wakes when *pane* prints."""
        ...


async def _cmd(
    engine: AsyncTmuxEngine,
    pane_id: str,
    name: str,
    *args: str,
    timeout: float | None = None,
) -> t.Any:
    """Run one tmux command against *pane_id* and return the result."""
    return await engine.run(
        CommandRequest.from_args(name, "-t", pane_id, *args, timeout=timeout),
    )


async def _display(
    engine: AsyncTmuxEngine,
    pane_id: str,
    fmt: str,
    *,
    timeout: float | None = None,
) -> list[str]:
    result = await _cmd(engine, pane_id, "display-message", "-p", fmt, timeout=timeout)
    return list(result.stdout)


async def _read_pane_state(
    engine: AsyncTmuxEngine,
    pane_id: str,
    *,
    timeout: float | None = None,
) -> _PaneState:
    """Snapshot the pane's grid and lifecycle in one round-trip."""
    stdout = await _display(engine, pane_id, PANE_STATE_FORMAT, timeout=timeout)
    return _parse_pane_state(stdout[0] if stdout else "0|0|0||0")


async def _read_history_limit(
    engine: AsyncTmuxEngine,
    pane_id: str,
    *,
    timeout: float | None = None,
) -> int:
    stdout = await _display(engine, pane_id, HISTORY_LIMIT_FORMAT, timeout=timeout)
    return int(stdout[0] if stdout else "0")


async def _capture_rows(
    engine: AsyncTmuxEngine,
    pane_id: str,
    *,
    start: t.Literal["-"] | int | None = None,
    end: t.Literal["-"] | int | None = None,
    timeout: float | None = None,
) -> list[str]:
    """Capture rows, refusing to mistake a failed read for silence."""
    args = ["-p"]
    if start is not None:
        args.extend(["-S", str(start)])
    if end is not None:
        args.extend(["-E", str(end)])
    result = await _cmd(engine, pane_id, "capture-pane", *args, timeout=timeout)
    if result.stderr:
        msg = f"capture-pane: {' '.join(result.stderr)}"
        raise exc.LibTmuxException(msg)
    return list(result.stdout)


async def _capture_cursor_rows(
    engine: AsyncTmuxEngine,
    pane_id: str,
    state: _PaneState,
    *,
    timeout: float | None = None,
) -> list[str] | None:
    if state.cursor_y >= state.pane_height:
        return None
    return await _capture_rows(
        engine,
        pane_id,
        start=state.cursor_y - _above_row_count(state),
        timeout=timeout,
    )


async def _read_stable_visible(
    engine: AsyncTmuxEngine,
    pane_id: str,
    *,
    baseline_pid: str | None = None,
    timeout: float | None = None,
) -> _PaneRead:
    """Capture the visible pane, re-sampling until the grid holds still."""
    before = await _read_pane_state(engine, pane_id, timeout=timeout)
    lines: list[str] = []
    cursor_rows: list[str] | None = []
    for _attempt in range(_STABLE_READ_ATTEMPTS):
        before = await _read_pane_state(engine, pane_id, timeout=timeout)
        if baseline_pid is None:
            if before.pane_dead:
                msg = f"pane {pane_id} died during pane read"
                raise exc.PaneLifecycleChanged(msg)
            expected_pid = before.pane_pid
        else:
            expected_pid = baseline_pid
            _raise_if_lifecycle_changed(pane_id, before, expected_pid)

        lines = await _capture_rows(engine, pane_id, timeout=timeout)
        cursor_rows = await _capture_cursor_rows(
            engine,
            pane_id,
            before,
            timeout=timeout,
        )
        after = await _read_pane_state(engine, pane_id, timeout=timeout)
        _raise_if_lifecycle_changed(pane_id, after, expected_pid)
        if before == after:
            return _PaneRead(
                state=after,
                cursor_rows=cursor_rows,
                lines=lines,
                lines_missed=False,
            )

    logger.debug(
        "pane never settled across %s reads; reporting a missed capture",
        _STABLE_READ_ATTEMPTS,
        extra={"tmux_pane": pane_id, "tmux_stdout_len": len(lines)},
    )
    return _PaneRead(
        state=before,
        cursor_rows=cursor_rows,
        lines=lines,
        lines_missed=True,
    )


async def _read_delta(
    engine: AsyncTmuxEngine,
    pane_id: str,
    cursor: CaptureCursor,
    *,
    timeout: float | None = None,
) -> _PaneRead:
    """Capture rows written since *cursor*, or fall back on anchor loss."""
    history_limit = await _read_history_limit(engine, pane_id, timeout=timeout)
    for _attempt in range(_STABLE_READ_ATTEMPTS):
        before = await _read_pane_state(engine, pane_id, timeout=timeout)
        _raise_if_lifecycle_changed(pane_id, before, cursor.pane_pid)
        trim_risk = _history_limit_trim_risk(cursor, before, history_limit)
        if _cursor_anchor_lost(cursor, before, content_search=trim_risk):
            return await _missed_read(engine, pane_id, cursor, timeout=timeout)

        start = cursor.anchor_abs - _anchor_shift(cursor, before)
        start -= before.history_size
        if trim_risk:
            rows = await _capture_rows(
                engine,
                pane_id,
                start="-",
                end=None,
                timeout=timeout,
            )
        else:
            rows = await _capture_rows(
                engine,
                pane_id,
                start=start,
                end=None,
                timeout=timeout,
            )
        cursor_rows = await _capture_cursor_rows(
            engine,
            pane_id,
            before,
            timeout=timeout,
        )

        after = await _read_pane_state(engine, pane_id, timeout=timeout)
        _raise_if_lifecycle_changed(pane_id, after, cursor.pane_pid)
        if before != after:
            continue

        if trim_risk:
            match_index = _find_unique_cursor_match(rows, cursor)
            if match_index is None:
                return await _missed_read(engine, pane_id, cursor, timeout=timeout)
            rows = rows[match_index:]
        return _PaneRead(
            state=after,
            cursor_rows=cursor_rows,
            lines=_drop_previously_seen_rows(rows, cursor),
            lines_missed=False,
            anchor_reported=_anchor_row_reported(rows, cursor),
        )

    return await _missed_read(engine, pane_id, cursor, timeout=timeout)


async def _missed_read(
    engine: AsyncTmuxEngine,
    pane_id: str,
    cursor: CaptureCursor,
    *,
    timeout: float | None = None,
) -> _PaneRead:
    missed = await _read_stable_visible(
        engine,
        pane_id,
        baseline_pid=cursor.pane_pid,
        timeout=timeout,
    )
    return missed._replace(lines_missed=True)


async def _read_since(
    engine: AsyncTmuxEngine,
    pane_id: str,
    cursor: CaptureCursor | None,
    *,
    timeout: float | None = None,
) -> _PaneRead:
    if cursor is not None and cursor.pane_id != pane_id:
        msg = (
            f"invalid capture_since cursor: cursor pane {cursor.pane_id} "
            f"does not match requested pane {pane_id}"
        )
        raise exc.InvalidCaptureCursor(msg)
    if cursor is None:
        return await _read_stable_visible(engine, pane_id, timeout=timeout)
    return await _read_delta(engine, pane_id, cursor, timeout=timeout)


async def capture_since(
    engine: AsyncTmuxEngine,
    pane_id: str,
    cursor: CaptureCursor | None = None,
    *,
    timeout: float | None = None,
) -> CaptureSince:
    """Capture rows written to a pane since *cursor*.

    The awaitable form of :meth:`libtmux.Pane.capture_since`: the same cursors,
    the same anchor rules, the same ``lines_missed`` honesty, read through an
    async engine.

    Parameters
    ----------
    engine : AsyncTmuxEngine
        Where to send the reads.
    pane_id : str
        Pane id such as ``%3``.
    cursor : CaptureCursor, optional
        Anchor from a previous call. Omitted, the visible screen is captured and
        a first cursor is opened.
    timeout : float, optional
        Bound, in seconds, on each tmux call.

    Returns
    -------
    CaptureSince
        New rows, the cursor that follows them, and whether rows were missed.

    Raises
    ------
    ~libtmux.exc.InvalidCaptureCursor
        *cursor* belongs to a different pane.
    ~libtmux.exc.PaneLifecycleChanged
        The pane died or was respawned since *cursor* was taken.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.aio.capture import capture_since
    >>> from libtmux.engines import AsyncSubprocessEngine
    >>> async def demo():
    ...     engine = AsyncSubprocessEngine.for_server(server)
    ...     first = await capture_since(engine, pane.pane_id)
    ...     again = await capture_since(engine, pane.pane_id, first.cursor)
    ...     return again.lines, again.lines_missed
    >>> asyncio.run(demo())
    ([], False)
    """
    read = await _read_since(engine, pane_id, cursor, timeout=timeout)
    return CaptureSince(
        lines=read.lines,
        cursor=_build_cursor(pane_id, read.state, read.cursor_rows),
        lines_missed=read.lines_missed,
    )


def _remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return max(deadline - time.monotonic(), _READ_TIMEOUT_FLOOR)


async def wait_for_text(
    engine: AsyncTmuxEngine,
    pane_id: str,
    pattern: str | re.Pattern[str],
    *,
    timeout: float | None = 30.0,
    since: CaptureCursor | None = None,
    regex: bool = False,
    watch: WatchSource | None = None,
    fallback: float = FALLBACK_INTERVAL,
) -> TextMatch:
    r"""Wait until *pattern* appears in rows written since an anchor.

    The awaitable form of :meth:`libtmux.Pane.wait_for_text`, woken by the pane's
    output instead of a timer. It subscribes before the first read, so output
    that arrives between the read and the sleep is never lost, and it reads once
    before sleeping, so text that is already there is found at once.

    Parameters
    ----------
    engine : AsyncTmuxEngine
        Where to send the reads. When it has ``watch_output``, such as
        :class:`~libtmux.engines.control.aio.AsyncControlModeEngine`, it also
        supplies the wake-ups.
    pane_id : str
        Pane id such as ``%3``.
    pattern : str or re.Pattern
        Text to find, or a compiled pattern.
    timeout : float, optional
        Seconds to wait. ``None`` waits until the text appears.
    since : CaptureCursor, optional
        Search only rows after this anchor; by default the pane as it is now.
    regex : bool
        Treat a string *pattern* as a regular expression.
    watch : WatchSource, optional
        The source of wake-ups, when it is not *engine* itself. With neither, the
        wait re-reads every *fallback* seconds.
    fallback : float
        Longest sleep without a wake-up.

    Returns
    -------
    TextMatch
        The matching row's :class:`re.Match`, a cursor after the read that
        found it, and ``lines_missed``.

    Raises
    ------
    ~libtmux.exc.WaitTimeout
        *timeout* elapsed without a match. Nothing is killed.
    ~libtmux.exc.TmuxTimeout
        A read outlived its bound.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.aio.capture import capture_since, wait_for_text
    >>> from libtmux.engines import AsyncSubprocessEngine, CommandRequest
    >>> async def demo():
    ...     engine = AsyncSubprocessEngine.for_server(server)
    ...     anchor = await capture_since(engine, pane.pane_id)
    ...     await engine.run(
    ...         CommandRequest.from_args(
    ...             "send-keys", "-t", pane.pane_id,
    ...             "printf '%s%s\\n' async_ marker", "Enter",
    ...         )
    ...     )
    ...     hit = await wait_for_text(
    ...         engine, pane.pane_id, "async_marker", since=anchor.cursor, timeout=10
    ...     )
    ...     return hit.match.string
    >>> asyncio.run(demo())
    'async_marker'
    """
    compiled = _compile_wait_pattern(pattern, regex=regex)
    deadline = None if timeout is None else time.monotonic() + timeout
    source = watch if watch is not None else _watch_source(engine)
    watcher = source.watch_output(pane_id) if source is not None else None
    try:
        anchor = (
            since
            if since is not None
            else (
                await capture_since(
                    engine,
                    pane_id,
                    timeout=_remaining(deadline),
                )
            ).cursor
        )
        saw_alternate_screen = False
        delay = _POLL_MIN
        while True:
            read = await _read_since(
                engine,
                pane_id,
                anchor,
                timeout=_remaining(deadline),
            )
            if read.state.alternate_on:
                saw_alternate_screen = True
            else:
                found = _first_row_match(
                    compiled,
                    _searchable_rows(
                        read.lines,
                        anchor_reported=read.anchor_reported,
                        lines_missed=read.lines_missed,
                        cursor=anchor,
                    ),
                )
                if found is not None:
                    return TextMatch(
                        match=found,
                        cursor=_build_cursor(pane_id, read.state, read.cursor_rows),
                        lines_missed=read.lines_missed,
                    )
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                msg = (
                    f"timed out after {timeout}s waiting for "
                    f"text {compiled.pattern!r} in pane {pane_id}"
                )
                if saw_alternate_screen:
                    msg += (
                        "; the pane was on the alternate screen, which a "
                        "full-screen program repaints, so its rows were not searched"
                    )
                raise exc.WaitTimeout(msg)
            if watcher is not None:
                nap = fallback if left is None else min(fallback, left)
                await watcher.changed(nap)
                # A burst of output is one wake-up and one read.
                await asyncio.sleep(0)
            else:
                # Nothing to wake us: poll, growing the delay like the blocking
                # wait does.
                await asyncio.sleep(delay if left is None else min(delay, left))
                delay = _poll_delay(delay)
    finally:
        if watcher is not None:
            watcher.close()


def _watch_source(engine: AsyncTmuxEngine) -> WatchSource | None:
    """Return *engine* when it can wake a wait, else ``None``."""
    return engine if hasattr(engine, "watch_output") else None  # type: ignore[return-value]
