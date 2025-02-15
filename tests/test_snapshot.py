"""Tests for libtmux snapshot functionality."""

from __future__ import annotations

import datetime
import shutil
import time
import typing as t

from libtmux.snapshot import PaneRecording, PaneSnapshot

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_pane_snapshot(session: Session) -> None:
    """Test creating a PaneSnapshot from a pane."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="snapshot_test",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None

    # Take initial snapshot
    snapshot = PaneSnapshot.from_pane(pane)
    assert snapshot.content == ["$"]
    assert snapshot.pane_id == pane.pane_id
    assert snapshot.window_id == pane.window.window_id
    assert snapshot.session_id == pane.session.session_id
    assert snapshot.server_name == pane.server.socket_name
    assert isinstance(snapshot.timestamp, datetime.datetime)
    assert snapshot.timestamp.tzinfo == datetime.timezone.utc

    # Verify metadata
    assert "pane_id" in snapshot.metadata
    assert "pane_width" in snapshot.metadata
    assert "pane_height" in snapshot.metadata

    # Test string representation
    str_repr = str(snapshot)
    assert "PaneSnapshot" in str_repr
    assert snapshot.pane_id in str_repr
    assert snapshot.window_id in str_repr
    assert snapshot.session_id in str_repr
    assert snapshot.server_name in str_repr
    assert snapshot.timestamp.isoformat() in str_repr
    assert "$" in str_repr


def test_pane_recording(session: Session) -> None:
    """Test creating and managing a PaneRecording."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="recording_test",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None

    recording = PaneRecording()
    assert len(recording) == 0
    assert recording.latest is None

    # Take initial snapshot
    recording.add_snapshot(pane)
    assert len(recording) == 1
    assert recording.latest is not None
    assert recording.latest.content == ["$"]

    # Send some commands and take more snapshots
    pane.send_keys("echo 'Hello'")
    time.sleep(0.1)  # Give tmux time to update
    recording.add_snapshot(pane)

    pane.send_keys("echo 'World'")
    time.sleep(0.1)  # Give tmux time to update
    recording.add_snapshot(pane)

    assert len(recording) == 3

    # Test iteration
    snapshots = list(recording)
    assert len(snapshots) == 3
    assert snapshots[0].content == ["$"]
    assert "Hello" in snapshots[1].content_str
    assert "World" in snapshots[2].content_str

    # Test indexing
    assert recording[0].content == ["$"]
    assert "Hello" in recording[1].content_str
    assert "World" in recording[2].content_str

    # Test time-based filtering
    start_time = snapshots[0].timestamp
    mid_time = snapshots[1].timestamp
    end_time = snapshots[2].timestamp

    assert len(recording.get_snapshots_between(start_time, end_time)) == 3
    assert len(recording.get_snapshots_between(mid_time, end_time)) == 2
