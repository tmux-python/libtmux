"""Multi-dispatch resolution: independent forward handles, sync + async."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

import pytest

from libtmux._experimental.chain import (
    AsyncSessionPlanExecutor,
    ForwardPlan,
    SessionPlanExecutor,
    panes,
)
from libtmux._experimental.chain._resolve import Dispatch, drive
from libtmux._experimental.chain.plan import PaneTarget

if t.TYPE_CHECKING:
    from libtmux.session import Session


@dataclass
class _FakeResult:
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    returncode: int = 0


def _mark(value: str) -> t.Callable[[t.Any], t.Any]:
    return lambda h: h.cmd.raw("set-option", "-p", "@m", value)


def test_drive_core_is_sans_io_and_substitutes_ids() -> None:
    """The core yields Dispatch, captures ids, and substitutes them -- no tmux.

    A hand-rolled driver feeds fake ids back, proving the resolution logic is a
    pure generator independent of any I/O (just like the sync/async drivers).
    """
    plan = ForwardPlan(PaneTarget("%1"))
    left, right = plan.split(horizontal=True), plan.split()
    left.do(_mark("L"))
    right.do(_mark("R"))

    gen = drive(tuple(plan._steps))
    dispatched: list[tuple[str, ...]] = []
    fake_ids = iter(["%7", "%8"])
    request = next(gen)
    try:
        while True:
            assert isinstance(request, Dispatch)
            dispatched.append(request.argv)
            out = [next(fake_ids)] if request.captures is not None else []
            request = gen.send(_FakeResult(stdout=out))
    except StopIteration as stop:
        resolved = stop.value

    assert dispatched == [
        # each creation dispatched alone with id capture (both split the seed %1):
        ("split-window", "-t", "%1", "-h", "-P", "-F", "#{pane_id}"),
        ("split-window", "-t", "%1", "-v", "-P", "-F", "#{pane_id}"),
        # downstream commands fold into one trailing  \;  chain, ids substituted:
        (
            "set-option",
            "-t",
            "%7",
            "-p",
            "@m",
            "L",
            ";",
            "set-option",
            "-t",
            "%8",
            "-p",
            "@m",
            "R",
        ),
    ]
    assert resolved.bindings == {0: "%7", 1: "%8"}


def _mark_of(session: Session, pane_id: str) -> list[str]:
    return session.server.cmd("display-message", "-p", "-t", pane_id, "#{@m}").stdout


def test_multidispatch_two_handles_sync(session: Session) -> None:
    """Live: two independent forward panes, each captured + decorated correctly."""
    window = session.new_window(window_name="resolve_sync")
    seed = window.active_pane
    assert seed is not None
    assert seed.pane_id is not None

    plan = ForwardPlan(PaneTarget(seed.pane_id))
    left, right = plan.split(horizontal=True), plan.split()
    left.do(_mark("LEFT"))
    right.do(_mark("RIGHT"))

    resolved = plan.run_resolving(SessionPlanExecutor(session))

    assert set(resolved.bindings) == {0, 1}
    assert resolved.bindings[0] != resolved.bindings[1]
    window.refresh()
    assert len(window.panes) == 3  # seed + two independent panes
    assert _mark_of(session, resolved.bindings[0]) == ["LEFT"]
    assert _mark_of(session, resolved.bindings[1]) == ["RIGHT"]


@pytest.mark.asyncio
async def test_multidispatch_two_handles_async(session: Session) -> None:
    """Live async: the same resolution core, driven with await."""
    window = session.new_window(window_name="resolve_async")
    seed = window.active_pane
    assert seed is not None
    assert seed.pane_id is not None

    plan = ForwardPlan(PaneTarget(seed.pane_id))
    plan.split(horizontal=True).do(_mark("AL"))
    plan.split().do(_mark("AR"))

    resolved = await plan.run_resolving_async(AsyncSessionPlanExecutor(session))

    window.refresh()
    assert len(window.panes) == 3
    assert _mark_of(session, resolved.bindings[0]) == ["AL"]
    assert _mark_of(session, resolved.bindings[1]) == ["AR"]


def test_multidispatch_from_query_seed(session: Session) -> None:
    """Live: seed the plan from the first row of a query (resolved at run)."""
    window = session.new_window(window_name="resolve_seed")
    assert window.active_pane is not None

    plan = ForwardPlan.from_query(panes().filter(active=True))
    plan.split(horizontal=True).do(_mark("A"))
    plan.split().do(_mark("B"))

    resolved = plan.run_resolving(SessionPlanExecutor(session))

    assert _mark_of(session, resolved.bindings[0]) == ["A"]
    assert _mark_of(session, resolved.bindings[1]) == ["B"]
