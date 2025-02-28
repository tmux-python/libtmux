#!/usr/bin/env python3
"""Test the snapshot functionality of libtmux."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from libtmux.server import Server
from libtmux.snapshot import (
    ServerSnapshot,
    snapshot_active_only,
    snapshot_to_dict,
)


def main():
    """Demonstrate the snapshot functionality."""
    # Create a test server
    server = Server()

    # Take a complete snapshot of the server
    print("Creating a complete snapshot of the server...")
    server_snapshot = ServerSnapshot.from_server(server)

    # Print some information about the snapshot
    print(f"Server snapshot created at: {server_snapshot.created_at}")
    print(f"Number of sessions: {len(server_snapshot.sessions)}")

    # Test that the snapshot is read-only
    try:
        server_snapshot.cmd("list-sessions")
    except NotImplementedError as e:
        print(f"Expected error when trying to execute a command: {e}")

    # If there are sessions, print information about the first one
    if server_snapshot.sessions:
        session = server_snapshot.sessions[0]
        print(f"\nFirst session ID: {session.id}")
        print(f"First session name: {session.name}")
        print(f"Number of windows: {len(session.windows)}")

        # If there are windows, print information about the first one
        if session.windows:
            window = session.windows[0]
            print(f"\nFirst window ID: {window.id}")
            print(f"First window name: {window.name}")
            print(f"Number of panes: {len(window.panes)}")

            # If there are panes, print information about the first one
            if window.panes:
                pane = window.panes[0]
                print(f"\nFirst pane ID: {pane.id}")
                print(
                    f"First pane content (up to 5 lines): {pane.pane_content[:5] if pane.pane_content else 'No content captured'}"
                )

    # Demonstrate filtering
    print("\nFiltering snapshot to get only active components...")
    try:
        filtered_snapshot = snapshot_active_only(server)
        print(f"Active sessions: {len(filtered_snapshot.sessions)}")

        active_windows = 0
        active_panes = 0
        for session in filtered_snapshot.sessions:
            active_windows += len(session.windows)
            for window in session.windows:
                active_panes += len(window.panes)

        print(f"Active windows: {active_windows}")
        print(f"Active panes: {active_panes}")
    except ValueError as e:
        print(f"No active components found: {e}")

    # Demonstrate serialization
    print("\nSerializing snapshot to dictionary...")
    snapshot_dict = snapshot_to_dict(server_snapshot)
    print(f"Dictionary has {len(snapshot_dict)} top-level keys")
    print(f"Top-level keys: {', '.join(sorted(key for key in snapshot_dict.keys()))}")

    # Output to JSON (just to show it's possible)
    json_file = "server_snapshot.json"
    with open(json_file, "w") as f:
        json.dump(snapshot_dict, f, indent=2, default=str)
    print(f"Snapshot saved to {json_file}")


if __name__ == "__main__":
    main()
