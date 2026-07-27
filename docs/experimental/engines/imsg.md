# Imsg engine

{class}`~libtmux.experimental.engines.imsg.base.ImsgEngine` speaks tmux's native
binary peer protocol over a Unix socket.

## Use it when

Use it on POSIX systems for narrow protocol experiments and direct comparisons
against the CLI engine at a known tmux protocol version.

## Avoid it when

Do not treat it as a portable replacement for the tmux CLI or as a universal
parity guarantee. The implementation currently supports protocol v8 and relies
on POSIX sockets, file descriptors, and process APIs.

## Construction and cleanup

Construct it directly, optionally with `protocol_version`. Socket-dispatched
requests open and close their own connection, so the engine has no close
method. Local queries and commands that must start a missing server use the
tmux binary instead. Unlike the subprocess and control-mode engines, it has no
`for_server()` helper. Put a private server's raw `-L` or `-S` global argument
in every
{class}`~libtmux.experimental.engines.base.CommandRequest`.

```python
>>> from libtmux.experimental.engines import CommandRequest, ImsgEngine
>>> assert server.socket_name is not None
>>> assert session.session_id is not None
>>> request = CommandRequest.from_args(
...     f"-L{server.socket_name}",
...     "display-message",
...     "-p",
...     "-t",
...     session.session_id,
...     "#{session_id}",
... )
>>> result = ImsgEngine().run(request)
>>> result.returncode, result.stdout == (session.session_id,)
(0, True)
```

## Lifecycle and failure boundary

{meth}`~libtmux.experimental.engines.imsg.base.ImsgEngine.run_batch` calls
{meth}`~libtmux.experimental.engines.imsg.base.ImsgEngine.run` for each request
in order. Each socket-dispatched command gets a fresh connection; local
queries, `start-server`, and server-starting commands such as `new-session`
against a missing server use the tmux binary. Missing or lost servers become
failed command results. Unsupported protocol negotiation, framing, codec, and
unexpected socket setup failures raise at the engine boundary.

## API

```{eval-rst}
.. autoclass:: libtmux.experimental.engines.imsg.base.ImsgEngine
   :members:
```

## Related tutorial

See {doc}`../tutorials/imsg-parity` for an explicit private-server binding and a
bounded CLI comparison.
