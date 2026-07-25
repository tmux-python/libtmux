# Choose an engine

Every engine satisfies the same
{class}`~libtmux.experimental.engines.base.TmuxEngine` or
{class}`~libtmux.experimental.engines.base.AsyncTmuxEngine` protocol. Changing
the engine changes how and where a command runs, not the operation or its
result type.

| Engine | Transport | Use it for |
| --- | --- | --- |
| {class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` | one `tmux` process per command | compatibility with the classic libtmux execution path |
| {class}`~libtmux.experimental.engines.mock.MockEngine` | in-memory, no tmux | deterministic tests and command-shape assertions |
| {class}`~libtmux.experimental.engines.control_mode.ControlModeEngine` | persistent `tmux -C` connection | many commands over one connection |
| {class}`~libtmux.experimental.engines.imsg.base.ImsgEngine` | tmux native peer protocol | direct protocol experiments |

Async subprocess, mock, and control-mode engines implement
{class}`~libtmux.experimental.engines.base.AsyncTmuxEngine`.

## Select by name

Construct an engine directly, bind a subprocess engine to a live server, or use
the engine registry:

```python
>>> from libtmux.experimental.engines import available_engines, create_engine
>>> from libtmux.experimental.ops import HasSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> available_engines()
('control_mode', 'imsg', 'mock', 'subprocess')
>>> engine = create_engine("mock")
>>> run(HasSession(target=SessionId("$0")), engine).status
'complete'
```

## Engine boundary

An engine emits a raw
{class}`~libtmux.experimental.engines.base.CommandResult`. The operation runner
converts it to the operation's declared
{class}`~libtmux.experimental.ops.results.Result` subtype. This boundary lets a
mock prove rendering and result conversion without claiming that a target
exists on a live tmux server.

## API

- {class}`~libtmux.experimental.engines.base.TmuxEngine`
- {class}`~libtmux.experimental.engines.base.AsyncTmuxEngine`
- {func}`~libtmux.experimental.engines.registry.available_engines`
- {func}`~libtmux.experimental.engines.registry.create_engine`
