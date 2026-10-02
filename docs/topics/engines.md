(engines)=

# Engines

Every tmux command libtmux runs goes through an **engine**. An engine takes a
rendered argv and returns a structured result — that is its whole job.

By default that engine is
{class}`~libtmux.engines.subprocess.SubprocessEngine`, which forks the tmux
binary once per command. You never have to know it exists. But because it is a
seam rather than hard-wired code, you can replace it — to test without tmux
running, to record what libtmux would do, or to point one `Server` at a
different tmux binary than another.

## The default path

Nothing changes if you ignore engines entirely:

```python
>>> server.cmd("display-message", "-p", "#{session_name}").stdout
['libtmux_...']
```

Under that call, {class}`~libtmux.Server` built a
{class}`~libtmux.engines.connection.ServerConnection` from its own
`socket_name`, `socket_path`, `config_file`, and `colors`, handed it to a
`SubprocessEngine`, and asked the engine to run the command:

```python
>>> from libtmux.engines import SubprocessEngine
>>> server.connection.args
('-L...',)
>>> isinstance(server.engine, SubprocessEngine)
True
```

The connection is *derived*, not frozen at construction, so moving a server to a
different socket is picked up on the next command:

```python
>>> from libtmux.server import Server
>>> tmux = Server(socket_name="engines_doc_a")
>>> tmux.connection.args
('-Lengines_doc_a',)
>>> tmux.socket_name = "engines_doc_b"
>>> tmux.connection.args
('-Lengines_doc_b',)
```

## Requests and results

An engine speaks two value types.
{class}`~libtmux.engines.base.CommandRequest` is the argv *after* the binary and
connection flags. {class}`~libtmux.engines.base.CommandResult` is what came
back.

```python
>>> from libtmux.engines import CommandRequest
>>> CommandRequest.from_args("kill-window", "-t", 2)
CommandRequest(args=('kill-window', '-t', '2'), tmux_bin=None, timeout=None)
```

A tmux-side failure is **data**, not an exception. An engine sets `returncode`
and `stderr`; it does not raise. Only an engine-broken condition — a missing
binary, a dropped connection — raises:

```python
>>> from libtmux.engines import CommandResult
>>> result = CommandResult(
...     cmd=("tmux", "kill-window"),
...     stderr=("no such window",),
...     returncode=1,
... )
>>> result.returncode, result.stderr
(1, ('no such window',))
```

### Bounding a command and sending stdin

A request can carry two more things. `timeout` is a number of seconds; when it
passes, the engine raises {exc}`~libtmux.exc.TmuxTimeout` instead of waiting.
A subprocess engine kills the tmux client it started and reaps it. A
control-mode engine abandons the reply and keeps its connection. `None`, the
default, waits as long as tmux takes. The exception is deliberately not a
{exc}`~libtmux.exc.LibTmuxException`, so the list accessors that read one as
"nothing to list" cannot hide a hung server.

`input` is data for the client's standard input, for commands that read `-`,
such as `load-buffer`. It is not subject to tmux's 16 KiB limit on arguments,
and `bytes` are sent unchanged.

```python
>>> from libtmux import exc
>>> from libtmux.engines import CommandRequest, SubprocessEngine
>>> engine = SubprocessEngine.for_server(server)
>>> engine.run(
...     CommandRequest.from_args(
...         "load-buffer", "-b", "doc_input", "-", input=b"payload"
...     )
... ).ok
True
>>> engine.run(CommandRequest.from_args("show-buffer", "-b", "doc_input")).stdout
('payload',)
>>> try:
...     engine.run(CommandRequest.from_args("run-shell", "sleep 5", timeout=0.25))
... except exc.TmuxTimeout as error:
...     print(error.timeout)
0.25
```

{meth}`Server.cmd() <libtmux.Server.cmd>` and the `cmd()` methods of the other
objects take the same `timeout=` and `input=` keywords.

## Writing an engine

{class}`~libtmux.engines.base.TmuxEngine` is a {class}`typing.Protocol`. There
is no base class to inherit — any object with `run()` and `run_batch()` is an
engine.

`run()` and the optional `command_line()` must be synchronous: libtmux
dispatches every command from ordinary, non-`async` code and cannot await a
coroutine. Because {class}`~libtmux.engines.base.TmuxEngine` is checked by name
only, an `async def run()` satisfies it and would otherwise fail much later,
with a bare `AttributeError` naming neither the engine nor the mismatch:

