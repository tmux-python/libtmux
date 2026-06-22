"""Deterministic, in-memory engines for tests and docs (no tmux server).

The concrete engines simulate just enough tmux behaviour to exercise the
operation contract offline: creation commands that ask for an id
(``-P -F '#{pane_id}'``) get a fabricated, monotonic id, ``capture-pane`` returns
canned lines, and everything else succeeds with empty output. A sync
(:class:`ConcreteEngine`) and async (:class:`AsyncConcreteEngine`) variant share
the same simulation, so the same operation returns the same typed result through
either, with no tmux required.
"""

from __future__ import annotations

import typing as t

from libtmux.experimental.engines.base import CommandResult

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest


def _fabricate(fmt: str, counters: dict[str, int]) -> str:
    """Fabricate one id per ``#{..._id}`` token in *fmt*, in their order.

    A single-token format (e.g. ``#{pane_id}``) yields one id, preserving the
    historical behaviour; a multi-token capture (e.g. ``new-session -F
    '#{session_id} #{window_id} #{pane_id}'``) yields a space-joined id per token.
    """
    found: list[tuple[int, str, str]] = []
    for key, sigil in (("session_id", "$"), ("window_id", "@"), ("pane_id", "%")):
        index = fmt.find(f"#{{{key}}}")
        if index != -1:
            found.append((index, key, sigil))
    if not found:
        return "?"
    parts: list[str] = []
    for _index, key, sigil in sorted(found):
        counters[key] += 1
        parts.append(f"{sigil}{counters[key]}")
    return " ".join(parts)


def _simulate(
    argv: tuple[str, ...],
    counters: dict[str, int],
    capture_lines: tuple[str, ...],
) -> CommandResult:
    """Produce a deterministic result for a rendered tmux command."""
    if "-P" in argv and "-F" in argv:
        fmt = argv[argv.index("-F") + 1]
        return CommandResult(
            cmd=("tmux", *argv),
            stdout=(_fabricate(fmt, counters),),
            returncode=0,
        )
    if argv and argv[0] == "capture-pane":
        return CommandResult(cmd=("tmux", *argv), stdout=capture_lines, returncode=0)
    return CommandResult(cmd=("tmux", *argv), returncode=0)


def _new_counters() -> dict[str, int]:
    """Return a fresh id-counter map."""
    return {"pane_id": 0, "window_id": 0, "session_id": 0}


class ConcreteEngine:
    """Execute operations against an in-memory simulation (synchronous).

    Parameters
    ----------
    capture_lines : Sequence[str]
        Lines that ``capture-pane`` returns.

    Notes
    -----
    The simulation is stateless -- it fabricates ids for ``-P -F`` creators and
    returns canned ``capture-pane`` lines, but has no notion of which objects
    exist, so queries like ``has-session`` always succeed (``HasSession.exists``
    is always ``True``). Use a live engine for those.

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
        self._counters = _new_counters()

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute one request against the in-memory simulation."""
        return _simulate(request.args, self._counters, self.capture_lines)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Execute each request in order (no batching benefit)."""
        return [self.run(req) for req in requests]


class AsyncConcreteEngine:
    """Async sibling of :class:`ConcreteEngine` for offline async tests/docs.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.experimental.ops import SplitWindow, arun
    >>> from libtmux.experimental.ops._types import WindowId
    >>> async def main():
    ...     return await arun(SplitWindow(target=WindowId("@1")), AsyncConcreteEngine())
    >>> asyncio.run(main()).new_pane_id
    '%1'
    """

    def __init__(self, *, capture_lines: Sequence[str] = ()) -> None:
        self.capture_lines = tuple(capture_lines)
        self._counters = _new_counters()

    async def run(self, request: CommandRequest) -> CommandResult:
        """Execute one request against the in-memory simulation."""
        return _simulate(request.args, self._counters, self.capture_lines)

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Execute each request in order (no batching benefit)."""
        return [await self.run(req) for req in requests]
