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

The `libtmux._experimental.chain` package lets you author an ordered
sequence of typed tmux commands that compiles to **one** native
`tmux ... \; ...` invocation and dispatches once -- instead of issuing one
subprocess per command. It grows in layers:

- **IR** -- the immutable argv intermediate representation: a
  {class}`~libtmux._experimental.chain.ir.CommandCall` is one typed
  command; a {class}`~libtmux._experimental.chain.ir.CommandChain`
  is an ordered group that renders to a single argv with standalone `;`
  separators and dispatches once.
- **Plan** -- a typed, target-safe deferred query: a lazy
  {class}`~libtmux._experimental.chain.plan.PaneQuery` resolves
  against a pure {class}`~libtmux._experimental.chain.plan.TmuxSnapshot`,
  maps each typed row to commands, and compiles to one sequence.
- **Async facade** -- {mod}`~libtmux._experimental.chain._async` wraps
  the same engine so snapshot resolution and dispatch are awaitable, while
  command construction stays sync and one plan still compiles to one dispatch.
- **Adapters** -- the live-tmux bridge:
  {func}`~libtmux._experimental.chain._connection.snapshot_from_session`
  reads real panes, and
  {class}`~libtmux._experimental.chain._connection.SessionPlanExecutor`
  (plus its async sibling
  {class}`~libtmux._experimental.chain._connection.AsyncSessionPlanExecutor`)
  resolves and dispatches a plan against a real server in one invocation.

::::{grid} 1 2 2 2
:gutter: 2 2 3 3

:::{grid-item-card} Command IR
:link: api/libtmux._experimental.chain.ir
:link-type: doc
Immutable argv primitives: `CommandCall`, `CommandChain`, `CommandSpec`.
:::

:::{grid-item-card} Deferred plan
:link: api/libtmux._experimental.chain.plan
:link-type: doc
Typed target-safe queries that compile to one command sequence.
:::

:::{grid-item-card} Async facade
:link: api/libtmux._experimental.chain._async
:link-type: doc
Awaitable snapshot + dispatch over the same engine, one dispatch per plan.
:::

:::{grid-item-card} Live-tmux adapters
:link: api/libtmux._experimental.chain._connection
:link-type: doc
`snapshot_from_session`, `SessionPlanExecutor`, `AsyncSessionPlanExecutor`.
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

Resolve a typed query against a snapshot and compile it to one sequence -- pure,
no tmux required:

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

Against a live server, dispatch the same plan in one invocation with
{class}`~libtmux._experimental.chain._connection.SessionPlanExecutor`:

```python
>>> from libtmux._experimental.chain import SessionPlanExecutor, panes
>>> runner = SessionPlanExecutor(session)
>>> live_plan = panes().filter(active=True).commands(
...     lambda pane: pane.cmd.send_keys("echo libtmux", enter=True),
... )
>>> live_plan.run(runner)
```

The same plan can be authored and compiled asynchronously -- construction stays
sync, only snapshot resolution and dispatch await:

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
```
