"""Incremental pane capture for :meth:`libtmux.pane.Pane.capture_since`.

:meth:`~libtmux.pane.Pane.capture_pane` returns a snapshot. Watching a pane
over time needs a *delta*: the rows written since the last look. Computing one
by diffing successive snapshots is wrong in three ways tmux makes easy to hit
-- output can scroll past the visible region between reads, ``history-limit``
trimming and ``clear-history`` renumber the grid under a stored row offset, and
a respawned pane keeps its ``pane_id`` while running a different process.

A :class:`CaptureCursor` anchors a position against all three. When the anchor
provably survives, the delta is exact; when it provably does not, the read
degrades to the current visible screen and says so through
:attr:`CaptureSince.lines_missed`. It never returns a silently incomplete
delta.

This module is deliberately split. Everything above :data:`PANE_STATE_FORMAT`
is pure -- it decides what a read *means* given values, and touches no tmux.
Everything below it performs tmux round-trips. Only the second half is
execution-model-specific, so an alternate driver can reuse the first half
rather than reimplement the anchor arithmetic.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
import json
import typing as t

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux.pane import Pane


#: Serialized-cursor prefix. Versioned so the wire format can change without
#: a decoder silently misreading an older payload as a newer one.
CURSOR_PREFIX = "capture-since-v1:"

_CURSOR_VERSION = 1

#: How many times a read re-samples pane state before giving up on getting an
#: untorn snapshot and reporting :attr:`CaptureSince.lines_missed`.
_STABLE_READ_ATTEMPTS = 3


class CaptureSince(t.NamedTuple):
    """Rows written since a cursor, plus the cursor that follows them.

    Attributes
    ----------
    lines : list[str]
        Captured rows, oldest first. Empty when nothing was written since
        the cursor.
    cursor : CaptureCursor
        A fresh cursor anchored after ``lines``. Pass it to the next
        :meth:`~libtmux.pane.Pane.capture_since` call.
    lines_missed : bool
        ``True`` when the previous anchor could not be proven to survive,
        so ``lines`` is the current visible screen rather than a complete
        delta. Rows written between the old anchor and the visible region
        are gone.
    """

    lines: list[str]
    cursor: CaptureCursor
    lines_missed: bool


@dataclasses.dataclass(frozen=True)
class CaptureCursor:
    """An immutable anchor into one pane's grid.

    Carries the pane it belongs to, so replaying it against a different
    pane is caught rather than silently reading the wrong process.

    Frozen because :meth:`~libtmux.pane.Pane.capture_since` returns a new
    cursor rather than advancing the one it was given -- the same cursor
    can be replayed and yields the same delta.

    Attributes
    ----------
    pane_id : str
        Pane the cursor was taken from (e.g. ``'%1'``).
    pane_pid : str
        PID of the pane's process when the cursor was taken. A change
        means the pane was respawned and the anchor describes another
        process's output.
    history_size : int
        Rows in the pane's scrollback when the cursor was taken.
    pane_height : int
        Visible rows when the cursor was taken. Distinguishes a resize
        from a real history trim.
    anchor_abs : int
        Absolute grid row of the anchor, as ``history_size + cursor_y``.
    anchor_hash : str | None
        Content hash of the anchor row, or ``None`` when the cursor sat
        below the visible region.
    below_hashes : tuple[str, ...]
        Content hashes of the rows beneath the anchor, used to re-locate
        the anchor when tmux may have renumbered the grid.

    Examples
    --------
    >>> cursor = pane.capture_since().cursor
    >>> cursor.pane_id == pane.pane_id
    True
    >>> CaptureCursor.from_str(str(cursor)) == cursor
    True
    """

    pane_id: str
    pane_pid: str
    history_size: int
    pane_height: int
    anchor_abs: int
    anchor_hash: str | None
    below_hashes: tuple[str, ...]

    def __str__(self) -> str:
        """Serialize to an opaque, round-trippable string.

        Examples
        --------
        >>> str(pane.capture_since().cursor).startswith('capture-since-v1:')
        True
        """
        payload: dict[str, t.Any] = {
            "version": _CURSOR_VERSION,
            "pane_id": self.pane_id,
            "pane_pid": self.pane_pid,
            "history_size": self.history_size,
            "pane_height": self.pane_height,
            "anchor_abs": self.anchor_abs,
            "anchor_hash": self.anchor_hash,
            "below_hashes": list(self.below_hashes),
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        return f"{CURSOR_PREFIX}{encoded}"

    @classmethod
    def from_str(cls, value: str) -> CaptureCursor:
        """Decode a cursor serialized by :meth:`__str__`.

        Parameters
        ----------
        value : str
            A string produced by ``str(cursor)``.

        Returns
        -------
        CaptureCursor

        Raises
        ------
        libtmux.exc.InvalidCaptureCursor
            If the string is not a cursor, is a version this build cannot
            read, or carries a malformed payload.

        Examples
        --------
        >>> CaptureCursor.from_str(str(pane.capture_since().cursor))
        CaptureCursor(pane_id='%...', ...)

        >>> CaptureCursor.from_str('nope')
        Traceback (most recent call last):
        libtmux.exc.InvalidCaptureCursor: invalid capture_since cursor: \
