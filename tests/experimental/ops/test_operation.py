"""Tests for the base :class:`~libtmux.experimental.ops.operation.Operation`."""

from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass

import pytest

from libtmux.experimental.engines.base import (
    CommandSeparator,
    is_command_separator,
)
from libtmux.experimental.ops import (
    BreakPane,
    CapturePane,
    NewPane,
    NewWindow,
    SelectLayout,
    SendKeys,
    SetBuffer,
    SplitWindow,
)
from libtmux.experimental.ops._types import Effects, PaneId, SessionId, WindowId
from libtmux.experimental.ops.exc import VersionUnsupported
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.results import Result


@dataclass(frozen=True, kw_only=True)
class _FutureOp(Operation[Result]):
    """A synthetic operation gated to a future tmux version, for tests."""

    kind = "_future_op_test"
    command = "future-cmd"
    scope = "server"
    result_cls = Result
    effects = Effects()
    min_version = "99.0"
    flag_version_map: t.ClassVar[dict[str, str]] = {"feat": "99.0"}


def test_render_includes_target_then_args() -> None:
    """``render`` emits ``command -t target *args`` in order."""
    op = SendKeys(target=PaneId("%1"), keys="echo hi", enter=True)
    assert op.render() == ("send-keys", "-t", "%1", "--", "echo hi", "Enter")


def test_render_without_target() -> None:
    """An operation with no target omits ``-t``."""
    op = SelectLayout(layout="tiled")
    assert op.render() == ("select-layout", "--", "tiled")


@pytest.mark.parametrize(
    "operation",
    (
        pytest.param(
            SetBuffer(buffer_name=CommandSeparator(";"), data="kill-server"),
            id="flag_value",
        ),
        pytest.param(
            SetBuffer(data=CommandSeparator(";")),
            id="positional_value",
        ),
    ),
)
def test_render_normalizes_user_string_subclasses(
    operation: Operation[t.Any],
) -> None:
    """Only the planner can introduce typed structural separators."""
    argv = operation.render()

    assert all(type(token) is str for token in argv)
    assert not any(is_command_separator(token) for token in argv)


def test_version_gate_drops_unsupported_flag() -> None:
    """A version-gated flag is dropped on an older tmux and kept on a newer one."""
    op = CapturePane(target=PaneId("%1"), trim_trailing=True)
    assert op.render(version="3.3") == ("capture-pane", "-t", "%1", "-p")
    assert op.render(version="3.4") == ("capture-pane", "-t", "%1", "-p", "-T")
    assert op.render() == ("capture-pane", "-t", "%1", "-p", "-T")


def test_check_version_raises_when_too_low() -> None:
    """An operation older tmux cannot satisfy raises on render."""
    op = _FutureOp()
    with pytest.raises(VersionUnsupported, match="requires tmux >= 99"):
        op.render(version="3.4")


def test_check_version_passes_when_satisfied() -> None:
    """No version (or a satisfying one) renders without error."""
    op = _FutureOp()
    assert op.render() == ("future-cmd",)
    assert op.render(version="99.0") == ("future-cmd",)


class VersionCase(t.NamedTuple):
    """A tmux version string and whether the 99.0-gated op accepts it."""

    test_id: str
    version: str | None
    satisfied: bool


VERSION_CASES = (
    VersionCase("master_suffix", "3.7-master", True),
    VersionCase("bare_master", "master", True),
    VersionCase("none", None, True),
    VersionCase("exact", "99.0", True),
    VersionCase("too_old", "3.4", False),
)


@pytest.mark.parametrize(
    list(VersionCase._fields),
    VERSION_CASES,
    ids=[c.test_id for c in VERSION_CASES],
)
def test_version_gates_normalize_master(
    test_id: str,
    version: str | None,
    satisfied: bool,
) -> None:
    """A "master"/suffixed version sorts above tagged releases for both gates."""
    op = _FutureOp()
    if satisfied:
        op.check_version(version)  # no raise
        assert op.flag_available("feat", version) is True
    else:
        with pytest.raises(VersionUnsupported):
            op.check_version(version)
        assert op.flag_available("feat", version) is False


