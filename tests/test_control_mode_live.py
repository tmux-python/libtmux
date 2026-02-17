"""Live control-mode functional tests (no fakes)."""

from __future__ import annotations

import typing as t
from typing import NamedTuple

import pytest

from libtmux._internal.engines.control_mode import ControlModeEngine
from libtmux.server import Server
from tests.helpers import wait_for_line


class ClientFlagCase(NamedTuple):
    """Fixture for exercising set_client_flags against real tmux."""

    test_id: str
    kwargs: dict[str, t.Any]
    present: set[str]
    absent: frozenset[str] = frozenset()


CLIENT_FLAG_CASES: list[ClientFlagCase] = [
    ClientFlagCase(
        test_id="enable_no_output_pause",
        kwargs={"no_output": True, "pause_after": 1},
        present={"no-output", "pause-after=1"},
    ),
    ClientFlagCase(
        test_id="clear_no_output_pause",
        kwargs={"no_output": False, "pause_after": 0, "wait_exit": False},
        present=set(),
        absent=frozenset({"no-output", "pause-after", "pause-after=1", "wait-exit"}),
    ),
    ClientFlagCase(
        test_id="enable_wait_exit",
        kwargs={"wait_exit": True},
        present={"wait-exit"},
    ),
    ClientFlagCase(
        test_id="enable_active_pane",
        kwargs={"active_pane": True},
        present={"active-pane"},
    ),
]
CLIENT_FLAG_IDS = [case.test_id for case in CLIENT_FLAG_CASES]


@pytest.mark.engines(["control"])
@pytest.mark.parametrize("case", CLIENT_FLAG_CASES, ids=CLIENT_FLAG_IDS)
def test_set_client_flags_live(
    case: ClientFlagCase,
    control_sandbox: t.ContextManager[Server],
) -> None:
    """set_client_flags should actually toggle tmux client flags."""
    with control_sandbox as server:
        engine = t.cast(ControlModeEngine, server.engine)
        engine.set_client_flags(**case.kwargs)

        flags_line = server.cmd("list-clients", "-F", "#{client_flags}").stdout
        assert flags_line
        flags = set(flags_line[0].split(","))

        for flag in case.present:
            assert flag in flags
        for flag in case.absent:
            assert flag not in flags


class PaneFlowLiveCase(NamedTuple):
    """Fixture for exercising set_pane_flow against real tmux."""

    test_id: str
    state: str


PANE_FLOW_CASES = [
    PaneFlowLiveCase(test_id="pause", state="pause"),
    PaneFlowLiveCase(test_id="continue", state="continue"),
]
PANE_FLOW_IDS = [case.test_id for case in PANE_FLOW_CASES]


@pytest.mark.engines(["control"])
@pytest.mark.parametrize("case", PANE_FLOW_CASES, ids=PANE_FLOW_IDS)
def test_set_pane_flow_live(
    case: PaneFlowLiveCase,
    control_sandbox: t.ContextManager[Server],
) -> None:
    """set_pane_flow should succeed and leave the client usable."""
    with control_sandbox as server:
        session = server.new_session(
            session_name="flow_case",
            attach=True,
            kill_session=True,
        )
        pane = session.active_pane
        assert pane is not None
        pane_id = t.cast(str, pane.pane_id)

        engine = t.cast(ControlModeEngine, server.engine)
        engine.set_pane_flow(pane_id, state=case.state)

        pane.send_keys('printf "flow-test"\\n', literal=True, suppress_history=False)
        lines = wait_for_line(pane, lambda line: "flow-test" in line)
        assert any("flow-test" in line for line in lines)


class SubscribeLiveCase(NamedTuple):
    """Fixture for exercising subscribe/unsubscribe against real tmux."""

    test_id: str
    what_fmt: tuple[str, str]


SUBSCRIBE_CASES = [
    SubscribeLiveCase(
        test_id="active_pane_subscription",
        what_fmt=("%1", "#{pane_active}"),
    ),
]
SUBSCRIBE_IDS = [case.test_id for case in SUBSCRIBE_CASES]


@pytest.mark.engines(["control"])
@pytest.mark.parametrize("case", SUBSCRIBE_CASES, ids=SUBSCRIBE_IDS)
def test_subscribe_roundtrip_live(
    case: SubscribeLiveCase,
    control_sandbox: t.ContextManager[Server],
) -> None:
    """subscribe/unsubscribe should succeed without breaking control client."""
    with control_sandbox as server:
        engine = t.cast(ControlModeEngine, server.engine)
        session = server.new_session(
            session_name="sub_case",
            attach=True,
            kill_session=True,
        )
        pane = session.active_pane
        assert pane is not None

        target = case.what_fmt[0] if case.what_fmt[0] != "%1" else pane.pane_id
        engine.subscribe("focus_test", what=target, fmt=case.what_fmt[1])
        assert server.cmd("display-message", "-p", "ok").stdout == ["ok"]

        engine.subscribe("focus_test", fmt=None)
        assert server.cmd("display-message", "-p", "ok").stdout == ["ok"]
