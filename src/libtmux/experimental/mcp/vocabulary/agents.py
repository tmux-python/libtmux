"""MCP tool surface for the AgentMonitor -- list, watch, and hook installation.

Three tools are registered on the FastMCP server by :func:`register_agents`:

- ``list_agents`` -- a snapshot of all currently tracked agents; no tmux
  round-trip, reads straight from the in-process store.
- ``watch_agents`` -- bounded stream collection: drains
  :meth:`~libtmux.experimental.agents.monitor.AgentMonitor.ingest` for up to
  *timeout_s* seconds and returns the state transitions observed.
- ``install_agent_hooks`` -- calls the named hook's
  :meth:`~libtmux.experimental.agents.hooks.base.AgentHook.install` and
  returns the hook's updated status.

This module mirrors the registration style of
:mod:`libtmux.experimental.mcp.events` (``FunctionTool.from_function`` +
``mcp.add_tool``) so the lifecycle is identical: tools are registered at
server-build time; the monitor is *started* by the caller (the lifespan) and
*stopped* on shutdown.  No unmanaged background task is spawned at import or
registration time.
"""

from __future__ import annotations

import asyncio
import typing as t

if t.TYPE_CHECKING:
    from fastmcp import FastMCP

    from libtmux.experimental.agents.monitor import AgentMonitor
    from libtmux.experimental.agents.store import Storage

# The methods AgentMonitor.start() drives on the engine. A streaming engine that
# only exposes subscribe() (enough for the event tools) is not enough for the
# monitor, whose start() also installs a subscription and sets attach targets.
_MONITOR_ENGINE_METHODS = ("subscribe", "add_subscription", "set_attach_targets")


def supports_monitor(engine: t.Any) -> bool:
    """Whether *engine* exposes the full control surface the monitor needs.

    The :class:`~libtmux.experimental.agents.monitor.AgentMonitor` drives more
    than ``subscribe()``: its :meth:`start` calls ``add_subscription`` and
    ``set_attach_targets``. Gating on this (rather than only ``subscribe``)
    avoids starting the monitor against a stream-only engine and crashing the
    lifespan with ``AttributeError``.

    Examples
    --------
    >>> class _Stream:
    ...     async def subscribe(self): ...
    >>> supports_monitor(_Stream())
    False
    >>> class _Full:
    ...     async def subscribe(self): ...
    ...     def add_subscription(self, spec): ...
    ...     def set_attach_targets(self, ids): ...
    >>> supports_monitor(_Full())
    True
    """
    return all(
        callable(getattr(engine, method, None)) for method in _MONITOR_ENGINE_METHODS
    )