def test_build_result_parses_payload() -> None:
    """``split-window`` parses the captured new-pane id into its result."""
    op = SplitWindow(target=WindowId("@1"))
    result = op.build_result(returncode=0, stdout=("%7",))
    assert result.new_pane_id == "%7"
    assert result.ok
    assert result.operation is op


@pytest.mark.parametrize(
    "op",
    (
        pytest.param(BreakPane(src_target=PaneId("%1")), id="break_pane"),
        pytest.param(SplitWindow(target=WindowId("@1")), id="split_window"),
        pytest.param(NewPane(target=PaneId("%1")), id="new_pane"),
    ),
)
@pytest.mark.parametrize(
    "stdout",
    (
        pytest.param((), id="absent_stdout"),
        pytest.param(("",), id="empty_line"),
        pytest.param((" \t ",), id="whitespace_line"),
    ),
)
def test_create_blank_or_absent_capture_is_missing(
    op: Operation[t.Any],
    stdout: tuple[str, ...],
) -> None:
    """An absent or blank captured object id normalizes to the missing sentinel."""
    result = op.build_result(returncode=0, stdout=stdout)

    assert result.created_id is None


def test_build_result_failure_status() -> None:
    """A nonzero return code yields a ``failed`` result and no payload."""
    op = SplitWindow(target=WindowId("@1"))
    result = op.build_result(returncode=1, stderr=("no space for new pane",))
    assert result.status == "failed"
    assert result.new_pane_id is None


def test_break_pane_catalog_marks_version_composition() -> None:
    """The static operation shape discloses its tmux 3.7 rename follow-up."""
    from libtmux.experimental.ops import catalog

    entry = next(item for item in catalog() if item.kind == "break_pane")

    assert not BreakPane.primitive
    assert not entry.primitive


def test_capture_invariant_logging_keeps_heavy_fields_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warning and error records keep output payloads out of their schema."""
    operation = NewWindow(target=SessionId("$1"), capture_pane=True)
    stdout = ("@2",)
    logger_name = "libtmux.experimental.ops.operation"
    with caplog.at_level(logging.DEBUG, logger=logger_name):
        operation.build_result(returncode=0, stdout=stdout)

    primary = t.cast(
        "t.Any",
        next(record for record in caplog.records if record.levelno == logging.ERROR),
    )
    assert primary.tmux_subcommand == operation.command
    assert primary.tmux_stdout_len == len(stdout)
    assert primary.tmux_stderr_len == 0
    assert not hasattr(primary, "tmux_stdout")
    assert not hasattr(primary, "tmux_stderr")
    assert operation.target is not None
    assert primary.tmux_target == operation.target.render()

    details = t.cast(
        "t.Any",
        next(record for record in caplog.records if record.levelno == logging.DEBUG),
    )
    assert details.tmux_stdout == list(stdout)
    assert details.tmux_stderr == []


def test_failed_create_result_does_not_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A returned tmux rejection remains data rather than emitting log noise."""
    operation = NewWindow(target=SessionId("$1"))

    with caplog.at_level(
        logging.DEBUG,
        logger="libtmux.experimental.ops.operation",
    ):
        result = operation.build_result(returncode=1, stderr=("duplicate",))

    assert result.failed
    assert caplog.records == []


def test_operations_are_frozen() -> None:
    """Operations are immutable values."""
    op = SendKeys(target=PaneId("%1"), keys="x")
    with pytest.raises((AttributeError, TypeError)):
        op.keys = "y"  # type: ignore[misc]


@pytest.mark.parametrize(
    "op",
    [
        pytest.param(SplitWindow(target=WindowId("@1")), id="split_window"),
        pytest.param(CapturePane(target=PaneId("%1")), id="capture_pane"),
        pytest.param(SendKeys(target=PaneId("%1"), keys="x"), id="send_keys"),
        pytest.param(SelectLayout(target=WindowId("@1")), id="select_layout"),
    ],
)
def test_render_is_nonempty_argv(op: Operation[t.Any]) -> None:
    """Every seed operation renders to a non-empty argv starting with command."""
    argv = op.render()
    assert argv
    assert argv[0] == op.command
