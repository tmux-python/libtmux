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

## Testing without tmux

Writing a fake that *simulates* tmux is a trap. libtmux's listing queries ask
tmux for 136 format fields per row, and a fake that answers unknown commands
optimistically ends up reporting that every session exists (`has-session` exits
0) while no sessions exist (`list-sessions` is empty).

So record real traffic instead, and play it back.
{class}`~libtmux.engines.record.RecordingEngine` wraps a real engine and keeps
what tmux said; {class}`~libtmux.engines.record.ReplayEngine` serves it back:

```python
>>> from libtmux.engines import RecordingEngine, ReplayEngine, SubprocessEngine
>>> from libtmux.server import Server

>>> recorder = RecordingEngine(SubprocessEngine.for_server(server))
>>> live = Server(socket_name=server.socket_name, engine=recorder)
>>> _ = live.cmd("display-message", "-p", "#{session_name}")

>>> offline = Server(engine=ReplayEngine(recorder.tape))
>>> offline.cmd("display-message", "-p", "#{session_name}").stdout
['libtmux_...']
```

Because the rows came from real tmux, the whole object API works offline —
`sessions`, `windows`, `panes` all hydrate. `to_dict()` and
{meth}`~libtmux.engines.record.ReplayEngine.from_dict` round-trip a tape through
JSON, so you can commit one next to the tests that replay it: recording needs
tmux, running does not.

A replay engine **fails closed**. A command it never recorded raises
{exc}`~libtmux.exc.UnscriptedCommand` rather than inventing an answer:

```python
>>> from libtmux.engines import CommandResult, ReplayEngine
>>> from libtmux.server import Server
>>> engine = ReplayEngine({("list-sessions",): CommandResult(cmd=("tmux",))})
>>> Server(engine=engine).cmd("kill-server")
Traceback (most recent call last):
...
libtmux.exc.UnscriptedCommand: no recorded result for 'kill-server'
```

A recorder also works as a plain spy — `requests` is every argv in order, which
is what the `recording_server` pytest fixture is for:

```python
>>> from libtmux.engines import RecordingEngine, SubprocessEngine
>>> from libtmux.server import Server
>>> recorder = RecordingEngine(SubprocessEngine.for_server(server))
>>> spy = Server(socket_name=server.socket_name, engine=recorder)
>>> _ = spy.cmd("list-sessions")
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
dispatch. {class}`~libtmux.engines.base.SupportsTmuxVersion` reports the tmux
version an engine targets, for version-gated behavior.
{class}`~libtmux.engines.base.SupportsConnection` marks an engine that
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

## Separators are explicit

tmux treats a trailing `;` on an argument as a command boundary. libtmux escapes
it so your data survives, which means a `;` you *intend* as a separator must say
so with {class}`~libtmux.engines.base.CommandSeparator`:

```python
>>> from libtmux.engines import CommandSeparator, encode_direct_argv
>>> encode_direct_argv(("send-keys", "echo hi;"))
('send-keys', 'echo hi\\;')
>>> encode_direct_argv(("send-keys", CommandSeparator(";"), "clear-history"))
('send-keys', ';', 'clear-history')
```

Connection flags are never escaped, because tmux's `getopt` removes them before
the command parser ever sees them:

```python
>>> from libtmux.engines import encode_direct_argv
>>> encode_direct_argv(("-Lsock;", "display-message", "text;"))
('-Lsock;', 'display-message', 'text\\;')
```

Used against a live pane, a separator folds two tmux commands into one dispatch:

```python
>>> pane = session.active_window.active_pane
>>> from libtmux.engines import CommandSeparator
>>> _ = server.cmd(
...     "send-keys", "-t", pane.pane_id, "-R",
...     CommandSeparator(";"),
...     "clear-history", "-t", pane.pane_id,
... )
```

See {ref}`migration-0-63-command-separator` for migrating existing callers.
