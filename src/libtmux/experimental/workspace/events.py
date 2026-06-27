"""Build events emitted by the workspace runner as it constructs a session.

These mirror tmuxp's ``on_build_event`` hooks: a structural stream (session ->
windows -> panes -> built) derived from the bound ids as the compiled plan runs,
so a caller can drive an incremental UI without polling tmux. The events live in
the *Declarative* tier -- the runner emits them; the Core
:class:`~libtmux.experimental.ops.plan.LazyPlan` stays observer-free.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

if t.TYPE_CHECKING:
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.results import Result


@dataclass(frozen=True)
class SessionCreated:
    """The session was created."""

    session_id: str


@dataclass(frozen=True)
class WindowCreated:
    """A window was created (a fresh window, or the reused first window bound)."""

    window_id: str


@dataclass(frozen=True)
class PaneCreated:
    """A pane was created (a window's first pane, or a split)."""

    pane_id: str


@dataclass(frozen=True)
class WorkspaceBuilt:
    """The whole workspace finished building."""

    session_id: str


#: A build event in the order the runner emits them.
BuildEvent = SessionCreated | WindowCreated | PaneCreated | WorkspaceBuilt


def events_for(op: Operation[t.Any], result: Result) -> list[BuildEvent]:
    """Derive the build events from one executed operation and its result.

    A creator binds its own id plus any implicit children (a new session's first
    window/pane, a new window's first pane), so one op can yield several events.

    Examples
    --------
    >>> from libtmux.experimental.ops import NewWindow
    >>> op = NewWindow(capture_pane=True)
    >>> result = op.build_result(returncode=0, stdout=("@5 %6",))
    >>> events_for(op, result)
    [WindowCreated(window_id='@5'), PaneCreated(pane_id='%6')]
    """
    events: list[BuildEvent] = []
    if op.kind == "new_session":
        if result.created_id is not None:
            events.append(SessionCreated(result.created_id))
        subids = result.created_subids
        if "window" in subids:
            events.append(WindowCreated(subids["window"]))
        if "pane" in subids:
            events.append(PaneCreated(subids["pane"]))
    elif op.kind == "new_window":
        if result.created_id is not None:
            events.append(WindowCreated(result.created_id))
        if "pane" in result.created_subids:
            events.append(PaneCreated(result.created_subids["pane"]))
    elif op.kind == "split_window" and result.created_id is not None:
        events.append(PaneCreated(result.created_id))
    return events
