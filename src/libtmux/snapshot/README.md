# libtmux Snapshot Module

The snapshot module provides a powerful way to capture the state of tmux objects (Server, Session, Window, Pane) as immutable, hierarchical snapshots. These snapshots preserve the structure and relationships between tmux objects while allowing for inspection, filtering, and serialization.

## Value Proposition

Snapshots provide several key benefits for tmux automation and management:

- **Point-in-time Captures**: Create immutable records of tmux state at specific moments
- **State Inspection**: Examine the structure of sessions, windows, and panes without modifying them
- **Testing Support**: Build reliable tests with deterministic tmux state snapshots
- **Comparison & Diff**: Compare configurations between different sessions or before/after changes
- **State Serialization**: Convert tmux state to dictionaries for storage or analysis
- **Safety & Predictability**: Work with tmux state without modifying the actual tmux server
- **Content Preservation**: Optionally capture pane content to preserve terminal output
- **Filtering & Searching**: Find specific components within complex tmux arrangements

## Installation

The snapshot module is included with libtmux:

```bash
pip install libtmux
```

## Basic Usage

Creating snapshots is straightforward using the factory functions:

```python
from libtmux import Server
from libtmux.snapshot.factory import create_snapshot, create_snapshot_active

# Connect to the tmux server
server = Server()

# Create a complete snapshot of the entire tmux server
server_snapshot = create_snapshot(server)

# Create a snapshot that only includes active sessions, windows, and panes
active_snapshot = create_snapshot_active(server)

# Create a snapshot with pane content captured
content_snapshot = create_snapshot(server, capture_content=True)

# Create a snapshot of a specific session
session = server.find_where({"session_name": "dev"})
if session:
    session_snapshot = create_snapshot(session)
    
# Create a snapshot of a specific window
window = session.attached_window
if window:
    window_snapshot = create_snapshot(window)
    
# Create a snapshot of a specific pane
pane = window.attached_pane
if pane:
    pane_snapshot = create_snapshot(pane)
```

## Working with Snapshots

Once you have a snapshot, you can navigate its hierarchy just like regular tmux objects:

```python
# Inspecting the server snapshot
server_snapshot = create_snapshot(server)
print(f"Server has {len(server_snapshot.sessions)} sessions")

# Navigate the snapshot hierarchy
for session in server_snapshot.sessions:
    print(f"Session: {session.name} ({len(session.windows)} windows)")
    
    for window in session.windows:
        print(f"  Window: {window.name} (index: {window.index})")
        
        for pane in window.panes:
            print(f"    Pane: {pane.pane_id} (active: {pane.active})")
            
            # If content was captured
            if pane.pane_content:
                print(f"      Content lines: {len(pane.pane_content)}")
```

## Filtering Snapshots

The snapshot API provides powerful filtering capabilities:

```python
# Filter a snapshot to only include a particular session
dev_snapshot = server_snapshot.filter(
    lambda s: getattr(s, "name", "") == "dev" or getattr(s, "session_name", "") == "dev"
)

# Filter for a specific window
target_window_snapshot = server_snapshot.filter(
    lambda s: getattr(s, "window_id", "") == "$1"
)

# Filter for active panes only
active_panes_snapshot = server_snapshot.filter(
    lambda s: getattr(s, "active", False) is True
)

# Complex filtering: sessions with at least one window containing "test" in the name
def has_test_window(obj):
    if hasattr(obj, "windows"):
        return any("test" in w.name.lower() for w in obj.windows)
    return "test" in getattr(obj, "name", "").lower()

test_snapshot = server_snapshot.filter(has_test_window)
```

## Serializing to Dictionaries

Snapshots can be easily converted to dictionaries for storage or analysis:

```python
# Convert a snapshot to a dictionary for serialization or inspection
snapshot_dict = server_snapshot.to_dict()

# Pretty print the structure
import json
print(json.dumps(snapshot_dict, indent=2))

# Selective dictionary conversion
session = server_snapshot.sessions[0]
session_dict = session.to_dict()
```

## Common Use Cases

### Testing tmux Applications

Snapshots make it easy to verify that tmux automations produce the expected state:

