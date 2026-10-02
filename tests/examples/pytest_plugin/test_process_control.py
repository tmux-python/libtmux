"""Examples of testing process control and monitoring."""

from __future__ import annotations

import pytest

from libtmux.test.retry import retry_until


@pytest.fixture
def window(session):
    """Create a window for testing."""
    return session.new_window(window_name="process-test")


@pytest.fixture
def pane(window):
    """Create a pane for testing."""
    pane = window.active_pane
    # Clear the pane at the start
    pane.send_keys("clear", enter=True)

    def pane_is_cleared() -> bool:
        pane_contents = "\n".join(pane.capture_pane())
        return "clear" not in pane_contents

    retry_until(pane_is_cleared, 1)
    return pane


def test_process_detection(pane) -> None:
    """Test detecting running processes in a pane."""
    # Start a long-running process
    pane.send_keys("sleep 10 &", enter=True)

    # Get the pane's TTY
    pane_tty = pane.cmd("display-message", "-p", "#{pane_tty}").stdout[0]

    # Run ps command to list processes
    pane.send_keys(f"ps -t {pane_tty} -o pid,command | grep sleep", enter=True)

    def ps_output_contains_sleep() -> bool:
        ps_output = pane.capture_pane()
        return any("sleep 10" in line for line in ps_output)

    retry_until(ps_output_contains_sleep, 3)

    # Capture the output
    ps_output = pane.capture_pane()

    # Verify the sleep command is running
    assert any("sleep 10" in line for line in ps_output), (
        f"Expected 'sleep 10' in: {ps_output}"
    )

    # Clear the pane
    pane.send_keys("clear", enter=True)

    def pane_is_cleared() -> bool:
        pane_contents = "\n".join(pane.capture_pane())
        return "clear" not in pane_contents

    retry_until(pane_is_cleared, 1)

    # Kill the process (find PID and kill it)
    pane.send_keys("pkill -f 'sleep 10'", enter=True)

    # Run ps command again to verify process is gone
    pane.send_keys(
        f"ps -t {pane_tty} -o pid,command | grep sleep || echo 'Process not found'",
        enter=True,
    )

    def process_is_killed() -> bool:
        ps_output = pane.capture_pane()
        return any("Process not found" in line for line in ps_output)

    retry_until(process_is_killed, 3)

    # Verify the process has stopped
    ps_output = pane.capture_pane()

    # The output might contain a message like '[1]  + terminated  sleep 10'
    # but this indicates the process has been terminated, not that it's running
    is_running = False
    for line in ps_output:
        # Look for a line with PID and 'sleep 10' without being a command or
        # termination message
        # Check for command prompts in different environments (local and CI)
        is_command_line = (
            line.startswith(("d%", "runner@"))
            or "grep sleep" in line
            or "$" in line
            or "pkill" in line
        )
        is_termination = "terminated" in line

        if (
            "sleep 10" in line
            and not is_command_line
            and not is_termination
            and "Process not found" not in line
        ):
            is_running = True
            break

    assert not is_running, f"Found running 'sleep 10' in: {ps_output}"


def test_command_output_scrollback(pane) -> None:
    """Test handling command output that exceeds visible pane height."""
    # Generate a lot of output
    pane.send_keys('for i in $(seq 1 100); do echo "Line $i"; done', enter=True)

    def output_generated() -> bool:
        output = pane.capture_pane(start="-100")
        lines_with_numbers = [line for line in output if "Line " in line]
        return len(lines_with_numbers) > 50

    retry_until(output_generated, 3)

    # Capture all the scrollback buffer
    output = pane.capture_pane(start="-100")

    # Check that we have captured a large portion of the output
    assert len(output) > 50

    # Verify the beginning and end of the captured output
    final_lines = [line for line in output if "Line " in line]
    if final_lines:
        line_numbers = [
            int(line.split("Line ")[1])
            for line in final_lines
            if line.split("Line ")[1].isdigit()
        ]
        if line_numbers:
            assert max(line_numbers) > min(line_numbers)

    # Clear the scrollback buffer
    pane.clear()

    def buffer_cleared() -> bool:
        cleared_output = pane.capture_pane()
        return len([line for line in cleared_output if line.strip()]) <= 1

    retry_until(buffer_cleared, 1)

    # Verify the buffer is now empty or only has the prompt
    cleared_output = pane.capture_pane()
    assert len([line for line in cleared_output if line.strip()]) <= 1


def test_running_background_process(pane) -> None:
    """Test running a process in the background."""
    # Start a background process that writes to a file
    pane.send_keys("touch /tmp/background_test.txt", enter=True)
    pane.send_keys(
        "(for i in $(seq 1 5); do "
        "echo 'Update $i' >> /tmp/background_test.txt; "
        "sleep 0.1; "
        "done) &",
        enter=True,
    )

    # Send a simple command with a unique string to verify responsiveness
    pane.send_keys("echo 'UNIQUE_BACKGROUND_STRING_789'", enter=True)

    def unique_string_in_output() -> bool:
        output = pane.capture_pane()
        return any("UNIQUE_BACKGROUND_STRING_789" in line for line in output)

    retry_until(unique_string_in_output, 2)

    # Verify the command was executed
    output = pane.capture_pane()
    assert any("UNIQUE_BACKGROUND_STRING_789" in line for line in output)

    # Check the file periodically
    pane.send_keys("cat /tmp/background_test.txt", enter=True)

    def updates_in_file() -> bool:
        output = pane.capture_pane()
        return any("Update" in line for line in output)

    retry_until(updates_in_file, 3)

    # Verify we got at least some updates
    output = pane.capture_pane()
    assert any("Update" in line for line in output)

    # Clean up
    pane.send_keys("rm /tmp/background_test.txt", enter=True)
