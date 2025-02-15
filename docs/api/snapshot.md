(snapshot)=

# Snapshots

The snapshot module provides functionality for capturing and analyzing the state of tmux panes.

## Core Classes

```{eval-rst}
.. autoclass:: libtmux.snapshot.PaneSnapshot
    :members:
    :inherited-members:
    :show-inheritance:
    :member-order: bysource

.. autoclass:: libtmux.snapshot.PaneRecording
    :members:
    :inherited-members:
    :show-inheritance:
    :member-order: bysource
```

## Output Adapters

```{eval-rst}
.. autoclass:: libtmux.snapshot.SnapshotOutputAdapter
    :members:
    :inherited-members:
    :show-inheritance:
    :member-order: bysource

.. autoclass:: libtmux.snapshot.TerminalOutputAdapter
    :members:
    :inherited-members:
    :show-inheritance:
    :member-order: bysource

.. autoclass:: libtmux.snapshot.CLIOutputAdapter
    :members:
    :inherited-members:
    :show-inheritance:
    :member-order: bysource

.. autoclass:: libtmux.snapshot.PytestDiffAdapter
    :members:
    :inherited-members:
    :show-inheritance:
    :member-order: bysource

.. autoclass:: libtmux.snapshot.SyrupySnapshotAdapter
    :members:
    :inherited-members:
    :show-inheritance:
    :member-order: bysource
```

## Examples

### Basic Snapshot

```python
>>> pane = session.active_window.active_pane
>>> snapshot = pane.snapshot()
>>> print(snapshot.content_str)
$ echo "Hello World"
Hello World
$
```

### Recording Activity

```python
>>> recording = pane.record()
>>> recording.add_snapshot(pane)
>>> pane.send_keys("echo 'Hello'")
>>> recording.add_snapshot(pane)
>>> print(recording.latest.content_str)
$ echo 'Hello'
Hello
$
```

### Using Output Adapters

```python
>>> from libtmux.snapshot import TerminalOutputAdapter
>>> print(snapshot.format(TerminalOutputAdapter()))
=== Pane Snapshot ===
Pane: %1
Window: @1
Session: $1
Server: default
Timestamp: 2024-01-01T12:00:00Z
=== Content ===
$ echo "Hello World"
Hello World
$
```

### Custom Adapter

```python
>>> from libtmux.snapshot import SnapshotOutputAdapter
>>> class MyAdapter(SnapshotOutputAdapter):
...     def format(self, snapshot):
...         return f"Content: {snapshot.content_str}"
>>> print(snapshot.format(MyAdapter()))
Content: $ echo "Hello World"
Hello World
$
```
