(experimental)=

# Experimental: operations & engines

```{warning}
Everything under {mod}`libtmux.experimental` is **not** covered by the
versioning policy and may change or be removed between any two releases.
```

`libtmux.experimental` hosts an inert, typed *operation* substrate and the
*engines* that execute it. An operation describes a tmux command (it renders
argv, carries its result type and metadata, and serializes) without dispatching;
an engine runs operations and returns typed results. The same operation returns
the same typed result whether executed by a subprocess, an in-memory simulator,
a persistent `tmux -C` control connection, or an async transport.

See ``tmux-python/libtmux`` issue 689 for the operationalization plan.

## Running an operation

An operation is a value; ``run`` (or ``arun`` for async) hands it to an engine
and returns the engine's typed result. Results never raise on construction --
inspect ``ok``/``status``, or opt into raising with ``raise_for_status()``:

```python
>>> from libtmux.experimental.ops import HasSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> from libtmux.experimental.engines import MockEngine
>>> result = run(HasSession(target=SessionId("$0")), MockEngine())
>>> result.ok
True
>>> result.raise_for_status() is result
True
```

How a *failed* result is treated is the engine's policy: the classic subprocess
path raises in its wrapper to match today's libtmux behavior, while the newer
engines hand the result back and let the caller decide.

## Choosing an engine

Every engine satisfies the same ``TmuxEngine`` (or ``AsyncTmuxEngine``)
protocol, so swapping engines never changes an operation or its result type --
only *how* and *where* the command runs.

| Engine | Transport | Use it for |
| --- | --- | --- |
| ``SubprocessEngine`` | one ``tmux`` process per command | the classic path; reproduces today's libtmux behavior |
| ``MockEngine`` | in-memory, no tmux | tests and dry runs (deterministic, fabricated output) |
| ``ControlModeEngine`` | a persistent ``tmux -C`` connection | many commands over one long-lived session |
| ``ImsgEngine`` | tmux's native binary peer protocol | an opt-in easter egg |

Each has an ``Async*`` counterpart (``AsyncSubprocessEngine``,
``AsyncMockEngine``, ``AsyncControlModeEngine``) behind ``AsyncTmuxEngine``.
Construct one directly, bind it to a live server with
``SubprocessEngine.for_server(server)``, or select one by name from the engine
registry:

```python
>>> from libtmux.experimental.engines import available_engines, create_engine
>>> from libtmux.experimental.ops import HasSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> available_engines()
('control_mode', 'imsg', 'mock', 'subprocess')
>>> engine = create_engine("mock")
>>> run(HasSession(target=SessionId("$0")), engine).status
'complete'
```

## Lazy plans and planners

A {class}`~libtmux.experimental.ops.plan.LazyPlan` records operations without
running them, returning a forward *slot reference* for each created object so a
later operation can target something that does not exist yet. ``execute``
(or ``aexecute``) resolves those references against captured ids as it goes:

```python
>>> from libtmux.experimental.ops import LazyPlan, SplitWindow, SendKeys
>>> from libtmux.experimental.ops._types import WindowId
>>> from libtmux.experimental.engines import MockEngine
>>> plan = LazyPlan()
>>> pane = plan.add(SplitWindow(target=WindowId("@1")))
>>> _ = plan.add(SendKeys(target=pane, keys="echo hi", enter=True))
>>> outcome = plan.execute(MockEngine())
>>> outcome.ok
True
>>> [r.status for r in outcome.results]
['complete', 'complete']
```

Operations also compose with ``>>`` into a chain, which a plan can run as one
dispatch when the members are chainable.

*How* a plan turns into dispatches is a pluggable
{class}`~libtmux.experimental.ops.planner.Planner`, so strategies can be A/B
tested against the same plan:

- ``SequentialPlanner`` -- one dispatch per operation (the default).
- ``FoldingPlanner`` -- folds adjacent chainable operations into a single
  ``;``-separated dispatch.
