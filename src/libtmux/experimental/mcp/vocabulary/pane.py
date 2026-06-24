"""Pane-scope vocabulary: split, send, capture, resize, swap/join/break, select.

Beyond thin op wrappers, this module hosts the composed, caller-aware
conveniences an agent reaches for that raw tmux makes awkward:
``capture_active_pane`` (no target), ``grep_pane`` (capture + filter, since tmux
has no server-side grep), ``search_panes`` ("which pane shows X?"), and the
geometry-resolved ``resolve_relative_pane`` / ``capture_relative_pane`` /
``grep_relative_pane`` / ``find_pane_by_position`` / directional ``select_pane``.
The relative tools resolve layout geometry to a concrete ``%N`` (robust across
tmux versions) and default their origin to the *caller's* pane; every
single-target tool that could act on the wrong pane rejects a relative special
target (``{up-of}`` …) with a hint, because those resolve against this MCP's
control client, not the caller.
"""

from __future__ import annotations

import re
import typing as t

from libtmux.experimental.engines.base import AsyncTmuxEngine
from libtmux.experimental.mcp.target_resolver import resolve_target
from libtmux.experimental.mcp.vocabulary._bridge import synced
from libtmux.experimental.mcp.vocabulary._caller import (
    engine_socket,
    is_strict_caller,
)
from libtmux.experimental.mcp.vocabulary._geometry import (
    Corner,
    Direction,
    corner_pane,
    neighbor,
    parse_boxes,
)
from libtmux.experimental.mcp.vocabulary._resolve import (
    DIR_FLAG,
    active_pane_id,
    caller_of,
    guard_kill_other_panes,
    guard_self_kill,
    opt_target,
    pane_id,
    raise_target_hint,
    reject_relative_special,
    resolve_origin,
    run_select,
    select_directional,
    select_step,
    window_id,
    window_rows,
)
from libtmux.experimental.mcp.vocabulary._results import (
    Listing,
    PaneCapture,
    PaneMatch,
    PaneRef,
    PaneResult,
    PaneSearch,
    WindowResult,
)
from libtmux.experimental.ops import (
    BreakPane,
    CapturePane,
    JoinPane,
    KillPane,
    ListPanes,
    ResizePane,
    RespawnPane,
    SelectPane,
    SendKeys,
    SplitWindow,
    SwapPane,
    arun,
)
from libtmux.experimental.ops._types import PaneId, Target

#: Default ceiling on the panes ``search_panes`` captures, to bound fan-out cost.
_SEARCH_PANE_CAP = 200


def _compile(pattern: str, *, ignore_case: bool) -> re.Pattern[str]:
    """Compile a user-supplied regex, routing a bad pattern to a tool hint."""
    try:
        return re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as error:
        raise_target_hint(f"invalid search pattern {pattern!r}: {error}")


async def asplit_pane(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    horizontal: bool = False,
    start_directory: str | None = None,
    version: str | None = None,
) -> PaneResult:
    """Split a pane, creating a new one (mirrors ``window.split_window``)."""
    result = await arun(
        SplitWindow(
            target=resolve_target(target),
            horizontal=horizontal,
            start_directory=start_directory,
        ),
        engine,
        version=version,
    )
    result.raise_for_status()
    return PaneResult(pane_id=result.new_pane_id or "")


async def asend_input(
    engine: AsyncTmuxEngine,
    target: str | Target,
    keys: str,
    *,
    enter: bool = False,
    literal: bool = False,
    suppress_history: bool = False,
    version: str | None = None,
) -> None:
    """Send keys to a pane (mirrors ``pane.send_keys``)."""
    resolved = resolve_target(target)
    reject_relative_special(resolved)
    (
        await arun(
            SendKeys(
                target=resolved,
                keys=keys,
                enter=enter,
                literal=literal,
                suppress_history=suppress_history,
            ),
            engine,
            version=version,
        )
    ).raise_for_status()


async def acapture_pane(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    start: int | None = None,
    end: int | None = None,
    join_wrapped: bool = False,
    trim_trailing: bool = False,
    version: str | None = None,
) -> PaneCapture:
    """Capture one pane's terminal text (mirrors ``pane.capture_pane``)."""
    resolved = resolve_target(target)
    reject_relative_special(resolved)
    result = await arun(
        CapturePane(
            target=resolved,
            start=start,
            end=end,
            join_wrapped=join_wrapped,
            trim_trailing=trim_trailing,
        ),
        engine,
        version=version,
    )
    result.raise_for_status()
    return PaneCapture(lines=result.lines)


