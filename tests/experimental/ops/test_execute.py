"""Tests for the :func:`run` / :func:`arun` execution bridge.

These use in-memory fake engines so they need no tmux server -- the same
property that lets the contract suite run an operation through every engine.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.ops import SendKeys, SplitWindow, arun, run
from libtmux.experimental.ops._types import PaneId, WindowId
from libtmux.experimental.ops.exc import TmuxCommandError

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest


class FakeEngine:
    """A synchronous fake engine that echoes argv and a canned stdout."""

    def __init__(self, stdout: tuple[str, ...] = (), returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[tuple[str, ...]] = []

    def run(self, request: CommandRequest) -> t.Any:
        """Record the request and return a canned result."""
        from libtmux.experimental.engines.base import CommandResult

        self.calls.append(request.args)
        return CommandResult(
            cmd=("tmux", *request.args),
            stdout=self.stdout,
            stderr=() if self.returncode == 0 else ("boom",),
            returncode=self.returncode,
        )

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[t.Any]:
        """Execute each request in order."""
        return [self.run(req) for req in requests]


class AsyncFakeEngine:
    """An asynchronous fake engine mirroring :class:`FakeEngine`."""

    def __init__(self, stdout: tuple[str, ...] = (), returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode

    async def run(self, request: CommandRequest) -> t.Any:
        """Return a canned result asynchronously."""
        from libtmux.experimental.engines.base import CommandResult

        return CommandResult(
            cmd=("tmux", *request.args),
            stdout=self.stdout,
            returncode=self.returncode,
        )

    async def run_batch(self, requests: Sequence[CommandRequest]) -> list[t.Any]:
        """Execute each request in order."""
        return [await self.run(req) for req in requests]


def test_run_returns_typed_result() -> None:
    """``run`` renders, dispatches, and returns the operation's typed result."""
    engine = FakeEngine(stdout=("%9",))
    result = run(SplitWindow(target=WindowId("@1")), engine)
    assert result.new_pane_id == "%9"
    assert result.argv == ("split-window", "-t", "@1", "-v", "-P", "-F", "#{pane_id}")
    assert engine.calls == [result.argv]


def test_run_does_not_raise_on_failure() -> None:
    """A tmux failure is data on the result; ``run`` itself never raises."""
    engine = FakeEngine(returncode=1)
    result = run(SendKeys(target=PaneId("%9"), keys="x"), engine)
    assert result.failed
    with pytest.raises(TmuxCommandError):
        result.raise_for_status()


def test_run_version_threads_through() -> None:
    """The ``version`` argument reaches operation rendering."""
    from libtmux.experimental.ops import CapturePane

    engine = FakeEngine()
    result = run(
        CapturePane(target=PaneId("%1"), trim_trailing=True),
        engine,
        version="3.3",
    )
    assert "-T" not in result.argv


def test_arun_shares_render_and_build() -> None:
    """``arun`` produces the same typed result as ``run`` via the async path."""
    engine = AsyncFakeEngine(stdout=("%5",))
    result = asyncio.run(arun(SplitWindow(target=WindowId("@1")), engine))
    assert result.new_pane_id == "%5"
    assert result.ok