def register_agents(
    mcp: FastMCP,
    engine: t.Any,
    *,
    sink: Storage | None = None,
    monitor: AgentMonitor | None = None,
) -> AgentMonitor:
    """Register ``list_agents``, ``watch_agents``, and ``install_agent_hooks`` on *mcp*.

    Registers the three MCP tools that expose an
    :class:`~libtmux.experimental.agents.monitor.AgentMonitor`, and returns the
    monitor so the caller (the server lifespan) can drive its
    :meth:`~libtmux.experimental.agents.monitor.AgentMonitor.start` /
    :meth:`~libtmux.experimental.agents.monitor.AgentMonitor.stop`. When
    *monitor* is ``None`` a fresh one is constructed (using *sink*); pass an
    existing instance to share the same monitor with the lifespan.

    Parameters
    ----------
    mcp : FastMCP
        The FastMCP server instance on which to register the tools.
    engine : object
        An async tmux engine with ``run``, ``subscribe``, ``add_subscription``,
        and ``set_attach_targets`` methods.
    sink : Storage or None
        Optional persistence sink forwarded to a freshly constructed monitor
        (ignored when *monitor* is provided).
    monitor : AgentMonitor or None
        An existing monitor to expose; when ``None`` one is constructed.

    Returns
    -------
    AgentMonitor
        The monitor backing the tools (not started by this call).

    Examples
    --------
    >>> class _FakeMcp:
    ...     def add_tool(self, tool): ...
    >>> class _FakeEngine:
    ...     async def run(self, req): ...
    ...     async def subscribe(self): ...
    ...     def add_subscription(self, spec): ...
    ...     def set_attach_targets(self, ids): ...
    >>> from libtmux.experimental.mcp.vocabulary.agents import register_agents
    >>> mon = register_agents(_FakeMcp(), _FakeEngine())
    >>> mon.status()
    {'agents': 0, 'generation': 0}
    """
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    from libtmux.experimental.agents.hooks.registry import get
    from libtmux.experimental.agents.monitor import AgentMonitor

    if monitor is None:
        monitor = AgentMonitor(engine, sink=sink)

    # ------------------------------------------------------------------
    # list_agents
    # ------------------------------------------------------------------

    async def list_agents() -> list[dict[str, t.Any]]:
        """Return a snapshot of all currently tracked agents.

        Reads directly from the in-process agent store -- no tmux round-trip.
        Each entry has ``pane_id``, ``name``, ``state`` (string value),
        ``since`` (monotonic timestamp), ``alive``, and ``source``.

        Returns
        -------
        list[dict[str, Any]]
            One dict per tracked agent pane.
        """
        return [
            {
                "pane_id": a.pane_id,
                "name": a.name,
                "state": a.state.value,
                "since": a.since,
                "alive": a.alive,
                "source": a.source,
            }
            for a in monitor.agents
        ]

    mcp.add_tool(
        FunctionTool.from_function(
            list_agents,
            name="list_agents",
            description="Snapshot of all currently tracked coding-agent panes",
            tags={"readonly", "agents"},
            annotations=ToolAnnotations(title="list_agents", readOnlyHint=True),
        ),
    )

    # ------------------------------------------------------------------
    # watch_agents
    # ------------------------------------------------------------------

    async def watch_agents(timeout_s: float = 5.0) -> dict[str, t.Any]:
        """Collect agent-state transitions for up to *timeout_s* seconds.

        Observes the monitor's live store over the window and returns any state
        changes. The monitor's own drain task is the sole ingester, so this only
        reads ``monitor.agents`` (no second subscription, no re-ingest) -- keeping
        the clock and ``since`` stamps accurate.

        Parameters
        ----------
        timeout_s : float
            Wall-clock seconds to observe before returning (default 5.0).

        Returns
        -------
        dict[str, Any]
            ``transitions`` -- list of ``{"pane_id", "before", "after"}`` dicts
            for agents whose state changed; ``count`` -- number of transitions.
        """
        snapshot_before = {a.pane_id: a.state.value for a in monitor.agents}
        await asyncio.sleep(timeout_s)
        snapshot_after = {a.pane_id: a.state.value for a in monitor.agents}
        transitions = [
            {
                "pane_id": pid,
                "before": snapshot_before.get(pid),
                "after": state,
            }
            for pid, state in snapshot_after.items()
            if snapshot_before.get(pid) != state
        ]
        return {"transitions": transitions, "count": len(transitions)}

    mcp.add_tool(
        FunctionTool.from_function(
            watch_agents,
            name="watch_agents",
            description=(
                "Collect agent-state transitions from the live tmux stream "
                "for up to timeout_s seconds"
            ),
            tags={"readonly", "agents"},
            annotations=ToolAnnotations(title="watch_agents", readOnlyHint=True),
        ),
    )

    # ------------------------------------------------------------------
    # install_agent_hooks
    # ------------------------------------------------------------------

    async def install_agent_hooks(agent: str) -> dict[str, t.Any]:
        """Install lifecycle hooks for the named coding agent.

        Calls :func:`~libtmux.experimental.agents.hooks.registry.get` to look
        up the hook installer, runs
        :meth:`~libtmux.experimental.agents.hooks.base.AgentHook.install`,
        then returns the hook's updated
        :meth:`~libtmux.experimental.agents.hooks.base.AgentHook.status`.

        Parameters
        ----------
        agent : str
            Hook name, e.g. ``"claude"`` or ``"codex"``.

        Returns
        -------
        dict[str, Any]
            ``{"agent": name, "status": "installed"|"outdated"|"absent"}``
            on success, or ``{"agent": name, "error": "unknown agent"}`` when
            *agent* is not registered.
        """
        try:
            hook = get(agent)
        except KeyError:
            return {"agent": agent, "error": "unknown agent"}

        def _install_and_status() -> str:
            hook.install()
            return hook.status()

        # install/status do blocking file I/O (read, fsync, atomic replace);
        # run off the event loop so concurrent MCP tools are not stalled.
        status = await asyncio.to_thread(_install_and_status)
        return {"agent": agent, "status": status}

    mcp.add_tool(
        FunctionTool.from_function(
            install_agent_hooks,
            name="install_agent_hooks",
            description=(
                "Install lifecycle hooks for a named coding agent (claude/codex)"
            ),
            tags={"mutating", "agents"},
            annotations=ToolAnnotations(
                title="install_agent_hooks", readOnlyHint=False
            ),
        ),
    )

    return monitor
