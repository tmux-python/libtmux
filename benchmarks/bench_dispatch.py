"""Benchmark: Server.cmd() dispatch, the primitive every wrapper method uses.

Run with::

    $ just bench

Equivalent to::

    $ uv run pytest benchmarks/ -o python_files='bench_*.py' --benchmark-only

Not part of ``pytest``'s default run -- ``benchmarks/`` is not in
``testpaths``, and performance work is a separate tier from the test-loop
budgets in CONTRIBUTING.md, not part of them.
"""

from __future__ import annotations

import pytest_benchmark.fixture

from libtmux.session import Session


def test_bench_command_dispatch(
    benchmark: pytest_benchmark.fixture.BenchmarkFixture,
    session: Session,
) -> None:
    """One round trip through Server.cmd(): fork, exec, read, parse exit."""
    server = session.server
    benchmark(server.cmd, "display-message", "-p", "#{session_name}")