unsupported cursor format
        """
        if not value.startswith(CURSOR_PREFIX):
            _raise_invalid_cursor("unsupported cursor format")
        encoded = value.removeprefix(CURSOR_PREFIX)
        padding = "=" * (-len(encoded) % 4)
        try:
            raw = base64.urlsafe_b64decode(f"{encoded}{padding}")
            payload: t.Any = json.loads(raw)
        except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as err:
            msg = "invalid capture_since cursor: could not decode payload"
            raise exc.InvalidCaptureCursor(msg) from err

        if not isinstance(payload, dict):
            _raise_invalid_cursor("payload is not an object")
        if payload.get("version") != _CURSOR_VERSION:
            _raise_invalid_cursor("unsupported cursor version")

        anchor_hash = payload.get("anchor_hash")
        if anchor_hash is not None and not isinstance(anchor_hash, str):
            _raise_invalid_cursor("missing or invalid anchor_hash")
        below_hashes = payload.get("below_hashes")
        if not isinstance(below_hashes, list) or not all(
            isinstance(item, str) for item in below_hashes
        ):
            _raise_invalid_cursor("missing or invalid below_hashes")

        return cls(
            pane_id=_cursor_str(payload, "pane_id"),
            pane_pid=_cursor_str(payload, "pane_pid"),
            history_size=_cursor_int(payload, "history_size"),
            pane_height=_cursor_int(payload, "pane_height"),
            anchor_abs=_cursor_int(payload, "anchor_abs"),
            anchor_hash=anchor_hash,
            below_hashes=tuple(below_hashes),
        )


class _PaneState(t.NamedTuple):
    """Per-read snapshot of a pane's grid and lifecycle.

    Read in one ``display-message`` round-trip so a caller does not pay a
    subprocess per format field. ``history_size + cursor_y`` is the
    absolute grid row of the cursor.

    Attributes
    ----------
    history_size : int
        Rows currently in scrollback.
    cursor_y : int
        Cursor row within the visible region.
    pane_height : int
        Visible rows.
    pane_pid : str
        PID of the pane's process.
    pane_dead : bool
        Whether the pane's process has exited (``remain-on-exit``).
    alternate_on : bool
        Whether the pane is on the alternate screen. Reported for
        completeness because it rides along free in the same round-trip;
        never acted on. A pane on the alternate screen has handed the
        whole grid to a full-screen program that repaints it, so "rows
        below the anchor" stops carrying delta meaning -- but
        ``capture-pane -S`` still returns real main-screen scrollback, so
        the anchor itself stays arithmetically valid.
    """

    history_size: int
    cursor_y: int
    pane_height: int
    pane_pid: str
    pane_dead: bool
    alternate_on: bool = False


#: tmux format read by :func:`_read_pane_state`. A fixed literal -- no
#: caller-supplied text is ever interpolated into a tmux format string,
#: because tmux's parser treats ``#`` and ``}`` structurally and either one
#: silently corrupts the surrounding fields.
PANE_STATE_FORMAT = (
    "#{history_size}|#{cursor_y}|#{pane_height}|#{pane_pid}|#{pane_dead}"
    "|#{alternate_on}"
)

#: ``history-limit`` read, split out because it never changes between reads.
HISTORY_LIMIT_FORMAT = "#{history_limit}"


def _raise_invalid_cursor(reason: str) -> t.NoReturn:
    """Raise :exc:`~libtmux.exc.InvalidCaptureCursor` with a uniform message.

    Examples
    --------
    >>> _raise_invalid_cursor('unsupported cursor version')
    Traceback (most recent call last):
    libtmux.exc.InvalidCaptureCursor: invalid capture_since cursor: \
