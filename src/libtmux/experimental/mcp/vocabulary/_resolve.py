"""Shared async resolution helpers for the curated vocabulary.

The pane-scoped tools need to turn a polymorphic target into a concrete id, find
the window scoping a target, and read a window's panes -- small async steps the
pane/window modules share. Kept here so each category module stays focused on its
verbs.
"""

from __future__ import annotations

import typing as t

from libtmux.experimental.engines.base import AsyncTmuxEngine
from libtmux.experimental.mcp.target_resolver import resolve_target
from libtmux.experimental.mcp.vocabulary._caller import (
    CallerContext,
    engine_socket,
    socket_could_match,
    socket_matches,
)
from libtmux.experimental.ops import (
    DisplayMessage,
    ListPanes,
    SelectPane,
    TmuxCommandError,
    arun,
)
from libtmux.experimental.ops._types import PaneId, Special, Target

#: Relative directional special tokens that resolve against the control client,
#: not the caller -- rejected with a hint by :func:`reject_relative_special`.
_RELATIVE_SPECIALS = frozenset({"up-of", "down-of", "left-of", "right-of"})

#: tmux ``select-pane`` direction flags for the four geometric directions.
DIR_FLAG: dict[str, t.Literal["U", "D", "L", "R"]] = {
    "up": "U",
    "down": "D",
    "left": "L",
    "right": "R",
}


def opt_target(target: str | Target | None) -> Target | None:
    """Resolve an optional target, preserving ``None``."""
    return None if target is None else resolve_target(target)


async def pane_id(
    engine: AsyncTmuxEngine,
    target: str | Target,
    version: str | None,
) -> str:
    """Resolve *target* to a concrete pane id (``%N``)."""
    resolved = resolve_target(target)
    if isinstance(resolved, PaneId):
        return resolved.value
    result = await arun(
        DisplayMessage(target=resolved, message="#{pane_id}"),
        engine,
        version=version,
    )
    result.raise_for_status()
    return result.text.strip()


async def window_id(
    engine: AsyncTmuxEngine,
    target: str | Target | None,
    version: str | None,
) -> str:
    """Resolve the window id for *target* (or the active window when ``None``)."""
    op = (
        DisplayMessage(message="#{window_id}")
        if target is None
        else DisplayMessage(target=resolve_target(target), message="#{window_id}")
    )
    result = await arun(op, engine, version=version)
    result.raise_for_status()
    return result.text.strip()


async def window_rows(
    engine: AsyncTmuxEngine,
    window: str,
    version: str | None,
) -> list[t.Mapping[str, str]]:
    """Return the ``list-panes`` rows belonging to *window*, in tmux order."""
    result = await arun(ListPanes(all_panes=True), engine, version=version)
    result.raise_for_status()
    return [row for row in result.rows if row.get("window_id") == window]


async def run_select(
    engine: AsyncTmuxEngine,
    op: SelectPane,
    version: str | None,
) -> None:
    """Run a ``select-pane`` op and raise on failure."""
    (await arun(op, engine, version=version)).raise_for_status()


async def select_directional(
    engine: AsyncTmuxEngine,
    target: str | Target | None,
    flag: t.Literal["U", "D", "L", "R"],
    version: str | None,
) -> None:
    """Move the selection one pane in a tmux direction."""
    await run_select(
        engine, SelectPane(target=opt_target(target), direction=flag), version
    )


async def select_step(
    engine: AsyncTmuxEngine,
    target: str | Target | None,
    direction: t.Literal["next", "previous"],
    version: str | None,
) -> None:
    """Select the next/previous pane by absolute id (tmux-version robust)."""
    rows = await window_rows(engine, await window_id(engine, target, version), version)
    if not rows:
        return
    ids = [row.get("pane_id", "") for row in rows]
    active = next(
        (row.get("pane_id", "") for row in rows if row.get("pane_active") == "1"),
        ids[0],
    )
    step = 1 if direction == "next" else -1
    target_id = ids[(ids.index(active) + step) % len(ids)]
    await run_select(engine, SelectPane(target=PaneId(target_id)), version)


async def active_pane_id(
    engine: AsyncTmuxEngine,
    target: str | Target | None,
    version: str | None,
) -> str | None:
    """Return the active pane id of the window scoping *target*."""
    rows = await window_rows(engine, await window_id(engine, target, version), version)
    for row in rows:
        if row.get("pane_active") == "1":
            return row.get("pane_id")
    return rows[0].get("pane_id") if rows else None


