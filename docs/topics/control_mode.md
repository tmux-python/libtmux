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
Control mode creates a bootstrap tmux session named ``libtmux_control_mode``.
If your code enumerates sessions, filter it out.
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