unsupported cursor version
    """
    msg = f"invalid capture_since cursor: {reason}"
    raise exc.InvalidCaptureCursor(msg)


def _cursor_str(payload: t.Mapping[str, t.Any], key: str) -> str:
    """Read a required non-empty string from a cursor payload.

    Examples
    --------
    >>> _cursor_str({'pane_id': '%1'}, 'pane_id')
    '%1'

    >>> _cursor_str({'pane_id': ''}, 'pane_id')
    Traceback (most recent call last):
    libtmux.exc.InvalidCaptureCursor: invalid capture_since cursor: \
missing or invalid pane_id
    """
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        _raise_invalid_cursor(f"missing or invalid {key}")
    return value


def _cursor_int(payload: t.Mapping[str, t.Any], key: str) -> int:
    """Read a required non-negative integer from a cursor payload.

    Rejects :class:`bool`, which is an :class:`int` subclass and would
    otherwise decode as ``0`` or ``1``.

    Examples
    --------
    >>> _cursor_int({'anchor_abs': 12}, 'anchor_abs')
    12

    >>> _cursor_int({'anchor_abs': True}, 'anchor_abs')
    Traceback (most recent call last):
    libtmux.exc.InvalidCaptureCursor: invalid capture_since cursor: \
missing or invalid anchor_abs
    """
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _raise_invalid_cursor(f"missing or invalid {key}")
    return value


def _line_hash(line: str) -> str:
    """Return a stable content hash for a tmux row.

    ``surrogateescape`` because tmux can hand back bytes that are not
    valid UTF-8, and a capture must never fail on undecodable output.

    Examples
    --------
    >>> _line_hash('') == _line_hash('')
    True
    >>> _line_hash('a') == _line_hash('b')
    False
    """
    return hashlib.sha256(line.encode("utf-8", "surrogateescape")).hexdigest()


def _parse_pane_state(raw: str) -> _PaneState:
    """Parse one :data:`PANE_STATE_FORMAT` line into a :class:`_PaneState`.

    ``maxsplit`` is one below the field count so a ``pane_pid`` or future
    field containing ``|`` cannot shift the parse. tmux builds that do not
    know ``alternate_on`` emit the literal format text instead of a value,
    so anything but ``"1"`` is treated as off -- this read sits on a poll
    path and must degrade rather than raise.

    Examples
    --------
    >>> _parse_pane_state('100|5|24|4242|0|0')
    _PaneState(history_size=100, cursor_y=5, pane_height=24, pane_pid='4242', \
pane_dead=False, alternate_on=False)

    A build without ``alternate_on`` still parses:

    >>> _parse_pane_state('0|0|24|4242|1').pane_dead
    True
    >>> _parse_pane_state('0|0|24|4242|1|#{alternate_on}').alternate_on
    False
    """
    parts = raw.split("|", 5)
    history_size, cursor_y, pane_height, pane_pid, pane_dead = parts[:5]
    alternate = parts[5] if len(parts) > 5 else "0"
    return _PaneState(
        history_size=int(history_size),
        cursor_y=int(cursor_y),
        pane_height=int(pane_height),
        pane_pid=pane_pid,
        pane_dead=pane_dead == "1",
        alternate_on=alternate == "1",
    )


def _cursor_anchor_lost(cursor: CaptureCursor, state: _PaneState) -> bool:
    """Whether sampled state proves tmux destroyed the cursor's anchor.

    ``anchor_abs`` below ``history_size`` is *not* loss -- the anchor
    scrolled into retained scrollback, where ``capture-pane -S`` still
    addresses it with a negative start offset.

    The ``pane_height`` comparison separates a resize-grow, which pulls
    rows out of history back into the visible region without freeing
    anything, from a real trim, where row data is gone.

    Parameters
    ----------
    cursor : CaptureCursor
        The anchor being checked.
    state : _PaneState
        A current snapshot of the same pane.

    Returns
    -------
    bool

    Examples
    --------
    An unchanged pane keeps its anchor:

    >>> steady = CaptureCursor('%1', '1', 100, 24, 110, None, ())
    >>> _cursor_anchor_lost(steady, _PaneState(100, 10, 24, '1', False))
    False

    Growing the pane explains a shrunken history, so it is not loss --
    the rows moved back into the visible region rather than being freed:

    >>> _cursor_anchor_lost(steady, _PaneState(90, 10, 34, '1', False))
    False

    Each branch below is shown against state where only it fires, since a
    real ``clear-history`` trips all three at once and would not show
    which one is load-bearing.

    An anchor past the bottom of the grid cannot exist, even with history
    intact and unshrunken:

    >>> off_grid = CaptureCursor('%1', '1', 10, 24, 100, None, ())
    >>> _cursor_anchor_lost(off_grid, _PaneState(10, 5, 24, '1', False))
    True

    A history wiped to zero destroys the anchor even when a simultaneous
    pane grow leaves it inside the new grid and explains the shrink:

    >>> wiped = CaptureCursor('%1', '1', 5, 24, 10, None, ())
    >>> _cursor_anchor_lost(wiped, _PaneState(0, 0, 30, '1', False))
    True

    A partial trim at constant height destroys rows while the anchor
    still addresses a row that exists:

    >>> trimmed = CaptureCursor('%1', '1', 100, 24, 50, None, ())
    >>> _cursor_anchor_lost(trimmed, _PaneState(60, 5, 24, '1', False))
    True
    """
    bottom_abs = state.history_size + state.pane_height - 1
    if cursor.anchor_abs > bottom_abs:
        return True
    # A complete history wipe (``clear-history``) always destroys the anchor
    # regardless of pane height -- the grid is reset to zero.
    if state.history_size == 0 and cursor.history_size > 0:
        return True
    return state.history_size < cursor.history_size and (
        state.pane_height <= cursor.pane_height
    )


def _history_limit_trim_risk(
    cursor: CaptureCursor,
    state: _PaneState,
    history_limit: int,
) -> bool:
    """Whether tmux may have rebased retained-history rows.

    tmux trims scrollback in batches rather than one row at a time, so
    ``history_size`` alone cannot prove rows were not renumbered. Anywhere
    within one batch of the limit, positional arithmetic is untrustworthy
    and the anchor must be re-located by content instead.

    Parameters
    ----------
    cursor : CaptureCursor
        The anchor being checked.
    state : _PaneState
        A current snapshot of the same pane.
    history_limit : int
        The pane's ``history-limit``.

    Returns
    -------
    bool

    Examples
    --------
    >>> cursor = CaptureCursor('%1', '1', 10, 24, 20, None, ())
    >>> state = _PaneState(10, 5, 24, '1', False)

    Far from the limit, offsets can be trusted:

    >>> _history_limit_trim_risk(cursor, state, 2000)
    False

    Close to it, they cannot:

    >>> _history_limit_trim_risk(cursor, state, 10)
    True

    A pane with no scrollback at all is always at risk:

    >>> _history_limit_trim_risk(cursor, state, 0)
    True
    """
    if history_limit <= 0:
        return True
    trim_batch = max(history_limit // 10, 1)
    risk_floor = history_limit - trim_batch
    return cursor.history_size >= risk_floor or state.history_size >= risk_floor


def _find_unique_cursor_match(rows: list[str], cursor: CaptureCursor) -> int | None:
    """Locate the cursor's anchor in ``rows`` by content fingerprint.

    Used when :func:`_history_limit_trim_risk` says offsets cannot be
    trusted. Matches the anchor row *and* the rows recorded beneath it, so
    a repeated single line (a bare shell prompt, say) does not anchor to
    the wrong place.

    Parameters
    ----------
    rows : list[str]
        Captured rows to search, oldest first.
    cursor : CaptureCursor
        The anchor to locate.

    Returns
    -------
    int | None
        Index of the anchor row, or ``None`` when the fingerprint is
        absent or appears more than once -- either way the anchor cannot
        be proven, and the caller must report a missed read.

    Examples
    --------
    >>> rows = ['alpha', 'beta', 'gamma']
    >>> cursor = CaptureCursor(
    ...     '%1', '1', 0, 24, 0, _line_hash('beta'), (_line_hash('gamma'),)
    ... )
    >>> _find_unique_cursor_match(rows, cursor)
    1

    An absent fingerprint does not match:

    >>> _find_unique_cursor_match(['alpha'], cursor) is None
    True

    An ambiguous fingerprint is refused rather than guessed:

    >>> ambiguous = CaptureCursor('%1', '1', 0, 24, 0, _line_hash('alpha'), ())
    >>> _find_unique_cursor_match(['alpha', 'beta', 'alpha'], ambiguous) is None
    True

    A cursor with no anchor row has nothing to match on:

    >>> _find_unique_cursor_match(rows, CaptureCursor(
    ...     '%1', '1', 0, 24, 0, None, ()
    ... )) is None
    True
    """
    if cursor.anchor_hash is None:
        return None

    fingerprint = (cursor.anchor_hash, *cursor.below_hashes)
    if len(rows) < len(fingerprint):
        return None

    match_index: int | None = None
    for index in range(len(rows) - len(fingerprint) + 1):
        candidate = rows[index : index + len(fingerprint)]
        if tuple(_line_hash(line) for line in candidate) != fingerprint:
            continue
        if match_index is not None:
            return None
        match_index = index
    return match_index


def _drop_previously_seen_rows(
    rows: list[str],
    cursor: CaptureCursor,
) -> list[str]:
    """Drop rows the cursor already reported.

    Compares hashes rather than counting, so a row rewritten in place --
    a progress bar redrawing over itself with a carriage return -- is
    reported as new content instead of skipped as already-seen.

    Parameters
    ----------
    rows : list[str]
        Captured rows starting at the anchor, oldest first.
    cursor : CaptureCursor
        The anchor these rows were captured from.

    Returns
    -------
    list[str]

    Examples
    --------
    >>> cursor = CaptureCursor(
    ...     '%1', '1', 0, 24, 0, _line_hash('prompt'), (_line_hash('below'),)
    ... )

    Unchanged rows are dropped, new ones kept:

    >>> _drop_previously_seen_rows(['prompt', 'below', 'fresh'], cursor)
    ['fresh']

    A rewritten anchor row is new content, while the unchanged row below
    it stays dropped:

    >>> _drop_previously_seen_rows(['prompt$ ls', 'below'], cursor)
    ['prompt$ ls']

    Matching stops at the first difference, so nothing after a changed
    row is dropped on position alone:

    >>> _drop_previously_seen_rows(['prompt', 'rewritten', 'below'], cursor)
    ['rewritten', 'below']

    >>> _drop_previously_seen_rows([], cursor)
    []
    """
    if not rows:
        return []

    output: list[str] = []
    if cursor.anchor_hash is None or _line_hash(rows[0]) != cursor.anchor_hash:
        output.append(rows[0])
    tail = rows[1:]

    drop = 0
    for expected_hash, line in zip(cursor.below_hashes, tail, strict=False):
        if _line_hash(line) != expected_hash:
            break
        drop += 1
    output.extend(tail[drop:])
    return output


def _build_cursor(
    pane_id: str,
    state: _PaneState,
    cursor_rows: list[str],
) -> CaptureCursor:
    """Build the cursor describing where a completed read stopped.

    Parameters
    ----------
    pane_id : str
        Pane the read came from.
    state : _PaneState
        The snapshot the read settled on.
    cursor_rows : list[str]
        Rows from the cursor row through the visible bottom.

    Returns
    -------
    CaptureCursor

    Examples
    --------
    >>> _build_cursor('%1', _PaneState(100, 5, 24, '42', False), ['a', 'b'])
    CaptureCursor(pane_id='%1', pane_pid='42', history_size=100, \
pane_height=24, anchor_abs=105, anchor_hash='...', below_hashes=('...',))

    A cursor below the visible region has no rows to fingerprint:

    >>> _build_cursor('%1', _PaneState(0, 0, 24, '42', False), []).anchor_hash \