```python
def test_my_tmux_function():
    # Setup
    server = Server()
    session = server.new_session("test-session")
    
    # Take a snapshot before
    before_snapshot = create_snapshot(server)
    
    # Run the function being tested
    my_tmux_function(session)
    
    # Take a snapshot after
    after_snapshot = create_snapshot(server)
    
    # Assert expected changes
    assert len(after_snapshot.sessions) == len(before_snapshot.sessions) + 1
    
    # Find the newly created session
    new_session = next(
        (s for s in after_snapshot.sessions if s not in before_snapshot.sessions),
        None
    )
    assert new_session is not None
    assert new_session.name == "expected-name"
    assert len(new_session.windows) == 3  # Expected window count
```

### Creating Reattachable Sessions

```python
# Take a snapshot before making changes
snapshot = create_snapshot(server)

# Make changes to tmux
# ...

# Find a session from the snapshot to reattach
original_session = snapshot.filter(lambda s: getattr(s, "name", "") == "main")
if original_session and hasattr(original_session, "name"):
    # Reattach to that session using its name
    server.cmd("attach-session", "-t", original_session.name)
```

### Comparing Window Configurations

```python
# Take a snapshot of two different sessions
session1 = server.find_where({"session_name": "dev"})
session2 = server.find_where({"session_name": "prod"})

if session1 and session2:
    snapshot1 = create_snapshot(session1)
    snapshot2 = create_snapshot(session2)
    
    # Compare window layouts
    for window1 in snapshot1.windows:
        # Find matching window in session2 by name
        matching_windows = [w for w in snapshot2.windows if w.name == window1.name]
        if matching_windows:
            window2 = matching_windows[0]
            print(f"Window {window1.name}:")
            print(f"  Session 1 layout: {window1.layout}")
            print(f"  Session 2 layout: {window2.layout}")
            print(f"  Layouts match: {window1.layout == window2.layout}")
```

### Monitoring Pane Content Changes

```python
import time

# Create a snapshot with pane content
pane = server.sessions[0].attached_window.attached_pane
snapshot1 = create_snapshot(pane, capture_content=True)

# Wait for potential changes
time.sleep(5)

# Take another snapshot
snapshot2 = create_snapshot(pane, capture_content=True)

# Compare content
if snapshot1.pane_content and snapshot2.pane_content:
    content1 = "\n".join(snapshot1.pane_content)
    content2 = "\n".join(snapshot2.pane_content)
    
    if content1 != content2:
        print("Content changed!")
        
        # Show a simple diff
        import difflib
        diff = difflib.unified_diff(
            snapshot1.pane_content,
            snapshot2.pane_content,
            fromfile="before",
            tofile="after",
        )
        print("\n".join(diff))
```

### Saving and Restoring Window Arrangements

```python
import json
import os

# Save the current tmux session arrangement
def save_arrangement(session_name, filepath):
    session = server.find_where({"session_name": session_name})
    if session:
        snapshot = create_snapshot(session)
        with open(filepath, "w") as f:
            json.dump(snapshot.to_dict(), f, indent=2)
        print(f"Saved arrangement to {filepath}")
    else:
        print(f"Session '{session_name}' not found")

# Example usage
save_arrangement("dev", "dev_arrangement.json")

# This function could be paired with a restore function that
# recreates the session from the saved arrangement
```

## Best Practices

- **Immutability**: Remember that snapshots are immutable - methods return new objects rather than modifying the original
- **Timing**: Snapshots represent the state at the time they were created - they don't update automatically
- **Memory Usage**: Be cautious with `capture_content=True` on many panes, as this captures all pane content and can use significant memory
- **Filtering**: The `filter()` method is powerful for finding specific objects within the snapshot hierarchy
- **Type Safety**: The API uses strong typing - take advantage of type hints in your code

## API Overview

The snapshot module follows this structure:

- Factory functions in `factory.py`:
  - `create_snapshot(obj)`: Create a snapshot of any tmux object
  - `create_snapshot_active(server)`: Create a snapshot with only active components

- Snapshot classes in `models/`:
  - `ServerSnapshot`: Snapshot of a tmux server
  - `SessionSnapshot`: Snapshot of a tmux session
  - `WindowSnapshot`: Snapshot of a tmux window
  - `PaneSnapshot`: Snapshot of a tmux pane

- Common methods on all snapshot classes:
  - `to_dict()`: Convert to a dictionary
  - `filter(predicate)`: Apply a filter function to this snapshot and its children 