async def acapture_active_pane(
    engine: AsyncTmuxEngine,
    *,
    start: int | None = None,
    end: int | None = None,
    join_wrapped: bool = False,
    trim_trailing: bool = False,
    version: str | None = None,
) -> PaneCapture:
    """Capture the active pane with no explicit target (current client).

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> capture_active_pane(ConcreteEngine(capture_lines=("hi",))).lines
    ('hi',)
    """
    result = await arun(
        CapturePane(
            start=start,
            end=end,
            join_wrapped=join_wrapped,
            trim_trailing=trim_trailing,
        ),
        engine,
        version=version,
    )
    result.raise_for_status()
    return PaneCapture(lines=result.lines)


async def agrep_pane(
    engine: AsyncTmuxEngine,
    target: str | Target,
    pattern: str,
    *,
    ignore_case: bool = True,
    start: int | None = None,
    version: str | None = None,
) -> PaneCapture:
    """Search one pane's terminal text (scrollback), returning matching lines.

    tmux has no server-side grep, so this captures (joining wrapped lines so a
    match is not split across a hard wrap) and filters client-side. Matching is
    case-insensitive by default.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> engine = ConcreteEngine(capture_lines=("foo", "bar baz", "foobar"))
    >>> grep_pane(engine, "%1", "foo").lines
    ('foo', 'foobar')
    """
    resolved = resolve_target(target)
    reject_relative_special(resolved)
    matcher = _compile(pattern, ignore_case=ignore_case)
    result = await arun(
        CapturePane(target=resolved, start=start, join_wrapped=True),
        engine,
        version=version,
    )
    result.raise_for_status()
    return PaneCapture(lines=tuple(ln for ln in result.lines if matcher.search(ln)))


async def asearch_panes(
    engine: AsyncTmuxEngine,
    pattern: str,
    *,
    ignore_case: bool = True,
    start: int | None = None,
    max_panes: int = _SEARCH_PANE_CAP,
    version: str | None = None,
) -> PaneSearch:
    """Search every pane's terminal text; return the panes that match.

    Answers "which pane shows X?" by capturing each pane's scrollback and
    filtering client-side (tmux has no cross-pane search). Each match is flagged
    ``is_caller`` when it is the pane that launched this MCP. Captures are
    serial, so this is bounded to the first ``max_panes`` panes; panes whose
    capture fails are skipped (lenient, like the list accessors).
    """
    matcher = _compile(pattern, ignore_case=ignore_case)
    listing = await arun(ListPanes(all_panes=True), engine, version=version)
    listing.raise_for_status()
    caller = caller_of(engine)
    socket = engine_socket(engine)
    matches: list[PaneMatch] = []
    for row in listing.rows[:max_panes]:
        pid = row.get("pane_id", "")
        if not pid:
            continue
        cap = await arun(
            CapturePane(target=PaneId(pid), start=start, join_wrapped=True),
            engine,
            version=version,
        )
        if not cap.ok:
            continue
        lines = tuple(ln for ln in cap.lines if matcher.search(ln))
        if lines:
            matches.append(
                PaneMatch(
                    pane_id=pid,
                    is_caller=is_strict_caller(pid, socket, caller),
                    lines=lines,
                ),
            )
    return PaneSearch(matches=tuple(matches))


async def aresize_pane(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    width: int | None = None,
    height: int | None = None,
    zoom: bool = False,
    version: str | None = None,
) -> None:
    """Resize a pane, or toggle its zoom (``resize-pane``)."""
    resolved = resolve_target(target)
    reject_relative_special(resolved)
    (
        await arun(
            ResizePane(target=resolved, width=width, height=height, zoom=zoom),
            engine,
            version=version,
        )
    ).raise_for_status()


async def aswap_pane(
    engine: AsyncTmuxEngine,
    src: str | Target,
    dst: str | Target,
    *,
    version: str | None = None,
) -> None:
    """Swap two panes (``swap-pane``: ``-s`` source, ``-t`` destination)."""
    src_target = resolve_target(src)
    dst_target = resolve_target(dst)
    reject_relative_special(src_target)
    reject_relative_special(dst_target)
    (
        await arun(
            SwapPane(target=dst_target, src_target=src_target),
            engine,
            version=version,
        )
    ).raise_for_status()


