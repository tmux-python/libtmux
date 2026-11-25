(engines)=

# Engines

Every tmux command libtmux runs goes through an **engine**: an object that
takes a {class}`~libtmux.engine.TmuxRequest` and returns a lossless raw-byte
{class}`~libtmux.engine.TmuxResult`.

By default, {class}`~libtmux.Server` uses
{class}`~libtmux.engine.SubprocessEngine`, which spawns the `tmux` executable
for each command. If you drive a local tmux server through `Server`, `Session`,
`Window`, and `Pane`, the default already covers your workflow and you can stop
after the first two sections. Reach for custom engines when you want to test
without a running tmux daemon, pipeline commands over control mode, wrap `tmux`
inside `docker exec` or `ssh`, or guard commands against daemon restarts.

## Default execution and raw bytes

Under the default engine, {meth}`Server.cmd() <libtmux.Server.cmd>` returns a
{class}`~libtmux.common.tmux_cmd` with UTF-8 decoded `stdout` and `stderr`
lines alongside unmodified `raw_stdout` and `raw_stderr` bytes:

```python
>>> proc = server.cmd("display-message", "-p", "#{session_name}")
>>> proc.stdout
['libtmux_...']
>>> isinstance(proc.raw_stdout, bytes)
True
```

Commands that read `-` from standard input or emit arbitrary binary data keep
every byte intact through `stdin=` and `raw_stdout`:

```python
>>> payload = b"\x00\xffbinary-line\n\n"
>>> _ = server.cmd("load-buffer", "-b", "demo_buf", "-", stdin=payload)
>>> server.cmd("save-buffer", "-b", "demo_buf", "-").raw_stdout == payload
True
```

## Testing without tmux

Pass `engine=` to {class}`~libtmux.Server` to replace subprocess execution.
{class}`~libtmux.test.FakeEngine` queues canned responses in memory and records
every {class}`~libtmux.engine.TmuxRequest` without needing a `tmux` binary:

```python
>>> from libtmux.server import Server as TmuxServer
>>> from libtmux.test import FakeEngine
>>> fake = FakeEngine()
>>> fake.enqueue(stdout=b"from-fake\n")
>>> offline = TmuxServer(socket_name="unit_test", engine=fake)
>>> offline.cmd("display-message", "-p", "ignored").stdout
['from-fake']
>>> fake.requests[0].commands
(('display-message', '-p', 'ignored'),)
```

To observe commands against a real server without changing how they run, wrap
an engine in {class}`~libtmux.test.RecordingEngine`:

```python
>>> from libtmux.engine import SubprocessEngine
>>> from libtmux.server import Server as TmuxServer
>>> from libtmux.test import RecordingEngine
>>> recorder = RecordingEngine(SubprocessEngine.for_server(server))
>>> observed = TmuxServer(socket_name=server.socket_name, engine=recorder)
>>> _ = observed.cmd("display-message", "-p", "tracked")
>>> recorder.requests[0].subcommand
'display-message'
```

## Writing a custom engine

{class}`~libtmux.engine.TmuxEngine` is a {class}`typing.Protocol` requiring an
`endpoint` attribute and a synchronous `execute(request)` method. A tmux-side
error is returned as data (`returncode` and `stderr`), while transport failures
raise {exc}`~libtmux.exc.TmuxTransportError` or
{exc}`~libtmux.exc.TmuxCommandNotFound`:

```python
>>> from libtmux.engine import TmuxEngine, TmuxRequest, TmuxResult
>>> class StaticEngine:
...     endpoint = "memory://demo"
...     def execute(self, request: TmuxRequest) -> TmuxResult:
...         return TmuxResult(argv=("tmux", *request.commands[0]), stdout=b"ok\n")
>>> isinstance(StaticEngine(), TmuxEngine)
True
```

When you pass an engine that already binds a specific socket (`-L` or `-S`) to
a {class}`~libtmux.Server` configured for a different socket, construction
raises {exc}`~libtmux.exc.EngineConfigurationMismatch` immediately rather than
silently overriding either target.

## Wrapper prefixes and control mode

For remote or containerized servers, {class}`~libtmux.engine.ExecEngine`
prepends a wrapper command before `tmux` and sets a distinct `endpoint` so two
servers sharing `-L default` in different containers never compare equal:

```python
>>> from libtmux.engine import ExecEngine, TmuxRequest
>>> engine = ExecEngine(("docker", "exec", "-i", "worker"))
>>> engine.command_line(TmuxRequest.from_args("list-sessions"))
('docker', 'exec', '-i', 'worker', 'tmux', 'list-sessions')
```

On tmux 3.7 and newer, {class}`~libtmux.engine.ControlModeEngine` pipelines
eligible commands over a persistent `tmux -u -C` client while routing binary
`stdin`, blocking waits, and multi-command groups through
{class}`~libtmux.engine.SubprocessEngine`.

## Capabilities and generation fences

{meth}`Server.capabilities() <libtmux.Server.capabilities>` queries the
connected daemon's version, `pid`, and `start_time` without starting a server
or firing `after-*` hooks:

```python
>>> caps = session.server.capabilities()
>>> caps.pid > 0 and isinstance(caps.supports("control-mode"), bool)
True
```

Pairing those coordinates with {class}`~libtmux.engine.DaemonGuard` aborts a
command with {exc}`~libtmux.exc.TmuxServerRestarted` if the daemon restarted
between inspection and mutation:

```python
>>> from libtmux.engine import DaemonGuard
>>> caps = session.server.capabilities()
>>> guard = DaemonGuard(pid=caps.pid, start_time=caps.start_time)
>>> session.server.cmd("display-message", "-p", "ok", daemon_guard=guard).stdout
['ok']
```