is None
    True
    """
    return CaptureCursor(
        pane_id=pane_id,
        pane_pid=state.pane_pid,
        history_size=state.history_size,
        pane_height=state.pane_height,
        anchor_abs=state.history_size + state.cursor_y,
        anchor_hash=_line_hash(cursor_rows[0]) if cursor_rows else None,
        below_hashes=tuple(_line_hash(line) for line in cursor_rows[1:]),
    )


class _PaneRead(t.NamedTuple):
    """One completed tmux read, before it becomes a :class:`CaptureSince`.

    Attributes
    ----------
    state : _PaneState
        The snapshot the read settled on.
    cursor_rows : list[str]
        Rows from the cursor row through the visible bottom, used to
        fingerprint the next cursor.
    lines : list[str]
        Rows to return to the caller.
    lines_missed : bool
        Whether ``lines`` is a fallback visible capture rather than a
        complete delta.
    """

    state: _PaneState
    cursor_rows: list[str]
    lines: list[str]
    lines_missed: bool


def _read_pane_state(pane: Pane) -> _PaneState:
    """Snapshot ``pane``'s grid and lifecycle in one round-trip.

    Examples
    --------
    >>> state = _read_pane_state(pane)
    >>> state.pane_height > 0
    True
    >>> state.pane_dead
    False
    """
    stdout = pane.display_message(PANE_STATE_FORMAT, get_text=True)
    return _parse_pane_state(stdout[0] if stdout else "0|0|0||0")


def _read_history_limit(pane: Pane) -> int:
    """Read ``pane``'s ``history-limit`` once.

    Fixed at pane creation -- a retroactive ``set-option history-limit``
    only takes effect from tmux 3.7 (commit ``e7b1575``), and older
    versions need a new pane. Safe to cache for one capture, and kept out
    of :func:`_read_pane_state` so per-tick reads do not pay for a value
    that cannot change between ticks.

    Examples
    --------
    >>> _read_history_limit(pane) > 0
    True
    """
    stdout = pane.display_message(HISTORY_LIMIT_FORMAT, get_text=True)
    return int(stdout[0] if stdout else "0")


def _capture_rows(
    pane: Pane,
    *,
    start: t.Literal["-"] | int | None = None,
    end: t.Literal["-"] | int | None = None,
) -> list[str]:
    """Capture pane rows as a concrete list.

    Examples
    --------
    >>> isinstance(_capture_rows(pane), list)
    True
    """
    rows = pane.capture_pane(start=start, end=end)
    return [] if rows is None else list(rows)


def _capture_cursor_rows(pane: Pane, state: _PaneState) -> list[str]:
    """Capture from the cursor row through the visible bottom.

    Examples
    --------
    >>> isinstance(_capture_cursor_rows(pane, _read_pane_state(pane)), list)
    True

    A cursor below the visible region has no rows:

    >>> _capture_cursor_rows(pane, _PaneState(0, 99, 24, '1', False))
    []
    """
    if state.cursor_y >= state.pane_height:
        return []
    return _capture_rows(pane, start=state.cursor_y, end=None)


def _raise_if_lifecycle_changed(
    pane_id: str | None,
    state: _PaneState,
    baseline_pid: str,
) -> None:
    """Raise when a cursor's process identity no longer holds.

    Examples
    --------
    >>> _raise_if_lifecycle_changed('%1', _PaneState(0, 0, 24, '42', False), '42')

    >>> _raise_if_lifecycle_changed('%1', _PaneState(0, 0, 24, '99', False), '42')
    Traceback (most recent call last):
    libtmux.exc.PaneLifecycleChanged: pane %1 was respawned (pid 42 -> 99); \