async def resolve_origin(
    engine: AsyncTmuxEngine,
    origin: str | Target | None,
    version: str | None,
) -> str:
    """Resolve a caller-relative origin to a concrete pane id.

    An explicit *origin* is resolved as a target; ``origin=None`` means the
    caller's own pane (from the discovered caller context -- own env, an explicit
    override, or a ``/proc`` parent walk), socket-scoped exactly like
    :func:`~._caller.is_strict_caller` because a ``%N`` is unique only within one
    server. When there is no trustworthy caller pane -- the server is not inside
    tmux, or its pane belongs to a different server than this engine targets --
    this raises rather than guessing the active pane, so the caller must pass an
    explicit origin.
    """
    if origin is not None:
        return await pane_id(engine, origin, version)
    caller = caller_of(engine)
    if caller.pane_id and socket_matches(engine_socket(engine), caller):
        return caller.pane_id
    raise_target_hint(
        "no caller pane is available (this MCP is not inside the engine's tmux "
        "server); pass an explicit origin pane id (e.g. %3) -- list_panes shows "
        "the current panes",
    )


def raise_target_hint(message: str) -> t.NoReturn:
    """Raise a user-facing tool error (``ToolError`` when fastmcp is present).

    Falls back to :class:`ValueError` so the guard is testable on the sync
    surface without the ``mcp`` extra installed.
    """
    try:
        from fastmcp.exceptions import ToolError
    except ImportError:
        raise ValueError(message) from None
    raise ToolError(message)


def reject_relative_special(resolved: Target | None) -> None:
    """Raise a targeted hint if *resolved* is a relative directional special.

    ``{up-of}`` / ``{down-of}`` / ``{left-of}`` / ``{right-of}`` resolve against
    this MCP's own control-mode client, not the caller's pane, so passing one to
    a capture/grep/send tool silently targets the wrong pane. Anchor specials
    (``{marked}`` / ``{last}`` / ``{mouse}``) are left untouched.
    """
    if (
        isinstance(resolved, Special)
        and resolved.token.strip("{}").lower() in _RELATIVE_SPECIALS
    ):
        raise_target_hint(
            f"relative special target {resolved.token} resolves against this MCP's "
            "control-mode client, not your pane; resolve_relative_pane(direction=...) "
            "and pass the returned %N to your capture/grep/send tool, or use the "
            "composed capture_relative_pane / grep_relative_pane (origin defaults to "
            "your pane)",
        )


def caller_of(engine: AsyncTmuxEngine) -> CallerContext:
    """Return the caller context discovered at build time (stashed on the engine).

    Falls back to a fresh :meth:`~._caller.CallerContext.from_env` read when no
    context was stashed (the engine was built outside the adapter).
    """
    stashed = getattr(engine, "_caller_context", None)
    if isinstance(stashed, CallerContext):
        return stashed
    return CallerContext.from_env()


async def session_id_of(
    engine: AsyncTmuxEngine,
    target: str | Target,
    version: str | None,
) -> str:
    """Return the session id (``$N``) containing *target* (a pane/window/session)."""
    result = await arun(
        DisplayMessage(target=resolve_target(target), message="#{session_id}"),
        engine,
        version=version,
    )
    result.raise_for_status()
    return result.text.strip()


async def caller_window_or_none(
    engine: AsyncTmuxEngine,
    caller_pane: str,
    version: str | None,
) -> str | None:
    """Map the caller's pane to its window, or ``None`` if not on this server.

    Fails safe: a caller pane that does not exist on the engine's server (the
    cross-server case the conservative gate tolerates) is *not* a self-kill, so
    the lookup returns ``None`` rather than surfacing a raw tmux error.
    """
    try:
        return await window_id(engine, PaneId(caller_pane), version)
    except TmuxCommandError:
        return None


async def caller_session_or_none(
    engine: AsyncTmuxEngine,
    caller_pane: str,
    version: str | None,
) -> str | None:
    """Map the caller's pane to its session, or ``None`` if not on this server."""
    try:
        return await session_id_of(engine, PaneId(caller_pane), version)
    except TmuxCommandError:
        return None


async def conservative_socket(
    engine: AsyncTmuxEngine,
    version: str | None,
) -> str | None:
    """Resolve the engine's socket for a conservative caller comparison.

    An explicit ``-S`` path is authoritative as-is. For a ``-L`` name or the
    ambient socket, asks tmux for ``#{socket_path}`` -- the path tmux actually
    uses -- so a macOS ``$TMUX_TMPDIR`` divergence under launchd cannot fool the
    reconstruction; falls back to the static selector when the query fails.
    """
    static = engine_socket(engine)
    if static is not None and "/" in static:
        return static
    try:
        result = await arun(
            DisplayMessage(message="#{socket_path}"),
            engine,
            version=version,
        )
        result.raise_for_status()
    except TmuxCommandError:
        return static
    return result.text.strip() or static


