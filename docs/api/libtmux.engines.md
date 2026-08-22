(engines-api)=

# Engines

An *engine* is the object that actually runs a tmux command. Every dispatch in
libtmux — {meth}`Server.cmd() <libtmux.Server.cmd>`, the listing queries behind
{attr}`~libtmux.Server.sessions`, and {meth}`Server.raise_if_dead()
<libtmux.Server.raise_if_dead>` — goes through one, and by default that is
{class}`~libtmux.engines.subprocess.SubprocessEngine`, which forks the tmux
binary exactly as libtmux always has.

The engine is swappable. Pass `engine=` to {class}`~libtmux.Server` and every
command on that server runs through your object instead, which is how you drive
libtmux against a recorded or in-memory tmux without a running server.

See {ref}`engines` for the guide, with worked examples.

Every symbol below is re-exported from `libtmux.engines`, so
`from libtmux.engines import SubprocessEngine` works regardless of which
submodule defines it.

## Requests and results

A {class}`~libtmux.engines.base.CommandRequest` is a rendered tmux argv; a
{class}`~libtmux.engines.base.CommandResult` is the structured outcome. A
tmux-side failure is *data* here — it sets `returncode` and `stderr` rather than
raising. Only an engine-broken condition (missing binary, lost connection)
raises.

{class}`~libtmux.engines.base.TmuxEngine` is a {class}`typing.Protocol`, so any
object with `run()` and `run_batch()` is an engine; there is no base class to
inherit. The `Supports*` protocols are optional capabilities an engine may
also implement.

```{eval-rst}
.. automodule:: libtmux.engines.base
   :members:
```

## Connections

A {class}`~libtmux.engines.connection.ServerConnection` is the pair every engine
needs before it can dispatch anything: which tmux *binary* to run, and the
connection flags (`-L`/`-S`/`-f`/`-2`/`-8`) naming one tmux server. It is the
single place either is computed.

```{eval-rst}
.. automodule:: libtmux.engines.connection
   :members:
```

## The default engine

```{eval-rst}
.. automodule:: libtmux.engines.subprocess
   :members:
```

## Async

```{eval-rst}
.. automodule:: libtmux.engines.asyncio
   :members:
```

## Recording and replay

```{eval-rst}
.. automodule:: libtmux.engines.record
   :members:
```

## Resolving an engine by name

An application that reads its transport from a config file or a CLI flag can
name it instead of importing it. A third-party distribution adds a name by
advertising it in the `libtmux.engines` entry-point group; entry points are read
on first use, not at import.

```{eval-rst}
.. automodule:: libtmux.engines.registry
   :members:
```
