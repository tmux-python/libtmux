"""Test the snapshot factory module."""

from __future__ import annotations

import pytest

from libtmux.server import Server
from libtmux.session import Session
from libtmux.snapshot.factory import create_snapshot, create_snapshot_active
from libtmux.snapshot.models.pane import PaneSnapshot
from libtmux.snapshot.models.server import ServerSnapshot
from libtmux.snapshot.models.session import SessionSnapshot
from libtmux.snapshot.models.window import WindowSnapshot


def test_create_snapshot_server(server: Server) -> None:
    """Test creating a snapshot of a server."""
    snapshot = create_snapshot(server)
    assert isinstance(snapshot, ServerSnapshot)
    assert snapshot._is_snapshot


def test_create_snapshot_session(session: Session) -> None:
    """Test creating a snapshot of a session."""
    snapshot = create_snapshot(session)
    assert isinstance(snapshot, SessionSnapshot)
    assert snapshot._is_snapshot


# We don't have a window fixture, so create one from the session
def test_create_snapshot_window(session: Session) -> None:
    """Test creating a snapshot of a window."""
    window = session.active_window
    assert window is not None, "Session has no active window"
    snapshot = create_snapshot(window)
    assert isinstance(snapshot, WindowSnapshot)
    assert snapshot._is_snapshot


# We don't have a pane fixture, so create one from the session
def test_create_snapshot_pane(session: Session) -> None:
    """Test creating a snapshot of a pane."""
    window = session.active_window
    assert window is not None, "Session has no active window"
    pane = window.active_pane
    assert pane is not None, "Window has no active pane"
    snapshot = create_snapshot(pane)
    assert isinstance(snapshot, PaneSnapshot)
    assert snapshot._is_snapshot


def test_create_snapshot_capture_content(session: Session) -> None:
    """Test creating a snapshot with content capture."""
    window = session.active_window
    assert window is not None, "Session has no active window"
    pane = window.active_pane
    assert pane is not None, "Window has no active pane"
    snapshot = create_snapshot(pane, capture_content=True)
    assert isinstance(snapshot, PaneSnapshot)
    assert snapshot._is_snapshot
    # In tests, content might be empty, but it should be available
    assert hasattr(snapshot, "pane_content")


def test_create_snapshot_unsupported() -> None:
    """Test creating a snapshot of an unsupported object."""
    with pytest.raises(TypeError):
        # Type checking would prevent this, but we test it for runtime safety
        create_snapshot("not a tmux object")  # type: ignore


def test_create_snapshot_active(server: Server) -> None:
    """Test creating a snapshot with only active components."""
    snapshot = create_snapshot_active(server)
    assert isinstance(snapshot, ServerSnapshot)
    assert snapshot._is_snapshot


def test_fluent_to_dict(server: Server) -> None:
    """Test the to_dict method on snapshots."""
    snapshot = create_snapshot(server)
    dict_data = snapshot.to_dict()
    assert isinstance(dict_data, dict)
    # The ServerSnapshot may not have created_at field in the test environment,
    # but it should have the sessions_snapshot field
    assert "sessions_snapshot" in dict_data


def test_fluent_filter(server: Server) -> None:
    """Test the filter method on snapshots."""
    snapshot = create_snapshot(server)
    # Filter to include everything
    filtered = snapshot.filter(lambda x: True)
    assert filtered is not None
    assert isinstance(filtered, ServerSnapshot)

    # Filter to include nothing
    filtered = snapshot.filter(lambda x: False)
    assert filtered is None


def test_fluent_active_only(server: Server) -> None:
    """Test the active_only method on snapshots."""
    snapshot = create_snapshot(server)
    active = snapshot.active_only()
    assert active is not None
    assert isinstance(active, ServerSnapshot)


def test_fluent_active_only_not_server(session: Session) -> None:
    """Test that active_only raises NotImplementedError on non-server snapshots."""
    snapshot = create_snapshot(session)
    with pytest.raises(NotImplementedError):
        snapshot.active_only()