```python
>>> from libtmux.engines import CommandResult
>>> from libtmux.server import Server

>>> class AsyncEngine:
...     async def run(self, request):
...         return CommandResult(cmd=("tmux", *request.args))
...     def run_batch(self, requests):
...         return [self.run(request) for request in requests]

>>> Server(engine=AsyncEngine()).cmd("display-message", "-p", "#S")
Traceback (most recent call last):
    ...
libtmux.exc.AsyncEngineMismatch: AsyncEngine.run() returned an awaitable: ...
```

Await such an engine from your own async code instead, or write a synchronous
`run()`.

Here is a complete one that runs nothing, records everything, and answers from a
canned script. Hand it to a server and no tmux process is involved:

```python
>>> from libtmux.engines import CommandResult
>>> from libtmux.server import Server

>>> class RecordingEngine:
...     """Record every dispatch; answer from a canned script."""
...
...     def __init__(self, stdout=()):
...         self.requests = []
...         self._stdout = tuple(stdout)
...
...     def run(self, request):
...         self.requests.append(request.args)
...         return CommandResult(cmd=("tmux", *request.args), stdout=self._stdout)
...
...     def run_batch(self, requests):
...         return [self.run(request) for request in requests]

>>> recorder = RecordingEngine(stdout=("my_session",))
>>> offline = Server(engine=recorder)
>>> offline.cmd("display-message", "-p", "#{session_name}").stdout
['my_session']
>>> recorder.requests
[('display-message', '-p', '#{session_name}')]
```

This works because the socket flags live on the *engine*, not in the request, so
your `run()` only ever sees the tmux subcommand — never a `-L` to parse back
out:

```python
>>> from libtmux.engines import CommandResult
>>> from libtmux.server import Server

>>> class Recorder:
...     def __init__(self):
...         self.requests = []
...     def run(self, request):
...         self.requests.append(request.args)
...         return CommandResult(cmd=("tmux", *request.args))
...     def run_batch(self, requests):
...         return [self.run(request) for request in requests]

>>> recorder = Recorder()
>>> _ = Server(socket_name="engines_doc_scoped", engine=recorder).cmd("list-sessions")
>>> recorder.requests
[('list-sessions',)]
```

## Injected engines and sockets

An engine that names no tmux server of its own **adopts** the server's
connection. Without that rule, injecting a bare engine into a socket-scoped
server would silently dispatch to whichever server a flagless `tmux` reaches:

```python
>>> from libtmux.engines import SubprocessEngine
>>> from libtmux.server import Server
>>> scoped = Server(socket_name="engines_doc_c", engine=SubprocessEngine())
>>> scoped.engine.server_args
('-Lengines_doc_c',)
```

An engine that *does* name a server is left exactly as you built it:

```python
>>> from libtmux.engines import SubprocessEngine
>>> from libtmux.server import Server
>>> pinned = SubprocessEngine.of(server_args=("-Lengines_doc_pinned",))
>>> Server(socket_name="engines_doc_c", engine=pinned).engine.server_args
('-Lengines_doc_pinned',)
```

An in-memory engine has no connection at all, so neither rule applies and it is
used untouched.

## Optional capabilities

An engine may implement extra protocols. Each is optional; libtmux checks with
{func}`isinstance` and degrades gracefully when absent.

{class}`~libtmux.engines.base.SupportsCommandLine` renders the argv an engine
*would* run, which is how the full command line reaches the debug log before
dispatch. {class}`~libtmux.engines.base.SupportsConnection` marks an engine that
dispatches over a named server and can be rebound — the protocol behind the
adoption rule above.

```python
>>> from libtmux.engines import (
...     SubprocessEngine,
...     SupportsCommandLine,
...     SupportsConnection,
... )
>>> engine = SubprocessEngine()
>>> isinstance(engine, SupportsCommandLine), isinstance(engine, SupportsConnection)
(True, True)
```

An engine that implements neither simply is not matched:

```python
>>> from libtmux.engines import CommandResult, SupportsCommandLine
>>> class Bare:
...     def run(self, request):
...         return CommandResult(cmd=("tmux", *request.args))
...     def run_batch(self, requests):
...         return [self.run(request) for request in requests]
>>> isinstance(Bare(), SupportsCommandLine)
False
```

{class}`~libtmux.engines.base.SupportsTmuxVersion` reports the tmux version an
engine targets, which a caller rendering version-gated argv reads to decide
whether a flag is safe to send. An engine that cannot know its version — an
in-memory fake — omits it, and the caller assumes the newest tmux.

## Explicit command separators

tmux treats a bare `;` argument as a boundary between two commands, but only
when it arrives unquoted. A `;` that is *data* — a pane title, a shell fragment
bound for `send-keys` — must not be mistaken for one. Guessing from the string
alone cannot tell them apart, so the intent rides in the type:
{class}`~libtmux.engines.base.CommandSeparator` marks a real boundary, and
{func}`~libtmux.engines.base.is_command_separator` finds it.

