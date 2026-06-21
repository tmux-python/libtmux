"""Tests for control-mode block correlation (folded chains, merge)."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.engines.control_mode import (
    ControlModeBlock,
    _merge_blocks,
    command_count,
)

if t.TYPE_CHECKING:
    from libtmux.session import Session


class CountCase(t.NamedTuple):
    """An argv and the number of tmux commands it runs."""

    test_id: str
    argv: tuple[str, ...]
    expected: int


COUNT_CASES = (
    CountCase("single", ("rename-window", "-t", "@1", "a"), 1),
    CountCase("two", ("rename-window", "a", ";", "kill-window", "@2"), 2),
    CountCase("three", ("a", ";", "b", ";", "c"), 3),
    CountCase("literal_semicolon_arg", ("send-keys", "-t", "%1", "a;b"), 1),
)


@pytest.mark.parametrize(
    list(CountCase._fields),
    COUNT_CASES,
    ids=[c.test_id for c in COUNT_CASES],
)
def test_command_count(test_id: str, argv: tuple[str, ...], expected: int) -> None:
    """Only a standalone ``;`` token counts as a command separator."""
    assert command_count(argv) == expected


def _block(*, is_error: bool, body: tuple[bytes, ...]) -> ControlModeBlock:
    return ControlModeBlock(number=1, flags=1, is_error=is_error, body=body)


class MergeCase(t.NamedTuple):
    """Blocks from one (possibly folded) request and the merged result."""

    test_id: str
    blocks: list[ControlModeBlock]
    returncode: int
    stdout: tuple[str, ...]
    stderr: tuple[str, ...]


MERGE_CASES = (
    MergeCase("single_ok", [_block(is_error=False, body=(b"%1",))], 0, ("%1",), ()),
    MergeCase("single_err", [_block(is_error=True, body=(b"boom",))], 1, (), ("boom",)),
    MergeCase(
        "chain_all_ok",
        [_block(is_error=False, body=(b"a",)), _block(is_error=False, body=(b"b",))],
        0,
        ("a", "b"),
        (),
    ),
    MergeCase(
        "chain_second_fails",
        [_block(is_error=False, body=(b"a",)), _block(is_error=True, body=(b"boom",))],
        1,
        ("a",),
        ("boom",),
    ),
)


@pytest.mark.parametrize(
    list(MergeCase._fields),
    MERGE_CASES,
    ids=[c.test_id for c in MERGE_CASES],
)
def test_merge_blocks(
    test_id: str,
    blocks: list[ControlModeBlock],
    returncode: int,
    stdout: tuple[str, ...],
    stderr: tuple[str, ...],
) -> None:
    """A folded request's blocks merge; any sub-command error fails the result."""
    result = _merge_blocks(blocks, ("cmd",))
    assert result.returncode == returncode
    assert result.stdout == stdout
    assert result.stderr == stderr


def test_async_control_write_failure_clears_pending() -> None:
    """A write failure removes the queued futures so the FIFO stays aligned."""
    import asyncio

    from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine
    from libtmux.experimental.engines.base import CommandRequest
    from libtmux.experimental.engines.control_mode import ControlModeError

    class _FakeStdin:
        def write(self, _data: bytes) -> None:
            raise BrokenPipeError

        async def drain(self) -> None: ...

    class _FakeProc:
        stdin = _FakeStdin()

    async def _check() -> None:
        engine = AsyncControlModeEngine()
        engine._started = True
        engine._proc = t.cast("t.Any", _FakeProc())
        with pytest.raises(ControlModeError):
            await engine.run_batch([CommandRequest.from_args("list-sessions")])
        assert not engine._pending

    asyncio.run(_check())


def test_control_mode_fold_detects_failure_live(session: Session) -> None:
    """A folded chain over control mode surfaces a later sub-command's failure."""
    from libtmux.experimental.engines.control_mode import ControlModeEngine
    from libtmux.experimental.ops import FoldingPlanner, LazyPlan, RenameWindow
    from libtmux.experimental.ops._types import WindowId

    window = session.active_window
    assert window.window_id is not None
    with ControlModeEngine.for_server(session.server) as engine:
        plan = LazyPlan()
        plan.add(RenameWindow(target=WindowId(window.window_id), name="ok"))
        plan.add(RenameWindow(target=WindowId("@999999"), name="x"))  # bad target
        outcome = plan.execute(engine, planner=FoldingPlanner())
    # The second sub-command's failure is no longer swallowed (was reported ok).
    assert not outcome.ok


def test_control_mode_fold_runs_all_live(session: Session) -> None:
    """A folded chain over control mode runs every sub-command."""
    from libtmux.experimental.engines.control_mode import ControlModeEngine
    from libtmux.experimental.ops import FoldingPlanner, LazyPlan, RenameWindow
    from libtmux.experimental.ops._types import WindowId

    second = session.new_window(window_name="orig")
    first = session.active_window
    assert first.window_id is not None and second.window_id is not None
    with ControlModeEngine.for_server(session.server) as engine:
        plan = LazyPlan()
        plan.add(RenameWindow(target=WindowId(first.window_id), name="one"))
        plan.add(RenameWindow(target=WindowId(second.window_id), name="two"))
        outcome = plan.execute(engine, planner=FoldingPlanner())
    assert outcome.ok
    second.refresh()
    assert second.window_name == "two"
