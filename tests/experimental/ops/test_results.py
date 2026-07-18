"""Tests for results and the opt-in failure model."""

from __future__ import annotations

import pytest

from libtmux.experimental.ops import SendKeys
from libtmux.experimental.ops._types import PaneId
from libtmux.experimental.ops.exc import TmuxCommandError
from libtmux.experimental.ops.results import Result, status_for


@pytest.mark.parametrize(
    ("returncode", "stderr", "expected"),
    [
        pytest.param(0, [], "complete", id="clean"),
        pytest.param(1, [], "failed", id="nonzero"),
        pytest.param(0, ["no current session"], "failed", id="stderr-on-zero"),
    ],
)
def test_status_for(returncode: int, stderr: list[str], expected: str) -> None:
    """Tmux signalling failure via stderr counts as failed even on exit 0."""
    assert status_for(returncode, stderr) == expected


def _result(returncode: int, stderr: tuple[str, ...] = ()) -> Result:
    """Build a send-keys result for the given outcome."""
    return SendKeys(target=PaneId("%1"), keys="x").build_result(
        returncode=returncode,
        stderr=stderr,
    )


def test_ok_result_does_not_raise() -> None:
    """``raise_for_status`` returns the result itself when OK (fluent)."""
    result = _result(0)
    assert result.ok
    assert result.raise_for_status() is result


def test_failed_result_raises_typed_error() -> None:
    """A failed result raises :class:`TmuxCommandError` only when asked."""
    result = _result(1, ("can't find pane",))
    assert result.failed
    with pytest.raises(TmuxCommandError) as excinfo:
        result.raise_for_status()
    assert excinfo.value.returncode == 1
    assert excinfo.value.stderr == ("can't find pane",)


def test_unknown_status_raises() -> None:
    """An ``unknown`` (e.g. timeout) result also raises on demand."""
    base = _result(0)
    unknown = Result(
        operation=base.operation,
        argv=base.argv,
        status="unknown",
        returncode=-1,
    )
    with pytest.raises(TmuxCommandError):
        unknown.raise_for_status()


def test_skipped_status_does_not_raise() -> None:
    """A ``skipped`` operation is not a failure."""
    base = _result(0)
    skipped = Result(
        operation=base.operation,
        argv=base.argv,
        status="skipped",
        returncode=0,
    )
    assert skipped.raise_for_status() is skipped
