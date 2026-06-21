"""A deterministic, in-memory engine for tests and docs (no tmux server).

The concrete engine simulates just enough tmux behaviour to exercise the
operation contract without a live server: creation commands that ask for an id
(``-P -F '#{pane_id}'``) get a fabricated, monotonic id, ``capture-pane`` returns
canned lines, and everything else succeeds with empty output. This is what backs
doctests and the cross-engine contract suite, so examples run anywhere and the
"same typed result regardless of engine" invariant can be asserted offline.
"""

from __future__ import annotations

import typing as t

from libtmux.experimental.engines.base import CommandResult

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest


class ConcreteEngine:
    """Execute operations against an in-memory simulation.

    Parameters
    ----------
    capture_lines : Sequence[str]
        Lines that ``capture-pane`` returns.

    Examples
    --------
    >>> from libtmux.experimental.ops import SplitWindow, CapturePane, run
    >>> from libtmux.experimental.ops._types import WindowId, PaneId
    >>> engine = ConcreteEngine(capture_lines=("hello", "world"))
    >>> run(SplitWindow(target=WindowId("@1")), engine).new_pane_id
    '%1'
    >>> run(SplitWindow(target=WindowId("@1")), engine).new_pane_id
    '%2'
    >>> run(CapturePane(target=PaneId("%1")), engine).lines
    ('hello', 'world')
    """

    def __init__(self, *, capture_lines: Sequence[str] = ()) -> None:
        self.capture_lines = tuple(capture_lines)
        self._counters = {"pane_id": 0, "window_id": 0, "session_id": 0}

    def _fabricate(self, fmt: str) -> str:
        """Return the next fabricated id for a ``#{..._id}`` capture format."""
        for key, sigil in (("pane_id", "%"), ("window_id", "@"), ("session_id", "$")):
            if key in fmt:
                self._counters[key] += 1
                return f"{sigil}{self._counters[key]}"
        return "?"

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute one request against the in-memory simulation."""
        argv = request.args
        if "-P" in argv and "-F" in argv:
            fmt = argv[argv.index("-F") + 1]
            return CommandResult(
                cmd=("tmux", *argv),
                stdout=(self._fabricate(fmt),),
                returncode=0,
            )
        if argv and argv[0] == "capture-pane":
            return CommandResult(
                cmd=("tmux", *argv),
                stdout=self.capture_lines,
                returncode=0,
            )
        return CommandResult(cmd=("tmux", *argv), returncode=0)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Execute each request in order (no batching benefit)."""
        return [self.run(req) for req in requests]