async def ajoin_pane(
    engine: AsyncTmuxEngine,
    src: str | Target,
    dst: str | Target,
    *,
    horizontal: bool = False,
    size: int | None = None,
    version: str | None = None,
) -> None:
    """Join a source pane into a destination window/pane (``join-pane``)."""
    src_target = resolve_target(src)
    dst_target = resolve_target(dst)
    reject_relative_special(src_target)
    reject_relative_special(dst_target)
    (
        await arun(
            JoinPane(
                target=dst_target,
                src_target=src_target,
                horizontal=horizontal,
                size=size,
            ),
            engine,
            version=version,
        )
    ).raise_for_status()


async def abreak_pane(
    engine: AsyncTmuxEngine,
    src: str | Target,
    *,
    name: str | None = None,
    version: str | None = None,
) -> WindowResult:
    """Break a pane out into a new window (``break-pane``); return its id."""
    src_target = resolve_target(src)
    reject_relative_special(src_target)
    result = await arun(
        BreakPane(src_target=src_target, name=name),
        engine,
        version=version,
    )
    result.raise_for_status()
    return WindowResult(window_id=result.new_id or "", name=name)


async def arespawn_pane(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    kill: bool = False,
    shell: str | None = None,
    start_directory: str | None = None,
    version: str | None = None,
) -> None:
    """Restart a pane's process in place (``respawn-pane``)."""
    resolved = resolve_target(target)
    reject_relative_special(resolved)
    await guard_self_kill(
        engine, pane=await pane_id(engine, target, version), version=version
    )
    (
        await arun(
            RespawnPane(
                target=resolved,
                kill=kill,
                shell=shell,
                start_directory=start_directory,
            ),
            engine,
            version=version,
        )
    ).raise_for_status()


async def akill_pane(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    others: bool = False,
    version: str | None = None,
) -> None:
    """Kill a pane (or all others in its window with ``others=True``)."""
    resolved = resolve_target(target)
    reject_relative_special(resolved)
    target_pane = await pane_id(engine, target, version)
    if others:
        await guard_kill_other_panes(engine, target_pane, version)
    else:
        await guard_self_kill(engine, pane=target_pane, version=version)
    (
        await arun(
            KillPane(target=resolved, others=others),
            engine,
            version=version,
        )
    ).raise_for_status()


async def alist_panes(
    engine: AsyncTmuxEngine,
    target: str | Target | None = None,
    *,
    all_panes: bool = False,
    version: str | None = None,
) -> Listing:
    """List panes (metadata), flagging the caller's own pane with ``is_caller``.

    Mirrors ``window.panes``; each row gains an ``is_caller`` field (``"1"`` for
    the pane that launched this MCP, else ``"0"`` -- the same ``"1"``/``"0"``
    convention as tmux's own ``pane_active``).
    """
    result = await arun(ListPanes(all_panes=all_panes), engine, version=version)
    result.raise_for_status()
    caller = caller_of(engine)
    socket = engine_socket(engine)
    rows = tuple(
        {
            **row,
            "is_caller": "1"
            if is_strict_caller(row.get("pane_id"), socket, caller)
            else "0",
        }
        for row in result.rows
    )
    return Listing(rows=rows)


async def aselect_pane(
    engine: AsyncTmuxEngine,
    target: str | Target | None = None,
    *,
    direction: t.Literal["up", "down", "left", "right", "last", "next", "previous"]
    | None = None,
    version: str | None = None,
) -> PaneRef:
    """Focus a pane by id or relative *direction*; return the now-active pane.

    ``up``/``down``/``left``/``right`` use tmux's own directional select; ``last``
    re-selects the previously active pane; ``next``/``previous`` step by pane
    order, computed from absolute ids to sidestep tmux-version target quirks.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> select_pane(ConcreteEngine(), "%1", direction="left")
    PaneRef(pane_id=None)
    """
    if direction in DIR_FLAG:
        await select_directional(engine, target, DIR_FLAG[direction], version)
    elif direction == "last":
        await run_select(
            engine, SelectPane(target=opt_target(target), last=True), version
        )
    elif direction in ("next", "previous"):
        await select_step(engine, target, direction, version)
    elif target is not None:
        resolved = resolve_target(target)
        reject_relative_special(resolved)
        await run_select(engine, SelectPane(target=resolved), version)
    return PaneRef(pane_id=await active_pane_id(engine, target, version))


