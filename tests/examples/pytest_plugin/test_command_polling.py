"""Examples for command polling in tmux tests."""

from __future__ import annotations

import time


def test_command_with_polling(session) -> None:
    """Test running a command and polling for completion."""
    # Create a window for testing
    window = session.new_window(window_name="polling-test")
    pane = window.active_pane

    # Clear the pane
    pane.send_keys("clear", enter=True)
    time.sleep(0.3)

    # Run a command that takes some time (using sleep)
    pane.send_keys("echo 'Starting task'; sleep 2; echo 'Task complete'", enter=True)

    # Poll for completion by checking for the completion message
    max_polls = 10
    poll_interval = 0.5
    completion_found = False

    for _ in range(max_polls):
        output = pane.capture_pane()
        if any("Task complete" in line for line in output):
            completion_found = True
            break
        time.sleep(poll_interval)

    # Verify the task completed
    assert completion_found, "Task did not complete within the expected time"

    # Additional verification that both messages are in the output
    final_output = pane.capture_pane()
    assert any("Starting task" in line for line in final_output)
    assert any("Task complete" in line for line in final_output)


def test_error_handling(session) -> None:
    """Test error handling during command execution."""
    # Create a window for testing
    window = session.new_window(window_name="error-test")
    pane = window.active_pane

    # Clear the pane
    pane.send_keys("clear", enter=True)
    time.sleep(0.3)

    # Run a command that will produce an error
    pane.send_keys(
        "echo 'Running command with error'; "
        "ls /nonexistent_directory; "
        "echo 'Command finished'",
        enter=True,
    )
    time.sleep(1)  # Wait for command to complete

    # Capture the output
    output = pane.capture_pane()

    # Verify error message and completion message
    assert any("Running command with error" in line for line in output), (
        "Start message not found"
    )
    assert any("Command finished" in line for line in output), (
        "Completion message not found"
    )

    # Verify error message is in the output
    has_error = any("No such file or directory" in line for line in output) or any(
        "cannot access" in line for line in output
    )
    assert has_error, "Error message not found in output"
