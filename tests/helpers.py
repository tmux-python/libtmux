"""Test helpers for control-mode flakiness handling."""

from __future__ import annotations

import time
import typing as t

from libtmux.pane import Pane


def wait_for_line(
    pane: Pane,
    predicate: t.Callable[[str], bool],
    *,
    timeout: float = 1.0,
    interval: float = 0.05,
) -> list[str]:
    """Poll capture_pane until a line satisfies ``predicate``.

    Returns the final capture buffer (may be empty if timeout elapses).
    """
    deadline = time.monotonic() + timeout
    last: list[str] = []
    while time.monotonic() < deadline:
        captured = pane.capture_pane()
        last = [captured] if isinstance(captured, str) else list(captured)
        if any(predicate(line) for line in last):
            break
        time.sleep(interval)
    return last
