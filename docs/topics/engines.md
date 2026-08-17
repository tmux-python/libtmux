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
CommandRequest(args=('kill-window', '-t', '2'), tmux_bin=None)
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

An engine already on the requested server is left exactly as you built it:

```python
>>> from libtmux.engines import SubprocessEngine
>>> from libtmux.server import Server
>>> pinned = SubprocessEngine.of(server_args=("-Lengines_doc_c",))
>>> Server(socket_name="engines_doc_c", engine=pinned).engine.server_args
('-Lengines_doc_c',)
```

Conflicting explicit scopes fail before a command can reach the wrong server:

```python
>>> from libtmux import exc
>>> from libtmux.engines import SubprocessEngine
>>> from libtmux.server import Server
>>> pinned = SubprocessEngine.of(server_args=("-Lengines_doc_pinned",))
>>> try:
...     Server(socket_name="engines_doc_c", engine=pinned).engine
... except exc.EngineConfigurationMismatch:
...     print("connection mismatch")
connection mismatch
```

An in-memory engine has no connection at all, so neither rule applies and it is
used untouched.

## Optional capabilities

An engine may implement extra protocols. Each is optional; libtmux checks with
{func}`isinstance` and degrades gracefully when absent.

{class}`~libtmux.engines.base.SupportsCommandLine` renders the argv an engine
*would* run, which is how the full command line reaches the debug log before
dispatch. {class}`~libtmux.engines.base.HasConnection` exposes a transport's
server scope for validation. {class}`~libtmux.engines.base.SupportsConnection`
adds safe rebinding; stateless subprocess engines implement both, while a live
control connection implements only the read-only capability and must already
match the Server.

```python
>>> from libtmux.engines import (
...     SubprocessEngine,
...     HasConnection,
...     SupportsCommandLine,
...     SupportsConnection,
... )
>>> engine = SubprocessEngine()
>>> (
...     isinstance(engine, SupportsCommandLine),
...     isinstance(engine, HasConnection),
...     isinstance(engine, SupportsConnection),
... )
(True, True, True)
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

Tmux's direct argv parser treats an unescaped `;` at the end of any token as a
boundary between two commands. That includes both a standalone `;` and a value
such as `title;`; an interior semicolon remains data. Guessing intent from the
string alone cannot distinguish a literal suffix from command structure, so
the intent rides in the type:
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

A plain `";"` and any other ordinary trailing semicolon are encoded as data:

```python
>>> from libtmux.engines import is_command_separator
>>> is_command_separator(";")
False
```

An existing `\;` suffix remains tmux escape syntax and is not escaped again;
tmux consumes that backslash while producing a literal semicolon. Use the
typed marker for structure and an ordinary unescaped suffix for new literal
data.

The marker survives request normalization. Direct subprocess engines render it
as a bare structural token while escaping ordinary suffix semicolons; control
engines render ordinary values as quoted data. Callers that intentionally used
a plain `";"` to group commands must replace it with `CommandSeparator(";")`.

## What an engine does not change

An engine chooses *how* a command runs, not what libtmux does with the answer.
Unescaped suffix semicolons remain argument data while each engine applies its
transport encoding, results read as before, and
{meth}`Server.cmd() <libtmux.Server.cmd>` still returns a
{class}`~libtmux.common.tmux_cmd`. Under the default engine there is nothing new
to configure.
