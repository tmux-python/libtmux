"""Hierarchical snapshots of tmux objects.

libtmux.snapshot
~~~~~~~~~~~~~~

- **License**: MIT
- **Description**: Snapshot data structure for tmux objects

This module provides hierarchical snapshots of tmux objects (Server, Session,
Window, Pane) that are immutable and maintain the relationships between objects.

Usage
-----
The primary interface is through the factory functions:

```python
from libtmux import Server
from libtmux.snapshot.factory import create_snapshot, create_snapshot_active

# Create a snapshot of a server
server = Server()
snapshot = create_snapshot(server)

# Create a snapshot of a server with only active components
active_snapshot = create_snapshot_active(server)

# Create a snapshot with pane content captured
content_snapshot = create_snapshot(server, capture_content=True)

# Snapshot API methods
data = snapshot.to_dict()  # Convert to dictionary
filtered = snapshot.filter(lambda x: hasattr(x, 'window_name'))  # Filter
```
"""
