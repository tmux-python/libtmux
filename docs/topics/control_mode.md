---
orphan: true
---

(control-mode)=

# Control Mode Engine (experimental)

:::{warning}
This is an **experimental API**. Names and behavior may change between releases.
Use with caution and pin your libtmux version if you depend on it.
:::

libtmux can drive tmux through a persistent Control Mode client. This keeps a
single connection open, pipelines commands, and surfaces tmux notifications in a
typed stream.

## Why use Control Mode?

- Lower overhead than spawning a tmux process per command
- Access to live notifications: layout changes, window/link events, client
  detach/attach, paste buffer updates, and more
- Structured command results with timing/flag metadata

## Using ControlModeEngine

```python
from __future__ import annotations

from libtmux._internal.engines.control_mode import ControlModeEngine
from libtmux.server import Server

engine = ControlModeEngine(command_timeout=5)
server = Server(engine=engine)

session = server.new_session(session_name="ctrl-demo")
print(session.name)

# Consume notifications (non-blocking example)
for notif in engine.iter_notifications(timeout=0.1):
    print(notif.kind, notif.data)
```

:::{note}
Control mode creates an internal session for connection management (default name:
`libtmux_control_mode`). This session is automatically filtered from
`Server.sessions` and `Server.has_session()` to maintain engine transparency.
:::

## Session management with Control Mode

The {meth}`Server.connect()` method works seamlessly with control mode:

```python
from libtmux._internal.engines.control_mode import ControlModeEngine
from libtmux.server import Server

engine = ControlModeEngine()
server = Server(engine=engine)

# Reuses session if it exists, creates if it doesn't
session = server.connect("dev-session")
print(session.name)

# Calling again returns the same session
session2 = server.connect("dev-session")
assert session2.session_id == session.session_id
```

This works transparently with both control mode and subprocess engines, making it
easy to switch between them without changing your code.

## Advanced Configuration

### Custom Internal Session Name

For testing or advanced scenarios, you can customize the internal session name:

```python
from libtmux._internal.engines.control_mode import ControlModeEngine
from libtmux.server import Server

engine = ControlModeEngine(internal_session_name="my_control_session")
server = Server(engine=engine)

# Internal session is still filtered
user_session = server.new_session("my_app")
len(server.sessions)  # 1 (only my_app visible)

# But exists internally
len(server._sessions_all())  # 2 (my_app + my_control_session)
```

### Attach to Existing Session

For expert use cases, control mode can attach to an existing session instead of
creating an internal one:

```python
# Create a session first
server.new_session("shared")

# Control mode attaches to it for its connection
engine = ControlModeEngine(attach_to="shared")
server = Server(engine=engine)

# The shared session is visible (not filtered)
len(server.sessions)  # 1 (shared session)
```

:::{warning}
Attaching to active user sessions will generate notification traffic from pane
output and layout changes. This increases protocol parsing overhead and may impact
performance. Use only when you need control mode notifications for a specific session.
:::

## Parsing notifications directly

The protocol parser can be used without tmux to understand the wire format.

```python
>>> from libtmux._internal.engines.control_protocol import ControlProtocol
>>> proto = ControlProtocol()
>>> proto.feed_line("%layout-change @1 abcd efgh 0")
>>> notif = proto.get_notification()
>>> notif.kind.name
'WINDOW_LAYOUT_CHANGED'
>>> notif.data['window_layout']
'abcd'
```

## Fallback engine

If control mode is unavailable, ``SubprocessEngine`` matches the same
``Engine`` interface but runs one tmux process per command:

```python
from libtmux._internal.engines.subprocess_engine import SubprocessEngine
from libtmux.server import Server

server = Server(engine=SubprocessEngine())
print(server.list_sessions())  # legacy behavior
```

## Key behaviors

- Commands still return ``tmux_cmd`` objects for compatibility, but extra
  metadata (``exit_status``, ``cmd_id``, ``tmux_time``) is attached.
- Notifications are queued; drops are counted when consumers fall behind.
- Timeouts raise ``ControlModeTimeout`` and restart the control client.

## Errors, timeouts, and retries

- ``ControlModeTimeout`` — command block did not finish before
  ``command_timeout``. The engine closes and restarts the control client.
- ``ControlModeConnectionError`` — control socket died (EOF/broken pipe). The
  engine restarts and replays the pending command once.
- ``ControlModeProtocolError`` — malformed ``%begin/%end/%error`` framing; the
  client is marked dead and must be restarted.
- ``SubprocessTimeout`` — subprocess fallback exceeded its timeout.

## Notifications and backpressure

- Notifications are enqueued in a bounded queue (default 4096). When the queue
  fills, additional notifications are dropped and the drop counter is reported
  via :class:`~libtmux._internal.engines.base.EngineStats`.
- Consume notifications via :meth:`ControlModeEngine.iter_notifications` to
  avoid drops; use a small timeout (e.g., 0.1s) for non-blocking loops.

## Environment propagation requirements

- tmux **3.2 or newer** is required for ``-e KEY=VAL`` on ``new-session``,
  ``new-window``, and ``split-window``. Older tmux versions ignore ``-e``; the
  library emits a warning and tests skip these cases.
- Environment tests and examples may wait briefly after ``send-keys`` so the
  shell prompt/output reaches the pane before capture.

## Capture-pane normalization

- Control mode trims trailing *whitespace-only* lines from ``capture-pane`` to
  match subprocess behaviour. If you request explicit ranges (``-S/-E``) or use
  ``-N/-J``, output is left untouched.
- In control mode, the first capture after ``send-keys`` can race the shell;
  libtmux retries briefly to ensure the prompt/output is visible.

## Control sandbox (tests/diagnostics)

The pytest fixture ``control_sandbox`` provides an isolated control-mode tmux
server with a unique socket, HOME/TMUX_TMPDIR isolation, and automatic cleanup.
It is used by the regression suite and can be reused in custom tests when you
need a hermetic control-mode client.
