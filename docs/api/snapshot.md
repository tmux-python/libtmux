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
>>> snapshot = pane.snapshot()
>>> snapshot.pane_id  # doctest: +ELLIPSIS
'%...'
>>> isinstance(snapshot.content_str, str)
True
```

### Recording Activity

```python
>>> recording = pane.record()
>>> recording.add_snapshot(pane)
>>> pane.send_keys("echo 'Hello'")
>>> recording.add_snapshot(pane)
>>> isinstance(recording.latest.content_str, str)
True
>>> len(recording) >= 2
True
```

### Using Output Adapters

```python
>>> from libtmux.snapshot import TerminalOutputAdapter
>>> snapshot = pane.snapshot()
>>> formatted = snapshot.format(TerminalOutputAdapter())
>>> '=== Pane Snapshot ===' in formatted
True
>>> '=== Content ===' in formatted
True
```

### Custom Adapter

```python
>>> from libtmux.snapshot import SnapshotOutputAdapter, PaneSnapshot
>>> snapshot = pane.snapshot()
>>> class MyAdapter(SnapshotOutputAdapter):
...     def format(self, snapshot: PaneSnapshot) -> str:
...         return f"Content: {snapshot.content_str[:20]}"
>>> snapshot.format(MyAdapter()).startswith('Content:')
True
```
