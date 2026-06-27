"""The agent-state vocabulary: the AgentState enum and the Agent record."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class AgentState(str, enum.Enum):
    """What a coding agent in a pane is doing.

    Examples
    --------
    >>> AgentState.from_signal("running")
    <AgentState.RUNNING: 'running'>
    >>> AgentState.from_signal("nonsense")
    <AgentState.UNKNOWN: 'unknown'>
    """

    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    IDLE = "idle"
    EXITED = "exited"
    UNKNOWN = "unknown"

    @classmethod
    def from_signal(cls, value: str) -> AgentState:
        """Map a hook's raw state string to an :class:`AgentState`.

        Unrecognized values become :attr:`UNKNOWN` rather than raising, so a
        malformed signal can never crash the monitor.

        Examples
        --------
        >>> AgentState.from_signal("AWAITING_INPUT")
        <AgentState.AWAITING_INPUT: 'awaiting_input'>
        >>> AgentState.from_signal("garbage")
        <AgentState.UNKNOWN: 'unknown'>
        """
        try:
            return cls(value.strip().lower())
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class Agent:
    """A pane's coding agent and its current state.

    Examples
    --------
    >>> a = Agent(pane_id="%1", key="%1", name="claude",
    ...           state=AgentState.RUNNING, since=1.0, source="option",
    ...           pid=42, alive=True)
    >>> a.is_running, a.is_awaiting
    (True, False)
    """

    pane_id: str
    key: str
    name: str | None
    state: AgentState
    since: float
    source: str
    pid: int | None
    alive: bool

    @property
    def is_awaiting(self) -> bool:
        """True when the agent is paused waiting on the human/orchestrator.

        Examples
        --------
        >>> Agent(pane_id="%1", key="%1", name="claude",
        ...       state=AgentState.AWAITING_INPUT, since=1.0, source="option",
        ...       pid=42, alive=True).is_awaiting
        True
        """
        return self.state is AgentState.AWAITING_INPUT

    @property
    def is_running(self) -> bool:
        """True when the agent is actively working.

        Examples
        --------
        >>> Agent(pane_id="%1", key="%1", name="claude",
        ...       state=AgentState.RUNNING, since=1.0, source="option",
        ...       pid=42, alive=True).is_running
        True
        """
        return self.state is AgentState.RUNNING