```python
>>> from libtmux.engines import CommandRequest, CommandSeparator, is_command_separator
>>> request = CommandRequest.from_args(
...     "rename-window", "a;b", CommandSeparator(";"), "kill-window", "@2"
... )
>>> [is_command_separator(arg) for arg in request.args]
[False, False, True, False, False]
```

A plain `";"` is data and stays data, so nothing an existing caller passes can
become a boundary by accident:

```python
>>> from libtmux.engines import is_command_separator
>>> is_command_separator(";")
False
```

The marker survives normalization, so an engine that chains commands into one
dispatch can find the boundaries while every other engine ignores them. The
default {class}`~libtmux.engines.subprocess.SubprocessEngine` sends one command
per dispatch and has no use for them.

## Control mode

{class}`~libtmux.engines.control.sync.ControlModeEngine` runs every command over
one persistent `tmux -C` client instead of forking tmux per command. Reach for
it when a program issues many commands, such as a loop over panes: a command
costs about a tenth of a millisecond instead of two or three, and the program
starts one tmux process instead of one per command.

```python
>>> from libtmux.engines import ControlModeEngine
>>> from libtmux.server import Server
>>> controlled = Server(socket_name=server.socket_name, engine=ControlModeEngine())
>>> controlled.cmd("display-message", "-p", "over control").stdout
['over control']
>>> controlled.engine.generation
1
>>> controlled.engine.close()
```

Nothing else changes: {meth}`Server.cmd() <libtmux.Server.cmd>` returns the same
{class}`~libtmux.common.tmux_cmd`, and the object API works as before. Close the
engine when you are done, or use it as a context manager; closing detaches the
client and reaps the process.

What to know before choosing it:

- **It attaches; it never creates.** The client joins an existing session whose
  `destroy-unattached` option is off, because a bare `tmux -C` creates a
  throwaway session on your server. With no such session, commands run in a
  subprocess until one exists, so `server.new_session()` works as the first call.
- **Commands that wait run in a subprocess.** `run-shell` without `-b`,
  `wait-for`, `confirm-before`, a non-detached `new-session` and similar would
  hold every command behind them on one connection, so the engine forks for
  those and the result is the same type.
- **Replies are matched to requests in order**, and tmux's command numbers are
  checked to increase. A `;` command group is one result, and tmux drops the
  commands after the first error in it.
- **Failures are loud.** If the client exits before replying, the call raises
  {exc}`~libtmux.exc.ControlConnectionLost` with the tail of the client's stderr;
  malformed output raises {exc}`~libtmux.exc.ControlProtocolError` and the
  connection is discarded. The next call reconnects.
- **The client receives no pane output.** It sends `refresh-client -f no-output`
  after attaching, because nothing reads between calls and a pane printing into
  an unread pipe stalls on most tmux builds.

### Cost

`scripts/bench/engine_latency.py` runs the same requests through both engines on
a private server and prints percentiles and process counts as JSON:

```console
$ TMUX_TMPDIR=/tmp/lt-en uv run scripts/bench/engine_latency.py --calls 300
```

300 calls each of `display-message -p` and `list-panes -a` (2 sessions), on a
loaded development machine (load average 10), milliseconds:

| tmux | engine | `display-message` p50 | p95 | `list-panes -a` p50 | p95 | processes for 601 commands |
| ---- | ------ | --------------------: | --: | ------------------: | --: | -------------------------: |
| 3.2a | subprocess | 2.59 | 3.99 | 2.31 | 3.90 | 601 |
| 3.2a | control | 0.07 | 0.13 | 0.10 | 0.18 | 2 |
| 3.7c | subprocess | 1.65 | 2.24 | 1.83 | 2.82 | 601 |
| 3.7c | control | 0.09 | 0.16 | 0.11 | 0.19 | 2 |
| 3.8-rc | subprocess | 2.40 | 3.48 | 2.35 | 3.98 | 601 |
| 3.8-rc | control | 0.21 | 0.40 | 0.23 | 0.39 | 2 |

The two control processes are the `list-sessions` probe that picks the session
and the client itself. Connecting costs about 3 to 6 ms once.

## What an engine does not change

An engine chooses *how* a command runs, not what libtmux does with the answer.
Arguments reach tmux exactly as they always have, results read exactly as they
always have, and {meth}`Server.cmd() <libtmux.Server.cmd>` still returns a
{class}`~libtmux.common.tmux_cmd`. Under the default engine there is nothing new
to learn and nothing to migrate.
