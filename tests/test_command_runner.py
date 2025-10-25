"""Test command runner abstraction."""

from __future__ import annotations

import typing as t

from libtmux._internal.engines import SubprocessCommandRunner
from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_subprocess_runner_instantiation() -> None:
    """SubprocessCommandRunner can be instantiated."""
    runner = SubprocessCommandRunner()
    assert runner is not None


def test_subprocess_runner_has_run_method() -> None:
    """SubprocessCommandRunner has run method."""
    runner = SubprocessCommandRunner()
    assert hasattr(runner, "run")
    assert callable(runner.run)


def test_server_default_runner(server: Server) -> None:
    """Server uses subprocess runner by default."""
    assert server.command_runner is not None
    assert isinstance(server.command_runner, SubprocessCommandRunner)


def test_server_custom_runner() -> None:
    """Server accepts custom command runner."""
    custom_runner = SubprocessCommandRunner()
    server = Server(socket_name="test", command_runner=custom_runner)
    assert server.command_runner is custom_runner


def test_server_runner_lazy_init() -> None:
    """Server lazily initializes command runner."""
    server = Server(socket_name="test")
    # Access property to trigger lazy init
    runner = server.command_runner
    assert isinstance(runner, SubprocessCommandRunner)
    # Second access returns same instance
    assert server.command_runner is runner


def test_runner_returns_tmux_cmd(server: Server, session: Session) -> None:
    """Command runner returns tmux_cmd objects."""
    from libtmux.common import tmux_cmd

    result = server.cmd("list-sessions")
    assert isinstance(result, tmux_cmd)
    assert hasattr(result, "stdout")
    assert hasattr(result, "stderr")
    assert hasattr(result, "returncode")
    assert hasattr(result, "cmd")


def test_runner_executes_real_tmux(server: Server) -> None:
    """Command runner executes real tmux (not mocked)."""
    # Create a session
    _ = server.new_session("test_runner")

    # List sessions through runner
    result = server.cmd("list-sessions")

    # Verify real tmux was executed
    assert any("test_runner" in line for line in result.stdout)
    assert result.returncode == 0


def test_runner_subprocess_integration(server: Server) -> None:
    """SubprocessCommandRunner integrates with Server.cmd()."""
    # Verify the runner is being used
    assert isinstance(server.command_runner, SubprocessCommandRunner)

    # Execute a command
    result = server.cmd("list-sessions")

    # Verify result structure
    assert isinstance(result.stdout, list)
    assert isinstance(result.stderr, list)
    assert isinstance(result.returncode, int)
    assert isinstance(result.cmd, list)


def test_server_cmd_uses_runner(server: Server) -> None:
    """Server.cmd() uses command_runner internally."""
    _ = server.new_session("test_cmd_uses_runner")

    # Execute command
    result = server.cmd("list-sessions")

    # Verify it went through the runner
    assert result.returncode == 0
    assert any("test_cmd_uses_runner" in line for line in result.stdout)


def test_runner_with_test_server_factory(TestServer: t.Callable[..., Server]) -> None:
    """TestServer factory works with command runner."""
    server1 = TestServer()
    server2 = TestServer()

    # Both should have command runners
    assert server1.command_runner is not None
    assert server2.command_runner is not None

    # Both should use SubprocessCommandRunner
    assert isinstance(server1.command_runner, SubprocessCommandRunner)
    assert isinstance(server2.command_runner, SubprocessCommandRunner)


def test_backward_compatibility_no_runner_param(server: Server) -> None:
    """Server works without command_runner parameter (backward compatibility)."""
    # Create server without command_runner parameter
    new_server = Server(socket_name=f"test_{server.socket_name}")

    # Should auto-initialize with SubprocessCommandRunner
    assert new_server.command_runner is not None
    assert isinstance(new_server.command_runner, SubprocessCommandRunner)

    # Should be able to execute commands
    result = new_server.cmd("list-sessions")
    assert hasattr(result, "stdout")


def test_runner_setter() -> None:
    """Server.command_runner can be set after initialization."""
    server = Server(socket_name="test")

    # Initial runner
    initial_runner = server.command_runner
    assert isinstance(initial_runner, SubprocessCommandRunner)

    # Set new runner
    new_runner = SubprocessCommandRunner()
    server.command_runner = new_runner

    # Verify it changed
    assert server.command_runner is new_runner
    assert server.command_runner is not initial_runner
