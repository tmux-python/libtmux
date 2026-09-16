"""Benchmark: Server.sessions / .windows / .panes listing.

Run with::

    $ just bench

Equivalent to::

    $ uv run pytest benchmarks/ -o python_files='bench_*.py' --benchmark-only

Not part of ``pytest``'s default run -- see bench_dispatch.py.
"""

from __future__ import annotations

import pytest
import pytest_benchmark.fixture

from libtmux.session import Session

_WINDOW_COUNT = 8
_PANES_PER_WINDOW = 4


@pytest.fixture
def populated_session(session: Session) -> Session:
    """Return a session with several windows, each split into several panes."""
    for i in range(_WINDOW_COUNT):
        window = session.new_window(window_name=f"bench-{i}", window_shell="sh")
        for _ in range(_PANES_PER_WINDOW - 1):
            window.split(attach=False)
    return session


def test_bench_server_sessions(
    benchmark: pytest_benchmark.fixture.BenchmarkFixture,
    populated_session: Session,
) -> None:
    """Server.sessions: one list-sessions call, decoded into objects."""
    server = populated_session.server
    benchmark(lambda: server.sessions)


def test_bench_server_windows(
    benchmark: pytest_benchmark.fixture.BenchmarkFixture,
    populated_session: Session,
) -> None:
    """Server.windows: one list-windows call across every session."""
    server = populated_session.server
    benchmark(lambda: server.windows)


def test_bench_server_panes(
    benchmark: pytest_benchmark.fixture.BenchmarkFixture,
    populated_session: Session,
) -> None:
    """Server.panes: one list-panes call across every window."""
    server = populated_session.server
    benchmark(lambda: server.panes)