cursor anchor is no longer valid

    >>> _raise_if_lifecycle_changed('%1', _PaneState(0, 0, 24, '42', True), '42')
    Traceback (most recent call last):
    libtmux.exc.PaneLifecycleChanged: pane %1 died; cursor anchor is no \
longer valid
    """
    if state.pane_dead:
        msg = f"pane {pane_id} died; cursor anchor is no longer valid"
        raise exc.PaneLifecycleChanged(msg)
    if state.pane_pid != baseline_pid:
        msg = (
            f"pane {pane_id} was respawned "
            f"(pid {baseline_pid} -> {state.pane_pid}); "
            "cursor anchor is no longer valid"
        )
        raise exc.PaneLifecycleChanged(msg)


def _read_stable_visible(
    pane: Pane,
    *,
    baseline_pid: str | None = None,
) -> _PaneRead:
    """Capture the visible pane, re-sampling until the grid holds still.

    Samples state, captures, then re-samples. A difference means the pane
    moved mid-capture and the rows may be torn across two grid states, so
    the read is retried. After :data:`_STABLE_READ_ATTEMPTS` the rows are
    returned with ``lines_missed`` set rather than presented as exact.

    Parameters
    ----------
    pane : Pane
        Pane to read.
    baseline_pid : str, optional
        PID a cursor expects. When omitted this is a first read, so any
        live PID is accepted and only pane death is an error.

    Returns
    -------
    _PaneRead

    Examples
    --------
    >>> read = _read_stable_visible(pane)
    >>> read.lines_missed
    False
    >>> isinstance(read.lines, list)
    True
    """
    for _attempt in range(_STABLE_READ_ATTEMPTS):
        before = _read_pane_state(pane)
        if baseline_pid is None:
            _raise_if_dead_without_baseline(pane, before)
            expected_pid = before.pane_pid
        else:
            expected_pid = baseline_pid
            _raise_if_lifecycle_changed(pane.pane_id, before, expected_pid)

        lines = _capture_rows(pane)
        cursor_rows = _capture_cursor_rows(pane, before)
        after = _read_pane_state(pane)
        _raise_if_lifecycle_changed(pane.pane_id, after, expected_pid)
        if before == after:
            return _PaneRead(
                state=after,
                cursor_rows=cursor_rows,
                lines=lines,
                lines_missed=False,
            )

    state = _read_pane_state(pane)
    if baseline_pid is None:
        _raise_if_dead_without_baseline(pane, state)
    else:
        _raise_if_lifecycle_changed(pane.pane_id, state, baseline_pid)
    return _PaneRead(
        state=state,
        cursor_rows=_capture_cursor_rows(pane, state),
        lines=_capture_rows(pane),
        lines_missed=True,
    )


def _raise_if_dead_without_baseline(pane: Pane, state: _PaneState) -> None:
    """Raise when a first read finds the pane already dead.

    Examples
    --------
    >>> _raise_if_dead_without_baseline(pane, _read_pane_state(pane))
    """
    if state.pane_dead:
        msg = f"pane {pane.pane_id} died during pane read"
        raise exc.PaneLifecycleChanged(msg)


def _read_delta(pane: Pane, cursor: CaptureCursor) -> _PaneRead:
    """Capture rows written since ``cursor``, or fall back on anchor loss.

    Parameters
    ----------
    pane : Pane
        Pane to read.
    cursor : CaptureCursor
        Anchor to read from.

    Returns
    -------
    _PaneRead

    Examples
    --------
    >>> read = _read_delta(pane, pane.capture_since().cursor)
    >>> read.lines_missed
    False
    """
    history_limit = _read_history_limit(pane)
    for _attempt in range(_STABLE_READ_ATTEMPTS):
        before = _read_pane_state(pane)
        _raise_if_lifecycle_changed(pane.pane_id, before, cursor.pane_pid)
        if _cursor_anchor_lost(cursor, before):
            return _missed_read(pane, cursor)

        trim_risk = _history_limit_trim_risk(cursor, before, history_limit)
        start = cursor.anchor_abs - before.history_size
        if trim_risk:
            rows = _capture_rows(pane, start="-", end=None)
        elif start >= before.pane_height:
            rows = []
        else:
            rows = _capture_rows(pane, start=start, end=None)
        cursor_rows = _capture_cursor_rows(pane, before)

        after = _read_pane_state(pane)
        _raise_if_lifecycle_changed(pane.pane_id, after, cursor.pane_pid)
        if before != after:
            continue

        if trim_risk:
            match_index = _find_unique_cursor_match(rows, cursor)
            if match_index is None:
                return _missed_read(pane, cursor)
            rows = rows[match_index:]
        return _PaneRead(
            state=after,
            cursor_rows=cursor_rows,
            lines=_drop_previously_seen_rows(rows, cursor),
            lines_missed=False,
        )

    return _missed_read(pane, cursor)


def _missed_read(pane: Pane, cursor: CaptureCursor) -> _PaneRead:
    """Fall back to the visible screen and mark the delta incomplete.

    Examples
    --------
    >>> _missed_read(pane, pane.capture_since().cursor).lines_missed
    True
    """
    missed = _read_stable_visible(pane, baseline_pid=cursor.pane_pid)
    return missed._replace(lines_missed=True)


def capture_since(pane: Pane, cursor: CaptureCursor | None = None) -> CaptureSince:
    """Capture rows written to ``pane`` since ``cursor``.

    Implements :meth:`libtmux.pane.Pane.capture_since`; call that instead.

    Parameters
    ----------
    pane : Pane
        Pane to read.
    cursor : CaptureCursor, optional
        Anchor from a previous call. When omitted the current visible
        screen is captured and a first cursor is opened.

    Returns
    -------
    CaptureSince

    Raises
    ------
    libtmux.exc.InvalidCaptureCursor
        If ``cursor`` belongs to a different pane.
    libtmux.exc.PaneLifecycleChanged
        If the pane died or was respawned since ``cursor`` was taken.

    Examples
    --------
    >>> first = capture_since(pane)
    >>> capture_since(pane, first.cursor).lines
    []
    """
    if pane.pane_id is None:
        raise exc.PaneNotFound
    if cursor is not None and cursor.pane_id != pane.pane_id:
        msg = (
            f"invalid capture_since cursor: cursor pane {cursor.pane_id} "
            f"does not match requested pane {pane.pane_id}"
        )
        raise exc.InvalidCaptureCursor(msg)

    read = _read_stable_visible(pane) if cursor is None else _read_delta(pane, cursor)
    return CaptureSince(
        lines=read.lines,
        cursor=_build_cursor(pane.pane_id, read.state, read.cursor_rows),
        lines_missed=read.lines_missed,
    )
