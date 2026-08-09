"""Examples of testing window management operations."""

from __future__ import annotations

import time


def test_window_renaming(session) -> None:
    """Test renaming windows."""
    # Create a window with initial name
    initial_name = "initial-window"
    window = session.new_window(window_name=initial_name)
    assert window.window_name == initial_name

    # Rename the window
    new_name = "renamed-window"
    window.rename_window(new_name)
    window.refresh()
    assert window.window_name == new_name

    # Verify the window name in the server's list
    window_list = session.server.cmd("list-windows", "-t", session.id).stdout
    assert new_name in "\n".join(window_list)


def test_window_moving(session) -> None:
    """Test moving windows within a session."""
    # Create multiple windows
    window1 = session.new_window(window_name="window-1")
    session.new_window(window_name="window-2")
    window3 = session.new_window(window_name="window-3")

    # Let tmux settle
    time.sleep(0.5)

    # Get initial indices
    index1 = window1.index

    # Move window 1 to the end
    window1.move_window()

    # Refresh windows
    session.refresh()
    window1.refresh()

    # Verify window 1 has moved
    assert window1.index != index1

    # Get a free index for window 3 to move to
    # Note: We can't just use index 1 as it might be taken
    all_indices = [int(w.index) for w in session.windows]
    for i in range(1, 10):
        if i not in all_indices:
            free_index = str(i)
            break
    else:
        free_index = "10"  # Fallback

    # Move window 3 to free index
    initial_index3 = window3.index
    window3.move_window(destination=free_index)

    # Refresh windows
    session.refresh()
    window3.refresh()

    # Verify window 3 has moved
    assert window3.index != initial_index3


def test_window_switching(session) -> None:
    """Test switching between windows in a session."""
    # Create multiple windows
    window1 = session.new_window(window_name="switch-test-1")
    window2 = session.new_window(window_name="switch-test-2")
    window3 = session.new_window(window_name="switch-test-3")

    # Give tmux time to update
    time.sleep(0.5)

    # Refresh session to get current state
    session.refresh()

    # Tmux may set any window as active - can vary across platforms
    # So first we'll explicitly set window3 as active
    session.select_window(window3.index)
    time.sleep(0.5)
    session.refresh()

    # Now verify window 3 is active
    assert session.active_window.id == window3.id, (
        f"Expected active window {window3.id}, got {session.active_window.id}"
    )

    # Switch to window 1
    session.select_window(window1.index)
    time.sleep(0.5)

    # Refresh the session information
    session.refresh()

    # Verify window 1 is now active
    assert session.active_window.id == window1.id, (
        f"Expected active window {window1.id}, got {session.active_window.id}"
    )

    # Switch to window 2 by name
    session.select_window("switch-test-2")
    time.sleep(0.5)

    # Refresh the session information
    session.refresh()

    # Verify window 2 is now active
    assert session.active_window.id == window2.id, (
        f"Expected active window {window2.id}, got {session.active_window.id}"
    )


def test_window_killing(session) -> None:
    """Test killing windows."""
    # Create multiple windows
    window1 = session.new_window(window_name="kill-test-1")
    window2 = session.new_window(window_name="kill-test-2")
    window3 = session.new_window(window_name="kill-test-3")

    # Count initial windows
    initial_count = len(session.windows)

    # Kill window 2
    window2.kill()

    # Refresh session data
    session.refresh()  # This refreshes the windows

    # Verify window was killed
    assert len(session.windows) == initial_count - 1

    # Check window IDs to verify the right window was killed
    window_ids = [w.id for w in session.windows]
    assert window2.id not in window_ids

    # Verify other windows still exist
    assert window1.id in window_ids
    assert window3.id in window_ids
