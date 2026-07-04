"""Tests for the fluent forward-ref plan builder (``plan()``)."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.engines.concrete import ConcreteEngine
from libtmux.experimental.fluent import PlanBuilder, plan
from libtmux.experimental.query import ForwardPaneRef

if t.TYPE_CHECKING:
    from libtmux.session import Session


def _one_window_two_panes(p: PlanBuilder) -> None:
    pane = p.new_session("dev").window().pane()
    pane.do(lambda c: c.send_keys("vim")).split().do(
        lambda c: c.send_keys("pytest -q"),
    )


def _two_windows(p: PlanBuilder) -> None:
    sess = p.new_session("dev")
    sess.window().pane().do(lambda c: c.send_keys("vim"))
    sess.new_window("logs").pane().do(lambda c: c.send_keys("tail -f log"))


class _BuildCase(t.NamedTuple):
    """A fluent build and the operation sequence it should record."""

    test_id: str
    build: t.Callable[[PlanBuilder], None]
    kinds: list[str]


_BUILD_CASES: tuple[_BuildCase, ...] = (
    _BuildCase(
        "one_window_two_panes",
        _one_window_two_panes,
        ["new_session", "send_keys", "split_window", "send_keys"],
    ),
    _BuildCase(
        "two_windows",
        _two_windows,
        ["new_session", "send_keys", "new_window", "send_keys"],
    ),
)


@pytest.mark.parametrize("case", _BUILD_CASES, ids=[c.test_id for c in _BUILD_CASES])
def test_builder_records_ops(case: _BuildCase) -> None:
    """The fluent build records the expected operation sequence."""
    p = plan()
    case.build(p)
    assert [op.kind for op in p.plan.operations] == case.kinds


@pytest.mark.parametrize("case", _BUILD_CASES, ids=[c.test_id for c in _BUILD_CASES])
def test_builder_runs_offline(case: _BuildCase) -> None:
    """The build resolves forward refs and folds over the in-memory engine."""
    p = plan()
    case.build(p)
    assert p.run(ConcreteEngine()).ok


def test_window_pane_is_forward_handle() -> None:
    """A window's first pane is a forward handle with no snapshot reads."""
    ref = plan().new_session("dev").window().pane()
    assert isinstance(ref, ForwardPaneRef)
    assert not hasattr(ref, "pane_id")


def test_build_session_live(session: Session) -> None:
    """A fluent build creates a real session with the declared panes."""
    from libtmux.experimental.engines.subprocess import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    p = plan()
    pane = p.new_session("fluentdev").window().pane()
    pane.do(lambda c: c.send_keys("echo top", enter=False)).split().do(
        lambda c: c.send_keys("echo bottom", enter=False),
    )
    p.run(engine).raise_for_status()

    built = [s for s in session.server.sessions if s.session_name == "fluentdev"]
    assert len(built) == 1
    assert len(built[0].windows[0].panes) == 2