async def guard_self_kill(
    engine: AsyncTmuxEngine,
    *,
    pane: str | None = None,
    window: str | None = None,
    session: str | None = None,
    version: str | None = None,
) -> None:
    """Refuse a destructive op aimed at the caller's own pane/window/session.

    Socket-scoped first (``%N``/``@N``/``$N`` are per-server counters that
    collide across servers), then the caller's pane is mapped to its window /
    session *via the engine* (``$TMUX`` carries no window id). Uses the
    conservative comparator so a self-kill fails safe under socket uncertainty;
    a caller pane absent from this engine's server fails safe to *allow* (it is
    not a self-kill). Raises a refusal hint; a different pane/window/session, or a
    cross-socket target with the same id, is not refused.
    """
    caller = caller_of(engine)
    if not caller.in_tmux or caller.pane_id is None:
        return
    if not socket_could_match(await conservative_socket(engine, version), caller):
        return
    if pane is not None and caller.pane_id == pane:
        raise_target_hint(
            f"refusing to kill pane {pane}: it runs this MCP server. Target a "
            "different pane, or run the tmux command manually if intended.",
        )
    if window is not None:
        caller_window = await caller_window_or_none(engine, caller.pane_id, version)
        if caller_window is not None and caller_window == window:
            raise_target_hint(
                f"refusing to kill window {window}: it holds this MCP server's "
                "pane. Use a manual tmux command if intended.",
            )
    if session is not None:
        caller_session = await caller_session_or_none(engine, caller.pane_id, version)
        if caller_session is not None and caller_session == session:
            raise_target_hint(
                f"refusing to kill session {session}: it holds this MCP server's "
                "pane. Use a manual tmux command if intended.",
            )


async def guard_kill_other_panes(
    engine: AsyncTmuxEngine,
    target_pane: str,
    version: str | None,
) -> None:
    """Refuse ``kill_pane(others=True)`` when the caller is a sibling of the target.

    ``others=True`` keeps the target and kills every other pane in its window, so
    the danger is the caller pane being one of those siblings (not the target).
    """
    caller = caller_of(engine)
    if not caller.in_tmux or not caller.pane_id or caller.pane_id == target_pane:
        return
    if not socket_could_match(await conservative_socket(engine, version), caller):
        return
    caller_window = await caller_window_or_none(engine, caller.pane_id, version)
    if caller_window is None:
        return
    target_window = await window_id(engine, PaneId(target_pane), version)
    if caller_window == target_window:
        raise_target_hint(
            f"refusing to kill the other panes of window {target_window}: pane "
            f"{caller.pane_id} runs this MCP server. Kill panes individually "
            f"(excluding {caller.pane_id}), or run the tmux command manually.",
        )


async def guard_kill_other_windows(
    engine: AsyncTmuxEngine,
    target: str | Target,
    target_window: str,
    version: str | None,
) -> None:
    """Refuse ``kill_window(others=True)`` when the caller is a same-session sibling.

    ``others=True`` keeps the target window and kills every other window in its
    session, so the danger is the caller's window being one of those siblings.
    """
    caller = caller_of(engine)
    if not caller.in_tmux or not caller.pane_id:
        return
    if not socket_could_match(await conservative_socket(engine, version), caller):
        return
    caller_window = await caller_window_or_none(engine, caller.pane_id, version)
    if caller_window is None or caller_window == target_window:
        return  # caller not on this server, or it is the kept target window
    target_session = await session_id_of(engine, target, version)
    caller_session = await caller_session_or_none(engine, caller.pane_id, version)
    if caller_session is None or caller_session != target_session:
        return
    raise_target_hint(
        f"refusing to kill the other windows of session {caller_session}: window "
        f"{caller_window} holds this MCP server's pane {caller.pane_id}. Exclude "
        "it, or run the tmux command manually.",
    )


async def guard_destructive_op(engine: AsyncTmuxEngine, operation: t.Any) -> None:
    """Apply the self-kill guard to a per-op kill/respawn operation, by kind.

    Covers the ``op_*`` per-operation surface, including the ``others=True``
    sibling case (which keeps the target and kills its neighbours).
    """
    target = operation.target
    if target is None:
        return
    kind = operation.kind
    others = bool(getattr(operation, "others", False))
    if kind == "respawn_pane":
        await guard_self_kill(engine, pane=await pane_id(engine, target, None))
    elif kind == "kill_pane":
        target_pane = await pane_id(engine, target, None)
        if others:
            await guard_kill_other_panes(engine, target_pane, None)
        else:
            await guard_self_kill(engine, pane=target_pane)
    elif kind == "kill_window":
        target_window = await window_id(engine, target, None)
        if others:
            await guard_kill_other_windows(engine, target, target_window, None)
        else:
            await guard_self_kill(engine, window=target_window)
    elif kind == "kill_session":
        await guard_self_kill(engine, session=await session_id_of(engine, target, None))
