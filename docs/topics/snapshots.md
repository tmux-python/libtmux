(snapshots)=

# Snapshots and Recordings

libtmux provides functionality to capture and analyze the state of tmux panes through snapshots and recordings.

## Taking Snapshots

A snapshot captures the content and metadata of a pane at a specific point in time:

```python
>>> pane = session.active_window.active_pane
>>> snapshot = pane.snapshot()
>>> print(snapshot.content_str)
$ echo "Hello World"
Hello World
$
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

>>> # Capture from start of history
>>> snapshot = pane.snapshot(start="-")

>>> # Capture up to current view
>>> snapshot = pane.snapshot(end="-")
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
>>> print(recording[0].content_str)  # First snapshot
>>> print(recording.latest.content_str)  # Most recent

>>> # Filter by time
>>> recent = recording.get_snapshots_between(
...     start_time=datetime.datetime.now() - datetime.timedelta(minutes=5),
...     end_time=datetime.datetime.now(),
... )
```

## Output Formats

Snapshots can be formatted in different ways for various use cases:

### Terminal Output

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

### CLI Output (No Colors)

```python
>>> from libtmux.snapshot import CLIOutputAdapter
>>> print(snapshot.format(CLIOutputAdapter()))
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

### Pytest Assertion Diffs

```python
>>> from libtmux.snapshot import PytestDiffAdapter
>>> expected = """
... PaneSnapshot(
...     pane_id='%1',
...     window_id='@1',
...     session_id='$1',
...     server_name='default',
...     timestamp='2024-01-01T12:00:00Z',
...     content=[
...         '$ echo "Hello World"',
...         'Hello World',
...         '$',
...     ],
...     metadata={
...         'pane_height': '24',
...         'pane_width': '80',
...     },
... )
... """
>>> assert snapshot.format(PytestDiffAdapter()) == expected
```

### Syrupy Snapshot Testing

```python
>>> from libtmux.snapshot import SyrupySnapshotAdapter
>>> snapshot.format(SyrupySnapshotAdapter())
{
  "pane_id": "%1",
  "window_id": "@1",
  "session_id": "$1",
  "server_name": "default",
  "timestamp": "2024-01-01T12:00:00Z",
  "content": [
    "$ echo \"Hello World\"",
    "Hello World",
    "$"
  ],
  "metadata": {
    "pane_height": "24",
    "pane_width": "80"
  }
}
```

## Custom Output Formats

You can create custom output formats by implementing the `SnapshotOutputAdapter` interface:

```python
from libtmux.snapshot import SnapshotOutputAdapter

class MyCustomAdapter(SnapshotOutputAdapter):
    def format(self, snapshot: PaneSnapshot) -> str:
        # Format snapshot data as needed
        return f"Custom format: {snapshot.content_str}"

# Use custom adapter
print(snapshot.format(MyCustomAdapter()))
```
