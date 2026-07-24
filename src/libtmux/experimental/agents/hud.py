"""Render the agent store into a floating HUD pane (tmux 3.7+).

A *pure* renderer: an :class:`~libtmux.experimental.agents.store.AgentStore`
becomes text, the text becomes a shell command that paints it into a pane, and
that command becomes a typed op. The :class:`~..monitor.AgentMonitor` drives it --
it creates a floating pane on start, repaints after each notification and
reconcile, and tears it down on stop. The renderer itself touches no tmux and no
engine, so it is fully unit-testable.

The paint command writes the frame and then holds the pane open at zero CPU
(``tail -f /dev/null``) so the frame stays visible until the next repaint.
"""

from __future__ import annotations

import shlex
import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops import RespawnPane
from libtmux.experimental.ops._types import PaneId

if t.TYPE_CHECKING:
    from libtmux.experimental.agents.store import AgentStore

#: Liveness glyphs; the state name carries the detail.
_ALIVE = "●"  # ●
_DEAD = "○"  # ○


def _hold_command(text: str) -> str:
    """Build a shell command that paints *text* into a pane and holds it open.

    ``clear`` wipes the prior frame, ``printf`` writes the rendered text
    (shell-quoted, so any content is safe), and ``exec tail -f /dev/null`` keeps
    the pane alive at zero CPU so the frame persists until the next repaint.
    """
    return f"clear; printf %s {shlex.quote(text)}; exec tail -f /dev/null"


@dataclass(frozen=True)
class HudRenderer:
    """Render an :class:`~..store.AgentStore` into floating-HUD pane content."""

    title: str = "agents"

    def render(self, store: AgentStore) -> str:
        """Render the store to the HUD's text frame (one line per agent).

        Examples
        --------
        >>> from libtmux.experimental.agents.store import AgentStore
        >>> frame = HudRenderer().render(AgentStore())
        >>> frame.startswith("agents") and "(no agents)" in frame
        True
        """
        agents = sorted(store.agents.values(), key=lambda agent: agent.pane_id)
        lines = [self.title, ""]
        if not agents:
            lines.append("(no agents)")
        for agent in agents:
            mark = _ALIVE if agent.alive else _DEAD
            name = agent.name or ""
            lines.append(
                f"{mark} {agent.state.value:<14} {agent.pane_id}  {name}".rstrip()
            )
        return "\n".join(lines) + "\n"

    def paint_command(self, store: AgentStore) -> str:
        """Return the shell command that paints the current store into a pane."""
        return _hold_command(self.render(store))

    def repaint_op(self, hud_pane_id: str, store: AgentStore) -> RespawnPane:
        """Build the typed op that repaints the HUD pane from the current store.

        Examples
        --------
        >>> from libtmux.experimental.agents.store import AgentStore
        >>> op = HudRenderer().repaint_op("%9", AgentStore())
        >>> op.command, op.kill
        ('respawn-pane', True)
        >>> op.render()[:3]
        ('respawn-pane', '-t', '%9')
        """
        return RespawnPane(
            target=PaneId(hud_pane_id),
            kill=True,
            shell=self.paint_command(store),
        )
