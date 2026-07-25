# Compare imsg with subprocess execution

{class}`~libtmux.experimental.engines.imsg.base.ImsgEngine` uses tmux's native
binary protocol on POSIX. A useful parity check binds it and
{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` to the same
private server, sends the same raw request, and compares a narrow observable.

## Bind both engines explicitly

`ImsgEngine` has no `for_server()` helper. Include the server's `-L` socket name
or `-S` socket path in every
{class}`~libtmux.experimental.engines.base.CommandRequest`. The subprocess
engine accepts the same global argument in the request, which keeps the
comparison exact.

```python
>>> from libtmux.experimental.engines import CommandRequest, ImsgEngine
>>> from libtmux.experimental.engines import SubprocessEngine
>>> assert session.session_id is not None
>>> if server.socket_name is not None:
...     prefix = (f"-L{server.socket_name}",)
... else:
...     socket_path = server.cmd(
...         "display-message", "-p", "#{socket_path}"
...     ).stdout[0]
...     prefix = (f"-S{socket_path}",)
>>> request = CommandRequest.from_args(
...     *prefix,
...     "display-message",
...     "-p",
...     "-t",
...     session.session_id,
...     "#{session_id}",
... )
>>> imsg_result = ImsgEngine().run(request)
>>> cli_result = SubprocessEngine().run(request)
>>> (
...     imsg_result.returncode == cli_result.returncode,
...     imsg_result.stdout == cli_result.stdout,
...     imsg_result.stderr == cli_result.stderr,
... )
(True, True, True)
>>> imsg_result.stdout[0] == session.session_id
True
```

## Interpret the result narrowly

This proves one query against one server. It does not prove command-wide parity,
cross-version compatibility, or portability. The current codec supports
protocol v8; unsupported protocol negotiation, socket framing, and descriptor
handling have their own failure paths. Local queries and commands that must
start a missing server use the tmux binary; commands dispatched to an existing
server still use the socket, including commands that spawn a shell there.
