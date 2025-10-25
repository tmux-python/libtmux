"""Integration tests for ControlModeCommandRunner.

IMPORTANT: All tests use REAL tmux - no mocks!
"""

from __future__ import annotations

import threading
import typing as t

import pytest

from libtmux._internal.engines.control_mode import ControlModeCommandRunner
from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_runner_connects_to_tmux(server: Server) -> None:
    """ControlModeCommandRunner establishes connection to real tmux."""
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)

    assert runner._process is not None
    assert runner._process.poll() is None  # Still running
    assert runner._parser is not None

    runner.close()


def test_runner_executes_command(server: Server) -> None:
    """Runner executes commands against real tmux."""
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)

    # Create session via normal server
    _ = server.new_session("test_control_mode")

    # Execute list-sessions via control mode
    result = runner.run("-L", server.socket_name, "list-sessions")

    assert result.returncode == 0
    assert len(result.stdout) > 0
    assert any("test_control_mode" in line for line in result.stdout)

    runner.close()


def test_runner_filters_server_flags(server: Server) -> None:
    """Runner correctly filters -L/-S/-f flags."""
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)

    # Create test session
    _ = server.new_session("filter_test")

    # Send command with server flags (as Server.cmd() would)
    result = runner.run(
        "-L",
        server.socket_name,
        "-2",  # Color flag (should be filtered)
        "list-sessions",
    )

    # Should work despite flags
    assert result.returncode == 0
    assert any("filter_test" in line for line in result.stdout)

    runner.close()


def test_runner_multiple_commands_sequential(server: Server) -> None:
    """Runner handles multiple commands in sequence."""
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)

    # Execute multiple commands
    result1 = runner.run("-L", server.socket_name, "new-session", "-d", "-s", "seq1")
    assert result1.returncode == 0

    result2 = runner.run("-L", server.socket_name, "new-session", "-d", "-s", "seq2")
    assert result2.returncode == 0

    result3 = runner.run("-L", server.socket_name, "list-sessions")
    assert result3.returncode == 0
    assert any("seq1" in line for line in result3.stdout)
    assert any("seq2" in line for line in result3.stdout)

    runner.close()


def test_runner_handles_command_error(server: Server) -> None:
    """Runner correctly handles command errors."""
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)

    # Execute invalid command
    result = runner.run("-L", server.socket_name, "invalid-command-xyz")

    # Should return error (not raise exception)
    assert result.returncode == 1
    assert len(result.stdout) > 0
    # Error message should mention unknown command
    assert any(
        "unknown command" in line.lower() or "parse error" in line.lower()
        for line in result.stdout
    )

    runner.close()


def test_runner_context_manager(server: Server) -> None:
    """Context manager closes connection automatically."""
    assert server.socket_name
    session_created = False

    with ControlModeCommandRunner(server.socket_name) as runner:
        result = runner.run(
            "-L", server.socket_name, "new-session", "-d", "-s", "ctx_test"
        )
        session_created = result.returncode == 0

    # Connection should be closed after context exit
    assert session_created
    # Verify session was created (using regular server)
    assert server.has_session("ctx_test")


def test_runner_close_is_idempotent(server: Server) -> None:
    """close() can be called multiple times safely."""
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)

    runner.close()
    runner.close()  # Should not raise
    runner.close()  # Should not raise


def test_runner_detects_closed_connection(server: Server) -> None:
    """Runner detects when connection is closed."""
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)
    runner.close()

    with pytest.raises(ConnectionError, match="not connected"):
        runner.run("-L", server.socket_name, "list-sessions")


