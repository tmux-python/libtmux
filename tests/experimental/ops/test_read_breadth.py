"""Tests for the non-list read ops (has-session/display-message/show-options).

These cover the read seam beyond the ``list-*`` family: a typed existence
query, a format evaluation, an option dump, and the client listing. Each op
renders an inert argv and parses tmux output into a typed result without a live
server; live tests then exercise them against real tmux.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.ops import (
    DisplayMessage,
    HasSession,
    ListClients,
    ShowOptions,
    result_from_dict,
    result_to_dict,
)
from libtmux.experimental.ops._types import NameRef, PaneId, SessionId

if t.TYPE_CHECKING:
    from libtmux.experimental.ops.operation import Operation
    from libtmux.session import Session


class RenderCase(t.NamedTuple):
    """An op and the argv fragments its render must contain."""

    test_id: str
    op: Operation[t.Any]
    fragments: tuple[str, ...]


RENDER_CASES = (
    RenderCase(
        test_id="has_session",
        op=HasSession(target=SessionId("$0")),
        fragments=("has-session", "-t", "$0"),
    ),
    RenderCase(
        test_id="display_message",
        op=DisplayMessage(target=PaneId("%1"), message="#{pane_id}"),
        fragments=("display-message", "-t", "%1", "-p", "#{pane_id}"),
    ),
    RenderCase(
        test_id="show_options_global",
        op=ShowOptions(global_=True),
        fragments=("show-options", "-g"),
    ),
    RenderCase(
        test_id="show_options_server_inherited",
        op=ShowOptions(server=True, include_inherited=True),
        fragments=("show-options", "-s", "-A"),
    ),
    RenderCase(
        test_id="list_clients",
        op=ListClients(),
        fragments=("list-clients", "-F"),
    ),
)


@pytest.mark.parametrize(
    list(RenderCase._fields),
    RENDER_CASES,
    ids=[c.test_id for c in RENDER_CASES],
)
def test_read_op_render(
    test_id: str,
    op: Operation[t.Any],
    fragments: tuple[str, ...],
) -> None:
    """Each read op renders the expected argv fragments."""
    argv = op.render(version="3.2a")
    for fragment in fragments:
        assert fragment in argv


class ParseCase(t.NamedTuple):
    """An op plus a synthesized tmux outcome and the result fields it yields."""

    test_id: str
    op: Operation[t.Any]
    returncode: int
    stdout: tuple[str, ...]
    expected: dict[str, t.Any]


PARSE_CASES = (
    ParseCase(
        test_id="has_session_exists",
        op=HasSession(target=SessionId("$0")),
        returncode=0,
        stdout=(),
        expected={"exists": True, "status": "complete"},
    ),
    ParseCase(
        test_id="has_session_missing",
        op=HasSession(target=SessionId("$9")),
        returncode=1,
        stdout=(),
        expected={"exists": False, "status": "complete"},
    ),
    ParseCase(
        test_id="display_message_text",
        op=DisplayMessage(message="#{pane_id}"),
        returncode=0,
        stdout=("%1",),
        expected={"text": "%1"},
    ),
    ParseCase(
        test_id="display_message_empty",
        op=DisplayMessage(message="#{pane_id}"),
        returncode=0,
        stdout=(),
        expected={"text": ""},
    ),
    ParseCase(
        test_id="show_options_pairs",
        op=ShowOptions(),
        returncode=0,
        stdout=("status on", "history-limit 2000"),
        expected={"options": {"status": "on", "history-limit": "2000"}},
    ),
)


@pytest.mark.parametrize(
    list(ParseCase._fields),
    PARSE_CASES,
    ids=[c.test_id for c in PARSE_CASES],
)
def test_read_op_parse(
    test_id: str,
    op: Operation[t.Any],
    returncode: int,
    stdout: tuple[str, ...],
    expected: dict[str, t.Any],
) -> None:
    """Each read op parses its tmux output into the expected result fields."""
    result = op.build_result(returncode=returncode, stdout=stdout)
    for attr, value in expected.items():
        assert getattr(result, attr) == value


@pytest.mark.parametrize(
    list(ParseCase._fields),
    PARSE_CASES,
    ids=[c.test_id for c in PARSE_CASES],
)
def test_read_result_round_trip(
    test_id: str,
    op: Operation[t.Any],
    returncode: int,
    stdout: tuple[str, ...],
    expected: dict[str, t.Any],
) -> None:
    """Every read result round-trips through its JSON-friendly dict form."""
    result = op.build_result(returncode=returncode, stdout=stdout)
    assert result_from_dict(result_to_dict(result)) == result


def test_has_session_live(session: Session) -> None:
    """has-session answers True for the fixture session, False for a fake one."""
    from libtmux.experimental.engines import SubprocessEngine
    from libtmux.experimental.ops import run

    engine = SubprocessEngine.for_server(session.server)
    assert session.session_id is not None

    present = run(HasSession(target=SessionId(session.session_id)), engine)
    assert present.status == "complete"
    assert present.exists is True

    absent = run(HasSession(target=NameRef("no-such-session-xyz")), engine)
    assert absent.status == "complete"
    assert absent.exists is False


def test_display_message_live(session: Session) -> None:
    """display-message -p evaluates a format against a real pane."""
    from libtmux.experimental.engines import SubprocessEngine
    from libtmux.experimental.ops import run

    engine = SubprocessEngine.for_server(session.server)
    pane = session.active_pane
    assert pane is not None and pane.pane_id is not None

    result = run(
        DisplayMessage(target=PaneId(pane.pane_id), message="#{session_id}"),
        engine,
    )
    assert result.ok
    assert result.text == session.session_id


def test_show_options_live(session: Session) -> None:
    """show-options -g returns a non-empty option mapping."""
    from libtmux.experimental.engines import SubprocessEngine
    from libtmux.experimental.ops import run

    engine = SubprocessEngine.for_server(session.server)
    result = run(ShowOptions(global_=True), engine)
    assert result.ok
    assert result.options  # global options are always present


def test_list_clients_live(session: Session) -> None:
    """list-clients returns typed client snapshots (possibly none)."""
    from libtmux.experimental.engines import SubprocessEngine
    from libtmux.experimental.ops import run

    engine = SubprocessEngine.for_server(session.server)
    result = run(ListClients(), engine)
    assert result.ok
    assert all(c.name for c in result.clients)
