(experimental)=

# Experimental

:::{danger}
**No stability guarantee.** Everything under `libtmux._experimental` is **not**
covered by the project's versioning policy. It can change or be removed between
any releases without notice.

These APIs are published so the design can be exercised and reviewed before any
stability commitment. If you depend on something here and want it stabilized,
please [file an issue](https://github.com/tmux-python/libtmux/issues).
:::

## Chainable commands

`libtmux._experimental.chain` lets you build an ordered sequence of
typed tmux commands that runs as **one** native `tmux ... \; ...` invocation,
instead of one subprocess per command. The pieces layer up, so you can reach for
as much or as little as you need:

- **Intermediate representation** -- the typed argv layer beneath everything: a
  {class}`~libtmux._experimental.chain.ir.CommandCall` is a single
  command, and a
  {class}`~libtmux._experimental.chain.ir.CommandChain` is an
  ordered group that renders to one argv (with standalone `;` separators) and
  dispatches once.
- **Expressions** -- compose commands from a lazy, target-safe pane query. A
  {class}`~libtmux._experimental.chain.plan.PaneQuery` resolves
  against a pure
  {class}`~libtmux._experimental.chain.plan.TmuxSnapshot`, maps each
  typed row to commands, and compiles to one sequence -- so you can build and
  assert the result without touching tmux.
- **Async** -- {mod}`~libtmux._experimental.chain._async` mirrors the
  same query and dispatch API with `await`, while command construction stays
  synchronous and one expression still compiles to one invocation.
- **Connecting to live tmux sessions** -- the bridge to a real server:
  {func}`~libtmux._experimental.chain._connection.snapshot_from_session`
  reads live panes, and
  {class}`~libtmux._experimental.chain._connection.SessionPlanExecutor`
  (with its async counterpart
  {class}`~libtmux._experimental.chain._connection.AsyncSessionPlanExecutor`)
  resolves and runs an expression against a live {class}`~libtmux.Session` in one
  invocation.
- **Chainability** --
  {mod}`~libtmux._experimental.chain.chain` decides which commands
  may share one invocation: the static
  {attr}`~libtmux._experimental.chain.ir.CommandSpec.chainable`
  flag, plus a deferred result that won't hand back output until the chain has
  run.

::::{grid} 1 2 2 2
:gutter: 2 2 3 3

:::{grid-item-card} Intermediate representation
:link: api/libtmux._experimental.chain.ir
:link-type: doc
The typed argv layer: `CommandCall`, `CommandChain`, `CommandSpec`.
:::

:::{grid-item-card} Expressions
:link: api/libtmux._experimental.chain.plan
:link-type: doc
Build commands from a lazy, target-safe pane query.
:::

:::{grid-item-card} Async
:link: api/libtmux._experimental.chain._async
:link-type: doc
The same query and dispatch API, with `await`.
:::

:::{grid-item-card} Connecting to live tmux sessions
:link: api/libtmux._experimental.chain._connection
:link-type: doc
Read live panes and run an expression against a real session.
:::

:::{grid-item-card} Chainability
:link: api/libtmux._experimental.chain.chain
:link-type: doc
Which commands may share one invocation.
:::

::::

## At a glance

Compose typed calls and dispatch them as one tmux invocation:

```python
>>> from libtmux._experimental.chain.ir import CommandCall
>>> sequence = (
...     CommandCall("set-option", ("-g", "@cc_docs_a", "1"))
...     >> CommandCall("set-option", ("-g", "@cc_docs_b", "2"))
... )
>>> sequence.argv()
('set-option', '-g', '@cc_docs_a', '1', ';', 'set-option', '-g', '@cc_docs_b', '2')
>>> sequence.run(session.server).returncode
0
>>> session.server.cmd("show-option", "-gv", "@cc_docs_b").stdout
['2']
```

Build an expression from a query and compile it to one sequence -- pure, no tmux
required:

```python
>>> from libtmux._experimental.chain.plan import (
...     PaneRef,
...     PaneTarget,
...     SessionTarget,
...     TmuxSnapshot,
...     WindowTarget,
...     panes,
... )
>>> snapshot = TmuxSnapshot(
...     panes=(
...         PaneRef(PaneTarget("%1"), WindowTarget("@1"), SessionTarget("$0"),
...                 pane_index=0, active=True, title="editor"),
...         PaneRef(PaneTarget("%2"), WindowTarget("@1"), SessionTarget("$0"),
...                 pane_index=1, active=True, title="logs"),
...     ),
... )
>>> plan = (
...     panes()
...     .filter(active=True)
...     .order_by("pane_index")
...     .commands(lambda pane: pane.cmd.resize_pane(height=20))
... )
>>> plan.to_chain(snapshot).argvs()
(('resize-pane', '-t', '%1', '-y', '20'), ('resize-pane', '-t', '%2', '-y', '20'))
```

Against a live server, run the same expression in one invocation with
{class}`~libtmux._experimental.chain._connection.SessionPlanExecutor`:

```python
>>> from libtmux._experimental.chain import SessionPlanExecutor, panes
>>> runner = SessionPlanExecutor(session)
>>> live_plan = panes().filter(active=True).commands(
...     lambda pane: pane.cmd.send_keys("echo libtmux", enter=True),
... )
>>> live_plan.run(runner)
```

The same expression can be built and compiled asynchronously -- construction
stays synchronous; only resolution and dispatch await:

```python
>>> import asyncio
>>> from libtmux._experimental.chain import aio
>>> from libtmux._experimental.chain.plan import (
...     PaneRef,
...     PaneTarget,
...     SessionTarget,
...     TmuxSnapshot,
...     WindowTarget,
... )
>>> snapshot = TmuxSnapshot(
...     panes=(
...         PaneRef(PaneTarget("%1"), WindowTarget("@1"), SessionTarget("$0"),
...                 pane_index=0, active=True, title="editor"),
...     ),
... )
>>> async def _resize() -> tuple[tuple[str, ...], ...]:
...     plan = aio.panes().filter(active=True).commands(
...         lambda pane: pane.cmd.resize_pane(height=20),
...     )
...     return (await plan.to_chain(snapshot)).argvs()
>>> asyncio.run(_resize())
(('resize-pane', '-t', '%1', '-y', '20'),)
```

```{toctree}
:hidden:
:maxdepth: 1

api/libtmux._experimental.chain.ir
api/libtmux._experimental.chain.plan
api/libtmux._experimental.chain._async
api/libtmux._experimental.chain._connection
api/libtmux._experimental.chain.chain
```
