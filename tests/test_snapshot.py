"""Tests for libtmux snapshot functionality."""

from __future__ import annotations

import datetime
import json
import shutil
import time
import typing as t

from libtmux.snapshot import (
    CLIOutputAdapter,
    PaneRecording,
    PaneSnapshot,
    PytestDiffAdapter,
    SyrupySnapshotAdapter,
    TerminalOutputAdapter,
)

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


def test_snapshot_output_adapters(session: Session) -> None:
    """Test the various output adapters for PaneSnapshot."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="adapter_test",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None

    # Create a snapshot with some content
    pane.send_keys("echo 'Test Content'")
    time.sleep(0.1)
    snapshot = pane.snapshot()

    # Test Terminal Output
    terminal_output = snapshot.format(TerminalOutputAdapter())
    assert "\033[1;34m=== Pane Snapshot ===\033[0m" in terminal_output
    assert "\033[1;36mPane:\033[0m" in terminal_output
    assert "Test Content" in terminal_output

    # Test CLI Output
    cli_output = snapshot.format(CLIOutputAdapter())
    assert "=== Pane Snapshot ===" in cli_output
    assert "Pane: " in cli_output
    assert "\033" not in cli_output  # No ANSI codes
    assert "Test Content" in cli_output

    # Test Pytest Diff Output
    pytest_output = snapshot.format(PytestDiffAdapter())
    assert "PaneSnapshot(" in pytest_output
    assert "    pane_id=" in pytest_output
    assert "    content=[" in pytest_output
    assert "    metadata={" in pytest_output
    assert "'Test Content'" in pytest_output

    # Test Syrupy Output
    syrupy_output = snapshot.format(SyrupySnapshotAdapter())
    data = json.loads(syrupy_output)
    assert isinstance(data, dict)
    assert "pane_id" in data
    assert "content" in data
    assert "metadata" in data
    assert "Test Content" in str(data["content"])

    # Test default format (no adapter)
    default_output = snapshot.format()
    assert default_output == str(snapshot)


def test_pane_snapshot_convenience_method(session: Session) -> None:
    """Test the Pane.snapshot() convenience method."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="snapshot_convenience_test",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None

    # Take snapshot using convenience method
    snapshot = pane.snapshot()
    assert snapshot.content == ["$"]
    assert snapshot.pane_id == pane.pane_id
    assert snapshot.window_id == pane.window.window_id
    assert snapshot.session_id == pane.session.session_id
    assert snapshot.server_name == pane.server.socket_name

    # Test with start/end parameters
    pane.send_keys("echo 'Line 1'")
    time.sleep(0.1)
    pane.send_keys("echo 'Line 2'")
    time.sleep(0.1)
    pane.send_keys("echo 'Line 3'")
    time.sleep(0.1)

    snapshot_partial = pane.snapshot(start=1, end=2)
    assert len(snapshot_partial.content) == 2
    assert "Line 1" in snapshot_partial.content_str
    assert "Line 2" in snapshot_partial.content_str
    assert "Line 3" not in snapshot_partial.content_str


def test_pane_record_convenience_method(session: Session) -> None:
    """Test the Pane.record() convenience method."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="record_convenience_test",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None

    # Create recording using convenience method
    recording = pane.record()
    assert isinstance(recording, PaneRecording)
    assert len(recording) == 0

    # Add snapshots to recording
    recording.add_snapshot(pane)
    pane.send_keys("echo 'Test'")
    time.sleep(0.1)
    recording.add_snapshot(pane)

    assert len(recording) == 2
    assert recording[0].content == ["$"]
    assert "Test" in recording[1].content_str
