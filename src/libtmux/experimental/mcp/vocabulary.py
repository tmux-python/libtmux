"""Curated core vocabulary -- the intuitive, named tmux tools.

The Layer-1 surface: a small set of hand-written, framework-agnostic functions
that mirror libtmux's own ORM (``server.new_session`` / ``window.split_window`` /
``pane.send_keys``) but run over any engine and return small, typed result
objects exposing just the ids/names a caller cares about. Each is a thin wrapper:
resolve the target, build one operation, :func:`~..ops.execute.run` it, raise on
failure, return a typed result. Power users drop to the per-op descriptors,
plans, or ops directly.

Examples
--------
>>> from libtmux.experimental.engines import ConcreteEngine
>>> engine = ConcreteEngine()
>>> session = create_session(engine, name="dev")
>>> session.session_id
'$1'
>>> pane = split_pane(engine, session.first_pane_id or "%1", horizontal=True)
>>> pane.pane_id
'%2'
>>> send_input(engine, pane.pane_id, "pytest -q", enter=True) is None
True
"""

from __future__ import annotations

import collections.abc
from dataclasses import dataclass

from libtmux.experimental.engines.base import TmuxEngine
from libtmux.experimental.mcp.target_resolver import resolve_target
from libtmux.experimental.ops import (
    CapturePane,
    KillPane,
    KillSession,
    KillWindow,
    ListPanes,
    ListSessions,
    ListWindows,
    NewSession,
    NewWindow,
    RenameSession,
    RenameWindow,
    SelectLayout,
    SelectPane,
    SendKeys,
    SplitWindow,
    run,
)
from libtmux.experimental.ops._types import Target

# TmuxEngine / Target are imported at runtime (not under TYPE_CHECKING) so the
# fastmcp adapter's get_type_hints() can resolve these annotations when it builds
# tool schemas from these functions.


@dataclass(frozen=True)
class SessionResult:
    """A created session: its id, name, and captured first window/pane ids."""

    session_id: str
    name: str | None = None
    first_window_id: str | None = None
    first_pane_id: str | None = None


@dataclass(frozen=True)
class WindowResult:
    """A created window: its id, name, and captured first pane id."""

    window_id: str
    name: str | None = None
    first_pane_id: str | None = None


@dataclass(frozen=True)
class PaneResult:
    """A created pane: its id."""

    pane_id: str


@dataclass(frozen=True)
class PaneCapture:
    """Captured pane contents."""

    lines: tuple[str, ...]


@dataclass(frozen=True)
class Listing:
    """A list query result: one mapping (tmux format row) per object."""

    rows: tuple[collections.abc.Mapping[str, str], ...]


def create_session(
    engine: TmuxEngine,
    *,
    name: str | None = None,
    start_directory: str | None = None,
    environment: collections.abc.Mapping[str, str] | None = None,
    width: int | None = None,
    height: int | None = None,
    version: str | None = None,
) -> SessionResult:
    """Create a detached session (mirrors ``server.new_session``).

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> r = create_session(ConcreteEngine(), name="work")
    >>> (r.session_id, r.name, r.first_pane_id)
    ('$1', 'work', '%1')
    """
    result = run(
        NewSession(
            session_name=name,
            start_directory=start_directory,
            environment=environment,
            width=width,
            height=height,
            capture_panes=True,
        ),
        engine,
        version=version,
    )
    result.raise_for_status()
    return SessionResult(
        session_id=result.new_id or "",
        name=name,
        first_window_id=result.first_window_id,
        first_pane_id=result.first_pane_id,
    )


def create_window(
    engine: TmuxEngine,
    target: str | Target,
    *,
    name: str | None = None,
    start_directory: str | None = None,
    version: str | None = None,
) -> WindowResult:
    """Create a window in a session (mirrors ``session.new_window``)."""
    result = run(
        NewWindow(
            target=resolve_target(target),
            name=name,
            start_directory=start_directory,
            capture_pane=True,
        ),
        engine,
        version=version,
    )
    result.raise_for_status()
    return WindowResult(
        window_id=result.new_id or "",
        name=name,
        first_pane_id=result.first_pane_id,
    )


