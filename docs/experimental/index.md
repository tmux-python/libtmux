(experimental)=

# Experimental API

```{warning}
Everything under {mod}`libtmux.experimental` is **not** covered by the
versioning policy and may change or be removed between any two releases.
```

`libtmux.experimental` separates an inert, typed operation from the engine that
executes it. An operation renders tmux arguments and declares its result and
effects; an engine returns the raw command outcome, and
{func}`~libtmux.experimental.ops.run` or
{func}`~libtmux.experimental.ops.arun` converts it to the operation's typed
result.

## Start here

- [Operations](operations/index.md) documents every registered command by
  Server, Session, Window, Pane, and Client scope.
- [Results](results.md) documents shared status and output fields plus each
  operation payload type.
- [Engines](engines.md) explains how to choose a transport without changing the
  operation contract.
- [Plans](plans.md) covers deferred execution, planners, and the fluent builder.

## Run one operation

{func}`~libtmux.experimental.ops.run` passes an operation value to an engine.
Inspect the returned result, or opt into an exception with
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status`:

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import HasSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> result = run(HasSession(target=SessionId(session.session_id)), engine)
>>> result.status, result.exists
('complete', True)
>>> result.raise_for_status() is result
True
```

```{toctree}
:hidden:

operations/index
results
engines
plans
```

## Agents

```{warning}
The agent-state monitor is experimental and subject to change without notice.
```

The `libtmux.experimental.agents` package gives you a live, server-side view
of every coding agent running across your tmux sessions.  A
{class}`~libtmux.experimental.agents.monitor.AgentMonitor` subscribes to a
control-mode engine, classifies incoming tmux notifications, and coalesces them
into a per-pane {class}`~libtmux.experimental.agents.state.Agent` record —
carrying the agent's name, its current {class}`~libtmux.experimental.agents.state.AgentState`
(`RUNNING`, `AWAITING_INPUT`, `IDLE`, `EXITED`, or `UNKNOWN`), the timestamp of
the last transition, and a liveness flag refreshed from the pane tree on each
reconcile.  A *local* pane whose process has exited is marked `EXITED`.  Remote
(SSH) panes have no local pid to probe, so they are left at their last-known
state and only become `EXITED` when their tmux pane disappears (no keepalive/TTL
in v1).

Agents report their state via tmux option subscriptions or OSC escape sequences.
When both signals arrive for the same pane the monitor applies a
last-writer-wins merge so the store stays consistent without locks.  On every
engine (re)connect the monitor runs a full-pane reconciliation — it lists all
panes, compares them against the stored snapshot, emits the minimal diff for
panes that vanished, and refreshes liveness — then re-subscribes to the
notification stream.  Because this runs on each reconnect (not on a fixed
timer), the monitor self-heals across a tmux restart or socket blip: a dropped
connection never leaves the store serving a stale snapshot.

```python
import asyncio

from libtmux import Server
from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine


async def main() -> None:
    engine = AsyncControlModeEngine.for_server(Server())
    monitor = AgentMonitor(engine)
    await monitor.start()
    try:
        for agent in monitor.agents:
            print(agent.pane_id, agent.state, "awaiting" if agent.is_awaiting else "")
    finally:
        await monitor.stop()


asyncio.run(main())
```

### Installing agent hooks

Before a coding agent can report state, its lifecycle hooks must be installed.
The {class}`~libtmux.experimental.agents.hooks.base.AgentHook` subclasses do not
touch tmux: `ClaudeCodeHook` merges hook entries into `~/.claude/settings.json`
and `CodexHook` into `~/.codex/config.toml`, leaving the rest of each file
untouched.  Every installed hook runs the `libtmux-agent-emit` console script on
the agent's lifecycle events, and that script is what writes the agent's state
to tmux — a per-pane `@agent_state` option locally, or an OSC 3008 escape
sequence over SSH — exactly the signals the monitor subscribes to.  The MCP tool
`install_agent_hooks` runs the matching installer on demand — pass `"claude"` or
`"codex"` as the agent name.

### MCP tools

When `libtmux-mcp` is running with the agent monitor wired in, three tools are
exposed to LLM clients:

- **`list_agents`** — returns a snapshot of every currently tracked agent:
  pane id, name, state string, seconds since last transition, and liveness.
- **`watch_agents`** — collects state-change events for a bounded window (default
  5 s) and returns them as a list, useful for agents that need to wait for a
  peer to reach `AWAITING_INPUT` before sending a message.
- **`install_agent_hooks`** — installs the named agent's shell hooks into the
  session so the monitor can begin receiving state signals.
