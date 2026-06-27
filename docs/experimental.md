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
>>> from libtmux.experimental.engines import ConcreteEngine
>>> result = run(HasSession(target=SessionId("$0")), ConcreteEngine())
>>> result.ok
True
>>> result.raise_for_status() is result
True
```

How a *failed* result is treated is the engine's policy: the classic subprocess
path raises in its facade to match today's libtmux behavior, while the newer
engines hand the result back and let the caller decide.

## Choosing an engine

Every engine satisfies the same ``TmuxEngine`` (or ``AsyncTmuxEngine``)
protocol, so swapping engines never changes an operation or its result type --
only *how* and *where* the command runs.

| Engine | Transport | Use it for |
| --- | --- | --- |
| ``SubprocessEngine`` | one ``tmux`` process per command | the classic path; reproduces today's libtmux behavior |
| ``ConcreteEngine`` | in-memory, no tmux | tests and dry runs (deterministic, fabricated output) |
| ``ControlModeEngine`` | a persistent ``tmux -C`` connection | many commands over one long-lived session |
| ``ImsgEngine`` | tmux's native binary peer protocol | an opt-in easter egg |

Each has an ``Async*`` counterpart (``AsyncSubprocessEngine``,
``AsyncConcreteEngine``, ``AsyncControlModeEngine``) behind ``AsyncTmuxEngine``.
Construct one directly, bind it to a live server with
``SubprocessEngine.for_server(server)``, or select one by name from the engine
registry:

```python
>>> from libtmux.experimental.engines import available_engines, create_engine
>>> from libtmux.experimental.ops import HasSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> available_engines()
('concrete', 'control_mode', 'imsg', 'subprocess')
>>> engine = create_engine("concrete")
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
>>> from libtmux.experimental.engines import ConcreteEngine
>>> plan = LazyPlan()
>>> pane = plan.add(SplitWindow(target=WindowId("@1")))
>>> _ = plan.add(SendKeys(target=pane, keys="echo hi", enter=True))
>>> outcome = plan.execute(ConcreteEngine())
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
>>> from libtmux.experimental.engines import ConcreteEngine
>>> plan = LazyPlan()
>>> pane = plan.add(SplitWindow(target=WindowId("@1")))
>>> _ = plan.add(SendKeys(target=pane, keys="echo hi", enter=True))
>>> plan.execute(ConcreteEngine(), planner=FoldingPlanner()).ok
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
carrying the agent's name, its current {class}`~libtmux.experimental.agents.state.AgentState`
(`RUNNING`, `AWAITING_INPUT`, `IDLE`, `EXITED`, or `UNKNOWN`), the timestamp of
the last transition, and a liveness flag updated by a periodic health probe.

Agents report their state via tmux option subscriptions or OSC escape sequences.
When both signals arrive for the same pane the monitor applies a
last-writer-wins merge so the store stays consistent without locks.  A full-pane
reconciliation sweep runs every few seconds to catch any pane the stream missed,
compare it against the stored snapshot, and emit the minimal diff — so the
monitor self-heals across reconnects and supervisor restarts.

### Installing agent hooks

Before a coding agent can report state, its shell hooks must be installed into
the tmux session.  {class}`~libtmux.experimental.agents.hooks.base.AgentHook`
subclasses (`ClaudeCodeHook`, `CodexHook`) write the necessary `after-*` hooks
into the running session via a tmux `set-hook` call.  The MCP tool
`install_agent_hooks` does this on demand — pass `"claude"` or `"codex"` as the
agent name and the tool installs the hooks in the monitor's target session.

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
