"""Benchmark: Pane.capture_pane() snapshot capture.

Run with::

    $ uv run pytest benchmarks/ --benchmark-only

Not part of ``pytest``'s default run -- see bench_dispatch.py.
"""

from __future__ import annotations

import pytest
import pytest_benchmark.fixture

from libtmux.pane import Pane
from libtmux.session import Session
from libtmux.test.retry import retry_until

_SCROLLBACK_LINES = 200


@pytest.fixture
def pane_with_scrollback(session: Session) -> Pane:
    """Return a pane with a full screen of numbered scrollback lines."""
    window = session.new_window(window_name="bench-capture", window_shell="sh")
    pane = window.active_pane
    assert pane is not None
    fill_command = (
        f"i=0; while [ $i -lt {_SCROLLBACK_LINES} ]; do "
        "echo line-$i; i=$((i+1)); done; echo capture-bench-done"
    )
    pane.send_keys(fill_command)
    retry_until(
        lambda: any(
            line.rstrip(" ") == "capture-bench-done" for line in pane.capture_pane()
        ),
        raises=True,
    )
    return pane


def test_bench_capture_pane(
    benchmark: pytest_benchmark.fixture.BenchmarkFixture,
    pane_with_scrollback: Pane,
) -> None:
    """capture_pane(): one list-panes read plus the visible screen text."""
    benchmark(pane_with_scrollback.capture_pane)
