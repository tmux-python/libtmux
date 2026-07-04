"""Read-side status projections for declared workspaces."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.query import ATTENTION

if t.TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from libtmux.experimental.agents.monitor import AgentMonitor
    from libtmux.experimental.agents.state import Agent, AgentState
    from libtmux.experimental.models import ServerSnapshot
    from libtmux.experimental.models.snapshots import SessionSnapshot
    from libtmux.experimental.workspace.ir import Workspace

AgentSource = t.Union["AgentMonitor", "Sequence[Agent]"]


@dataclass(frozen=True)
class WorkspaceStatus:
    """Status for one declared workspace against a live server snapshot."""

    name: str
    exists: bool
    session_id: str | None = None
    windows: int = 0
    panes: int = 0
    agents: tuple[Agent, ...] = ()
    agent_state: AgentState | None = None


def _agent_rows(source: AgentSource) -> tuple[Agent, ...]:
    """Resolve an agent source without making a tmux call."""
    store_agents = getattr(source, "agents", None)
    if store_agents is not None:
        return tuple(store_agents)
    return tuple(t.cast("Sequence[Agent]", source))


def _session_pane_ids(session: SessionSnapshot) -> set[str]:
    """Return the pane ids contained in *session*."""
    return {pane.pane_id for window in session.windows for pane in window.panes}


def _agent_state(rows: Iterable[Agent]) -> AgentState | None:
    """Return the most urgent state for *rows*, or ``None`` when empty."""
    agents = tuple(rows)
    if not agents:
        return None
    return max(agents, key=lambda agent: ATTENTION.get(agent.state, -1)).state


def workspace_status(
    workspaces: Iterable[Workspace],
    snapshot: ServerSnapshot,
    agents_source: AgentSource = (),
) -> tuple[WorkspaceStatus, ...]:
    """Project declared workspaces against a server snapshot and agent records.

    The projection is pure: callers can feed one
    :class:`~libtmux.experimental.models.ServerSnapshot` and an in-process
    agent store, then refresh UI state repeatedly with zero tmux calls.

    Examples
    --------
    >>> from libtmux.experimental.models import ServerSnapshot
    >>> from libtmux.experimental.workspace import Window, Workspace
    >>> snap = ServerSnapshot.from_pane_rows([
    ...     {"session_id": "$1", "session_name": "dev", "window_id": "@1",
    ...      "pane_id": "%1"},
    ... ])
    >>> workspace_status([Workspace("dev", windows=[Window("w")])], snap)[0].exists
    True
    """
    by_name = {session.name: session for session in snapshot.sessions}
    agents = _agent_rows(agents_source)
    statuses: list[WorkspaceStatus] = []
    for workspace in workspaces:
        session = by_name.get(workspace.name)
        if session is None:
            statuses.append(WorkspaceStatus(name=workspace.name, exists=False))
            continue
        pane_ids = _session_pane_ids(session)
        session_agents = tuple(agent for agent in agents if agent.pane_id in pane_ids)
        statuses.append(
            WorkspaceStatus(
                name=workspace.name,
                exists=True,
                session_id=session.session_id,
                windows=len(session.windows),
                panes=sum(len(window.panes) for window in session.windows),
                agents=session_agents,
                agent_state=_agent_state(session_agents),
            ),
        )
    return tuple(statuses)
