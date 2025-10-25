(engines-topic)=

# Command Engines

libtmux can execute tmux commands through different "engines"—pluggable
backends that share the same high-level API but vary in transport mechanics.
This abstraction keeps the Python surface area stable while allowing you to
choose the best option for your environment.

## Available engines

``SubprocessEngine`` (default)
: Launches a short-lived ``tmux`` process for each command, matching the
  behaviour libtmux shipped with historically. This is the most broadly
  compatible approach and requires no extra configuration.

``ControlModeEngine``
: Starts ``tmux`` with the ``-C`` flag and communicates using tmux’s control
  mode protocol. Because it keeps a persistent control connection open, it can
  be more efficient for workflows that issue many commands in rapid succession
  and is a stepping stone toward richer, event-driven integrations.

Both engines expose the same :class:`~libtmux.engines.base.CommandResult`
contract, so all existing consumers (e.g., :class:`~libtmux.Server`,
:class:`~libtmux.Session`, :class:`~libtmux.Window`, :class:`~libtmux.Pane`)
continue to operate identically regardless of which engine you choose.

## Choosing an engine

```python
>>> import libtmux
>>> from libtmux.engines import ControlModeEngine
>>> server = libtmux.Server(engine=ControlModeEngine())
```

If you omit the ``engine`` argument, libtmux defaults to
:class:`~libtmux.engines.subprocess.SubprocessEngine` for full backward
compatibility. You can inject the engine at construction time—fixtures in the
test suite demonstrate this pattern—and all child objects created from the
server inherit the same backend automatically.

## Compatibility notes

- Control mode is available in tmux 2.1 and newer. Ensure your tmux binary
  supports ``-C`` before opting in.
- When using control mode, libtmux opens a dedicated tmux process per engine
  instance. Create one :class:`~libtmux.Server` per desired control connection
  to avoid unnecessary processes.
- Both engines honour ``socket_name``, ``socket_path`` and ``config_file``
  options just like the CLI would; the abstraction only swaps out how commands
  are forwarded to tmux.

For deeper architectural background, explore the {ref}`traversal` topic to see
how commands flow through libtmux’s object model.
