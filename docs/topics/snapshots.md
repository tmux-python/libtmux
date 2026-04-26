(snapshots)=

# Snapshots and Recordings

libtmux provides functionality to capture and analyze the state of tmux panes through snapshots and recordings.

## Taking Snapshots

A snapshot captures the content and metadata of a pane at a specific point in time:

```python
>>> snapshot = pane.snapshot()
>>> snapshot.pane_id  # doctest: +ELLIPSIS
'%...'
>>> isinstance(snapshot.content_str, str)
True
```

Snapshots are immutable and include:
- Pane content
- Timestamp (in UTC)
- Pane, window, session, and server IDs
- All tmux pane metadata

You can also capture specific ranges of the pane history:

```python
>>> # Capture lines 1-3 only
>>> snapshot = pane.snapshot(start=1, end=3)
>>> isinstance(snapshot.content_str, str)
True

>>> # Capture from start of history
>>> snapshot = pane.snapshot(start="-")
>>> isinstance(snapshot.content_str, str)
True

>>> # Capture up to current view
>>> snapshot = pane.snapshot(end="-")
>>> isinstance(snapshot.content_str, str)
True
```

## Recording Pane Activity

To track changes in a pane over time, use recordings:

```python
>>> recording = pane.record()
>>> recording.add_snapshot(pane)
>>> pane.send_keys("echo 'Hello'")
>>> recording.add_snapshot(pane)
>>> pane.send_keys("echo 'World'")
>>> recording.add_snapshot(pane)

>>> # Access snapshots
>>> isinstance(recording[0].content_str, str)
True
>>> isinstance(recording.latest.content_str, str)
True

>>> # Filter by time
>>> import datetime
>>> recent = recording.get_snapshots_between(
...     start_time=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5),
...     end_time=datetime.datetime.now(datetime.timezone.utc),
... )
>>> isinstance(recent, list)
True
```

## Output Formats

Snapshots can be formatted in different ways for various use cases:

### Terminal Output

```python
>>> from libtmux.snapshot import TerminalOutputAdapter
>>> snapshot = pane.snapshot()
>>> formatted = snapshot.format(TerminalOutputAdapter())
>>> '=== Pane Snapshot ===' in formatted
True
>>> '=== Content ===' in formatted
True
```

### CLI Output (No Colors)

```python
>>> from libtmux.snapshot import CLIOutputAdapter
>>> snapshot = pane.snapshot()
>>> formatted = snapshot.format(CLIOutputAdapter())
>>> '=== Pane Snapshot ===' in formatted
True
```

### Pytest Assertion Diffs

```python
>>> from libtmux.snapshot import PytestDiffAdapter
>>> snapshot = pane.snapshot()
>>> formatted = snapshot.format(PytestDiffAdapter())
>>> 'PaneSnapshot(' in formatted
True
```

### Syrupy Snapshot Testing

```python
>>> from libtmux.snapshot import SyrupySnapshotAdapter
>>> snapshot = pane.snapshot()
>>> formatted = snapshot.format(SyrupySnapshotAdapter())
>>> 'pane_id' in formatted
True
```

## Custom Output Formats

You can create custom output formats by implementing the `SnapshotOutputAdapter` interface:

```python
>>> from libtmux.snapshot import SnapshotOutputAdapter, PaneSnapshot
>>> snapshot = pane.snapshot()
>>> class MyCustomAdapter(SnapshotOutputAdapter):
...     def format(self, snapshot: PaneSnapshot) -> str:
...         return f"Custom format: {snapshot.content_str[:20]}"
>>> result = snapshot.format(MyCustomAdapter())
>>> result.startswith('Custom format:')
True
```
