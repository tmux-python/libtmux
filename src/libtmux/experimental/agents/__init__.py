"""Agent-state monitoring and synchronization over tmux (experimental).

The monitor (:class:`AgentMonitor`) tracks what every coding agent is doing; the
synchronization verbs act on that knowledge: :func:`wait_for_agent_state` /
:func:`wait_for_agents` block until agents reach a state (zero tmux calls), and
:func:`send_to_agent` / :func:`send_to_agents` drive them safely under a per-pane
:func:`pane_lock`, folding each send to a single tmux dispatch.
"""

from __future__ import annotations

from libtmux.experimental.agents.drive import (
    SendOutcome,
    pane_lock,
    send_to_agent,
    send_to_agents,
)
from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.state import Agent, AgentState, AgentTransition
from libtmux.experimental.agents.statusline import (
    DEFAULT_LABELS,
    paint_status_line,
    render_status_line,
    status_line_op,
)
from libtmux.experimental.agents.wait import (
    AgentWait,
    WaitReason,
    wait_for_agent_state,
    wait_for_agents,
)

__all__ = (
    "DEFAULT_LABELS",
    "Agent",
    "AgentMonitor",
    "AgentState",
    "AgentTransition",
    "AgentWait",
    "SendOutcome",
    "WaitReason",
    "paint_status_line",
    "pane_lock",
    "render_status_line",
    "send_to_agent",
    "send_to_agents",
    "status_line_op",
    "wait_for_agent_state",
    "wait_for_agents",
)