async def aresolve_relative_pane(
    engine: AsyncTmuxEngine,
    direction: Direction,
    origin: str | Target | None = None,
    *,
    version: str | None = None,
) -> PaneRef:
    """Return the id of the pane *direction* of *origin* (caller pane by default).

    Resolved from layout geometry (the ``pane_left/top/right/bottom`` the list
    template already carries) -- robust across tmux versions, and without moving
    the active pane. ``origin=None`` means the caller's own pane (the pane that
    launched this MCP), resolved only when this engine targets the caller's tmux
    server; otherwise an explicit ``origin`` is required. This never falls back to
    tmux's active pane (the control client's cursor, not the caller).
    """
    origin_id = await resolve_origin(engine, origin, version)
    if not origin_id:
        return PaneRef(pane_id=None)
    window = await window_id(engine, origin_id, version)
    boxes = parse_boxes(await window_rows(engine, window, version))
    return PaneRef(pane_id=neighbor(boxes, origin_id, direction))


async def acapture_relative_pane(
    engine: AsyncTmuxEngine,
    direction: Direction,
    origin: str | Target | None = None,
    *,
    start: int | None = None,
    end: int | None = None,
    join_wrapped: bool = False,
    trim_trailing: bool = False,
    version: str | None = None,
) -> PaneCapture:
    """Capture the pane *direction* of *origin* (caller pane by default).

    Resolves the neighbour to a concrete ``%N`` first, so it never hands tmux a
    relative special target. Raises a hint (naming the resolved origin) when
    there is no pane that way.
    """
    ref = await aresolve_relative_pane(engine, direction, origin, version=version)
    if ref.pane_id is None:
        await _raise_no_neighbour(engine, direction, origin, version)
    return await acapture_pane(
        engine,
        PaneId(ref.pane_id or ""),
        start=start,
        end=end,
        join_wrapped=join_wrapped,
        trim_trailing=trim_trailing,
        version=version,
    )


async def agrep_relative_pane(
    engine: AsyncTmuxEngine,
    direction: Direction,
    pattern: str,
    origin: str | Target | None = None,
    *,
    ignore_case: bool = True,
    start: int | None = None,
    version: str | None = None,
) -> PaneCapture:
    """Search the terminal text of the pane *direction* of *origin* (caller default).

    The one-call answer to "what does the pane above/below/beside me show?".
    Resolves the neighbour to a concrete ``%N`` first; raises a hint (naming the
    resolved origin) when there is no pane that way.
    """
    ref = await aresolve_relative_pane(engine, direction, origin, version=version)
    if ref.pane_id is None:
        await _raise_no_neighbour(engine, direction, origin, version)
    return await agrep_pane(
        engine,
        PaneId(ref.pane_id or ""),
        pattern,
        ignore_case=ignore_case,
        start=start,
        version=version,
    )


async def afind_pane_by_position(
    engine: AsyncTmuxEngine,
    corner: Corner,
    target: str | Target | None = None,
    *,
    version: str | None = None,
) -> PaneRef:
    """Return the id of the pane occupying *corner* of a window."""
    window = await window_id(engine, target, version)
    boxes = parse_boxes(await window_rows(engine, window, version))
    return PaneRef(pane_id=corner_pane(boxes, corner))


async def _raise_no_neighbour(
    engine: AsyncTmuxEngine,
    direction: Direction,
    origin: str | Target | None,
    version: str | None,
) -> t.NoReturn:
    """Raise a no-neighbour hint naming the concrete origin pane."""
    origin_id = await resolve_origin(engine, origin, version)
    where = origin_id or "the caller pane"
    raise_target_hint(
        f"no pane {direction} of {where}; see list_panes for the current layout",
    )


split_pane = synced(asplit_pane)
send_input = synced(asend_input)
capture_pane = synced(acapture_pane)
capture_active_pane = synced(acapture_active_pane)
grep_pane = synced(agrep_pane)
search_panes = synced(asearch_panes)
resize_pane = synced(aresize_pane)
swap_pane = synced(aswap_pane)
join_pane = synced(ajoin_pane)
break_pane = synced(abreak_pane)
respawn_pane = synced(arespawn_pane)
kill_pane = synced(akill_pane)
list_panes = synced(alist_panes)
select_pane = synced(aselect_pane)
resolve_relative_pane = synced(aresolve_relative_pane)
capture_relative_pane = synced(acapture_relative_pane)
grep_relative_pane = synced(agrep_relative_pane)
find_pane_by_position = synced(afind_pane_by_position)
