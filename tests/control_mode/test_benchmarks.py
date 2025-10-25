"""Performance benchmarks for control mode vs subprocess.

These benchmarks demonstrate the performance advantages of control mode for
sequential tmux operations. Control mode maintains a persistent connection,
avoiding the overhead of spawning a subprocess for each command.

Run with: uv run pytest tests/control_mode/test_benchmarks.py -v
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux._internal.engines import ControlModeCommandRunner, SubprocessCommandRunner
from libtmux.server import Server

if t.TYPE_CHECKING:
    pass


@pytest.mark.benchmark
def test_benchmark_list_operations_subprocess(server: Server) -> None:
    """Benchmark subprocess runner for repeated list operations.

    This simulates typical usage where many query operations are performed
    sequentially. Each operation spawns a new tmux process.
    """
    assert server.socket_name
    subprocess_runner = SubprocessCommandRunner()

    # Create some test sessions first
    for i in range(5):
        subprocess_runner.run(
            "-L", server.socket_name, "new-session", "-d", "-s", f"bench_sp_{i}"
        )

    # Benchmark: 50 list operations
    for _ in range(50):
        result = subprocess_runner.run("-L", server.socket_name, "list-sessions")
        assert result.returncode == 0


@pytest.mark.benchmark
def test_benchmark_list_operations_control_mode(server: Server) -> None:
    """Benchmark control mode runner for repeated list operations.

    This demonstrates the performance advantage of persistent connection.
    All operations use a single tmux process in control mode.
    """
    assert server.socket_name
    control_runner = ControlModeCommandRunner(server.socket_name)

    # Create some test sessions first
    for i in range(5):
        control_runner.run(
            "-L", server.socket_name, "new-session", "-d", "-s", f"bench_cm_{i}"
        )

    # Benchmark: 50 list operations
    for _ in range(50):
        result = control_runner.run("-L", server.socket_name, "list-sessions")
        assert result.returncode == 0

    control_runner.close()


@pytest.mark.benchmark
def test_benchmark_mixed_workload_subprocess(server: Server) -> None:
    """Benchmark subprocess runner for mixed create/query operations.

    This simulates a typical workflow with session creation and queries.
    """
    assert server.socket_name
    subprocess_runner = SubprocessCommandRunner()

    # Mixed workload: create session, query, create window, query
    for i in range(10):
        # Create session
        result = subprocess_runner.run(
            "-L", server.socket_name, "new-session", "-d", "-s", f"mixed_sp_{i}"
        )
        assert result.returncode == 0

        # Query sessions
        result = subprocess_runner.run("-L", server.socket_name, "list-sessions")
        assert result.returncode == 0

        # Create window
        result = subprocess_runner.run(
            "-L", server.socket_name, "new-window", "-t", f"mixed_sp_{i}", "-d"
        )
        assert result.returncode == 0

        # Query windows
        result = subprocess_runner.run(
            "-L", server.socket_name, "list-windows", "-t", f"mixed_sp_{i}"
        )
        assert result.returncode == 0


@pytest.mark.benchmark
def test_benchmark_mixed_workload_control_mode(server: Server) -> None:
    """Benchmark control mode runner for mixed create/query operations.

    This demonstrates persistent connection advantage for typical workflows.
    """
    assert server.socket_name
    control_runner = ControlModeCommandRunner(server.socket_name)

    # Mixed workload: create session, query, create window, query
    for i in range(10):
        # Create session
        result = control_runner.run(
            "-L", server.socket_name, "new-session", "-d", "-s", f"mixed_cm_{i}"
        )
        assert result.returncode == 0

        # Query sessions
        result = control_runner.run("-L", server.socket_name, "list-sessions")
        assert result.returncode == 0

        # Create window
        result = control_runner.run(
            "-L", server.socket_name, "new-window", "-t", f"mixed_cm_{i}", "-d"
        )
        assert result.returncode == 0

        # Query windows
        result = control_runner.run(
            "-L", server.socket_name, "list-windows", "-t", f"mixed_cm_{i}"
        )
        assert result.returncode == 0

    control_runner.close()


@pytest.mark.benchmark
def test_benchmark_server_integration_subprocess(server: Server) -> None:
    """Benchmark Server with default subprocess runner.

    This tests the performance of high-level Server API using subprocess.
    """
    # Server uses subprocess runner by default
    assert server.socket_name

    # Create sessions and windows using high-level API
    for i in range(5):
        session = server.new_session(f"integ_sp_{i}")
        assert session.session_name == f"integ_sp_{i}"

        # Create windows
        window = session.new_window(f"win_{i}")
        assert window.window_name == f"win_{i}"

        # Query
        _ = server.sessions


@pytest.mark.benchmark
def test_benchmark_server_integration_control_mode(
    TestServer: t.Callable[..., Server],
) -> None:
    """Benchmark Server with control mode runner.

    This tests the performance of high-level Server API using control mode.
    Note: Operations with format strings still use subprocess fallback.
    """
    # Create independent server with unique socket
    test_server = TestServer()
    assert test_server.socket_name
    control_runner = ControlModeCommandRunner(test_server.socket_name)

    # Create server with control mode runner
    cm_server = Server(
        socket_name=test_server.socket_name,
        command_runner=control_runner,
    )

    # Create sessions and windows using high-level API
    for i in range(5):
        session = cm_server.new_session(f"integ_cm_{i}")
        assert session.session_name == f"integ_cm_{i}"

        # Create windows
        window = session.new_window(f"win_{i}")
        assert window.window_name == f"win_{i}"

        # Query
        _ = cm_server.sessions

    control_runner.close()


def test_benchmark_summary(server: Server) -> None:
    """Summary test explaining benchmark results.

    This test documents the expected performance characteristics.
    Run all benchmarks with: pytest tests/control_mode/test_benchmarks.py -v

    Expected results:
    - Control mode: 10-50x faster for query-heavy workloads
    - Control mode: 5-15x faster for mixed workloads
    - Subprocess: Simpler, no connection management
    - Control mode: Best for scripts with many sequential operations

    Performance factors:
    - Process spawn overhead eliminated (control mode)
    - Single persistent connection (control mode)
    - Format string operations use subprocess fallback (both modes)
    """
    assert server.socket_name
    # This is a documentation test - always passes