def split_pane(
    engine: TmuxEngine,
    target: str | Target,
    *,
    horizontal: bool = False,
    start_directory: str | None = None,
    version: str | None = None,
) -> PaneResult:
    """Split a pane, creating a new one (mirrors ``window.split_window``)."""
    result = run(
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


def send_input(
    engine: TmuxEngine,
    target: str | Target,
    keys: str,
    *,
    enter: bool = False,
    literal: bool = False,
    suppress_history: bool = False,
    version: str | None = None,
) -> None:
    """Send keys to a pane (mirrors ``pane.send_keys``)."""
    run(
        SendKeys(
            target=resolve_target(target),
            keys=keys,
            enter=enter,
            literal=literal,
            suppress_history=suppress_history,
        ),
        engine,
        version=version,
    ).raise_for_status()


def capture_pane(
    engine: TmuxEngine,
    target: str | Target,
    *,
    start: int | None = None,
    end: int | None = None,
    join_wrapped: bool = False,
    trim_trailing: bool = False,
    version: str | None = None,
) -> PaneCapture:
    """Capture a pane's contents (mirrors ``pane.capture_pane``)."""
    result = run(
        CapturePane(
            target=resolve_target(target),
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


def list_sessions(engine: TmuxEngine, *, version: str | None = None) -> Listing:
    """List the server's sessions (mirrors ``server.sessions``)."""
    result = run(ListSessions(), engine, version=version)
    result.raise_for_status()
    return Listing(rows=result.rows)


def list_windows(
    engine: TmuxEngine,
    target: str | Target | None = None,
    *,
    all_windows: bool = False,
    version: str | None = None,
) -> Listing:
    """List windows of a session, or all windows (mirrors ``session.windows``)."""
    result = run(
        ListWindows(target=resolve_target(target), all_windows=all_windows),
        engine,
        version=version,
    )
    result.raise_for_status()
    return Listing(rows=result.rows)


def list_panes(
    engine: TmuxEngine,
    target: str | Target | None = None,
    *,
    all_panes: bool = False,
    version: str | None = None,
) -> Listing:
    """List panes of a window, or all panes (mirrors ``window.panes``)."""
    result = run(
        ListPanes(target=resolve_target(target), all_panes=all_panes),
        engine,
        version=version,
    )
    result.raise_for_status()
    return Listing(rows=result.rows)


def kill_pane(
    engine: TmuxEngine,
    target: str | Target,
    *,
    others: bool = False,
    version: str | None = None,
) -> None:
    """Kill a pane (or all others in its window with ``others=True``)."""
    run(
        KillPane(target=resolve_target(target), others=others),
        engine,
        version=version,
    ).raise_for_status()


def kill_window(
    engine: TmuxEngine,
    target: str | Target,
    *,
    others: bool = False,
    version: str | None = None,
) -> None:
    """Kill a window (or all others in its session with ``others=True``)."""
    run(
        KillWindow(target=resolve_target(target), others=others),
        engine,
        version=version,
    ).raise_for_status()


def kill_session(
    engine: TmuxEngine,
    target: str | Target,
    *,
    version: str | None = None,
) -> None:
    """Kill a session (mirrors ``session.kill``)."""
    run(
        KillSession(target=resolve_target(target)), engine, version=version
    ).raise_for_status()


def rename_window(
    engine: TmuxEngine,
    target: str | Target,
    name: str,
    *,
    version: str | None = None,
) -> None:
    """Rename a window (mirrors ``window.rename_window``)."""
    run(
        RenameWindow(target=resolve_target(target), name=name),
        engine,
        version=version,
    ).raise_for_status()


def rename_session(
    engine: TmuxEngine,
    target: str | Target,
    name: str,
    *,
    version: str | None = None,
) -> None:
    """Rename a session (mirrors ``session.rename_session``)."""
    run(
        RenameSession(target=resolve_target(target), name=name),
        engine,
        version=version,
    ).raise_for_status()


def select_layout(
    engine: TmuxEngine,
    target: str | Target,
    *,
    layout: str | None = None,
    version: str | None = None,
) -> None:
    """Apply a layout to a window (mirrors ``window.select_layout``)."""
    run(
        SelectLayout(target=resolve_target(target), layout=layout),
        engine,
        version=version,
    ).raise_for_status()


def select_pane(
    engine: TmuxEngine,
    target: str | Target,
    *,
    version: str | None = None,
) -> None:
    """Make a pane active (mirrors ``window.select_pane``)."""
    run(
        SelectPane(target=resolve_target(target)), engine, version=version
    ).raise_for_status()
