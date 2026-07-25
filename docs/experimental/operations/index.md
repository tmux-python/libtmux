# Operations

Operations are immutable command descriptions. Each page below documents the
Python constructor, tmux command, result type, version gates, safety, and
effects directly from the operation registry.

## Execution contract

An engine emits a raw
{class}`~libtmux.experimental.engines.base.CommandResult`.
{func}`~libtmux.experimental.ops.run` converts it to the operation's declared
{class}`~libtmux.experimental.ops.results.Result` subtype. Results preserve
failures as data; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` when the
calling boundary requires an exception.

Examples use {class}`~libtmux.experimental.engines.mock.MockEngine` so every
page tests deterministically without depending on ambient tmux state. The
failure section on each page identifies what a mock cannot prove about a live
server.

## Browse by tmux object

- [Server operations](server/index.md) manage server-wide state, buffers, and
  hierarchy discovery.
- [Session operations](session/index.md) manage a session and its windows.
- [Window operations](window/index.md) manage windows, layouts, and pane
  placement.
- [Pane operations](pane/index.md) manage terminal input, output, and geometry.
- [Client operations](client/index.md) manage attached tmux clients.

```{toctree}
:hidden:

server/index
session/index
window/index
pane/index
client/index
```