def test_runner_thread_safety(server: Server) -> None:
    """Multiple threads can use same runner safely."""
    assert server.socket_name
    socket_name = server.socket_name  # Store for closure
    runner = ControlModeCommandRunner(socket_name)
    results: list[bool] = []
    errors: list[Exception] = []

    def create_session(name: str) -> None:
        try:
            result = runner.run("-L", socket_name, "new-session", "-d", "-s", name)
            results.append(result.returncode == 0)
        except Exception as e:
            errors.append(e)

    # Spawn 5 threads creating sessions concurrently
    threads = [
        threading.Thread(target=create_session, args=(f"thread_{i}",)) for i in range(5)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # All should succeed
    assert len(errors) == 0, f"Errors occurred: {errors}"
    assert all(results), "Not all sessions created successfully"

    # Verify all sessions exist
    list_result = runner.run("-L", socket_name, "list-sessions")
    for i in range(5):
        assert any(f"thread_{i}" in line for line in list_result.stdout)

    runner.close()


def test_runner_preserves_output_format(server: Server, session: Session) -> None:
    """Control mode output matches subprocess output format."""
    assert server.socket_name
    from libtmux._internal.engines import SubprocessCommandRunner

    # Create sessions/windows via normal server
    _ = session.new_window("win1")
    _ = session.new_window("win2")

    # Get output via subprocess
    subprocess_runner = SubprocessCommandRunner()
    subprocess_result = subprocess_runner.run(
        "-L", server.socket_name, "list-windows", "-t", session.session_id or "$0"
    )

    # Get output via control mode
    control_runner = ControlModeCommandRunner(server.socket_name)
    control_result = control_runner.run(
        "-L", server.socket_name, "list-windows", "-t", session.session_id or "$0"
    )

    # Both should succeed
    assert subprocess_result.returncode == 0
    assert control_result.returncode == 0

    # Both should have same number of lines (same windows)
    assert len(subprocess_result.stdout) == len(control_result.stdout)

    # Both should mention same windows
    subprocess_text = " ".join(subprocess_result.stdout)
    control_text = " ".join(control_result.stdout)
    assert "win1" in subprocess_text
    assert "win1" in control_text
    assert "win2" in subprocess_text
    assert "win2" in control_text

    control_runner.close()


def test_runner_with_server_integration(server: Server) -> None:
    """Server works correctly with control mode runner.

    Control mode runner transparently falls back to subprocess for commands
    with format strings (-F flag), ensuring all operations work correctly.
    """
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)

    # Create server with control mode runner
    cm_server = Server(
        socket_name=server.socket_name,
        command_runner=runner,
    )

    # All normal operations should work
    session = cm_server.new_session("cm_integration_test")
    assert session.session_name == "cm_integration_test"

    window = session.new_window("test_window")
    assert window.window_name == "test_window"

    # Verify runner was actually used
    assert isinstance(cm_server.command_runner, ControlModeCommandRunner)

    runner.close()


def test_runner_handles_empty_response(server: Server) -> None:
    """Runner handles commands with no output."""
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)

    # Create a session (output goes to stdout but we use -d for detached)
    result = runner.run(
        "-L", server.socket_name, "new-session", "-d", "-s", "empty_test"
    )

    # Should succeed
    assert result.returncode == 0
    # Output might be empty or minimal
    assert isinstance(result.stdout, list)

    runner.close()


def test_runner_large_output(server: Server) -> None:
    """Runner handles commands with large output."""
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)

    # Create many sessions
    for i in range(20):
        runner.run("-L", server.socket_name, "new-session", "-d", "-s", f"large_{i}")

    # List all sessions (large output)
    result = runner.run("-L", server.socket_name, "list-sessions")

    assert result.returncode == 0
    assert len(result.stdout) >= 20

    runner.close()


def test_runner_command_with_special_characters(server: Server) -> None:
    """Runner handles commands with special characters."""
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)

    # Create session with special characters in name
    session_name = "test-session_123"
    result = runner.run(
        "-L", server.socket_name, "new-session", "-d", "-s", session_name
    )

    assert result.returncode == 0

    # Verify it was created
    list_result = runner.run("-L", server.socket_name, "list-sessions")
    assert any(session_name in line for line in list_result.stdout)

    runner.close()


def test_runner_result_has_cmd_attribute(server: Server) -> None:
    """Runner result includes cmd attribute for debugging."""
    assert server.socket_name
    runner = ControlModeCommandRunner(server.socket_name)

    result = runner.run("-L", server.socket_name, "list-sessions")

    assert hasattr(result, "cmd")
    assert isinstance(result.cmd, list)
    assert "tmux" in result.cmd
    assert "-C" in result.cmd
    assert "list-sessions" in result.cmd

    runner.close()
