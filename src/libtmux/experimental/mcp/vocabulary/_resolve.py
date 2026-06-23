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
    socket_matches,
)
from libtmux.experimental.ops import DisplayMessage, ListPanes, SelectPane, arun
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
    caller's own pane (from the server's environment), socket-scoped exactly
    like :func:`~._caller.is_strict_caller` because a ``%N`` is unique only
    within one server. When there is no trustworthy caller pane -- the server is
    not inside tmux, or its pane belongs to a different server than this engine
    targets -- this raises rather than guessing the active pane, so the caller
    must pass an explicit origin.
    """
    if origin is not None:
        return await pane_id(engine, origin, version)
    caller = CallerContext.from_env()
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