- ``MarkedPlanner`` -- folds a "create then decorate the new pane" run into one
  dispatch using tmux's ``{marked}`` register.

Every planner produces the same per-operation result; they differ only in how
many times tmux is invoked:

```python
>>> from libtmux.experimental.ops import LazyPlan, SplitWindow, SendKeys, FoldingPlanner
>>> from libtmux.experimental.ops._types import WindowId
>>> from libtmux.experimental.engines import MockEngine
>>> plan = LazyPlan()
>>> pane = plan.add(SplitWindow(target=WindowId("@1")))
>>> _ = plan.add(SendKeys(target=pane, keys="echo hi", enter=True))
>>> plan.execute(MockEngine(), planner=FoldingPlanner()).ok
True
```

## Building fluently with `plan()`

{func}`~libtmux.experimental.fluent.plan` is a fluent builder over a plan: you
name a session, walk down to a pane, and record what each pane runs, without
threading the new ids through yourself. Nothing touches tmux until
{meth}`~libtmux.experimental.fluent.PlanBuilder.run`, which folds the whole
description into a few dispatches (its async twin is ``arun``):

```python
>>> from libtmux.experimental.fluent import plan
>>> from libtmux.experimental.engines import MockEngine
>>> p = plan()
>>> pane = p.new_session("dev").window().pane()
>>> _ = pane.do(lambda c: c.send_keys("vim")).split().do(lambda c: c.send_keys("htop"))
>>> p.run(MockEngine()).ok
True
```

``.split()`` makes a new pane that does not exist yet, so it comes back as a
*forward* handle: you keep building on it, but reading its id is a static type
error (the concrete {class}`~libtmux.experimental.query.PaneRef` has
``.pane_id``; the {class}`~libtmux.experimental.query.ForwardPaneRef` does not),
resolved against the captured id only when the plan runs.

``run()`` folds by default and breaks the fold only at a true blocker -- a
created id a later op needs, or a host pause recorded by ``sleep()``/``wait()``.
{meth}`~libtmux.experimental.fluent.PlanBuilder.find_or_create_session` makes the
create conditional, so re-running a build reuses a live session instead of
duplicating it:

```python
>>> from libtmux.experimental.fluent import plan
>>> from libtmux.experimental.engines import MockEngine
>>> p = plan()
>>> _ = p.find_or_create_session("dev").window().pane()
>>> p.run(MockEngine()).ok
True
```

## Operation catalog

The catalog below is generated from the operation registry, so it always matches
the code.

```{tmuxop-catalog}
```

### Read-only operations

```{tmuxop-catalog}
:safety: readonly
```

### Destructive operations

```{tmuxop-catalog}
:safety: destructive
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
carrying the agent's name, its current
{class}`~libtmux.experimental.agents.state.AgentState` (`RUNNING`,
`AWAITING_INPUT`, `DONE`, `IDLE`, `EXITED`, or `UNKNOWN`), the timestamp of the
last transition, and a liveness flag refreshed from the pane tree on each
reconcile.  `DONE` means a turn completed and needs review, distinct from an
idle shell.  A *local* pane whose process has exited is marked `EXITED`.  Remote
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

When `libtmux-mcp` is running with the agent monitor wired in, these tools are
exposed to LLM clients:

- **`list_agents`** — returns a snapshot of every currently tracked agent:
  pane id, name, state string, seconds since last transition, and liveness.
- **`watch_agents`** — collects state-change events for a bounded window (default
  5 s) and returns them as a list, useful for agents that need to wait for a
  peer to reach `AWAITING_INPUT` before sending a message.
- **`wait_for_agent`** — blocks on the monitor's in-process store until a pane
  reaches a target state such as `AWAITING_INPUT` or `DONE`.
- **`send_to_agent`** — waits for `AWAITING_INPUT`, `DONE`, or `IDLE`, then sends
  a prompt through one folded tmux dispatch.
- **`install_agent_hooks`** — installs the named agent's shell hooks into the
  session so the monitor can begin receiving state signals.
