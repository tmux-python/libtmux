"""Unit tests for engine protocol and wrappers."""

from __future__ import annotations

import typing as t

import pytest

from libtmux._internal.engines.base import (
    CommandResult,
    ExitStatus,
    NotificationKind,
    command_result_to_tmux_cmd,
)
from libtmux._internal.engines.control_protocol import (
    CommandContext,
    ControlProtocol,
    ParserState,
)


class NotificationFixture(t.NamedTuple):
    """Fixture for notification parsing cases."""

    test_id: str
    line: str
    expected_kind: NotificationKind
    expected_subset: dict[str, str]


class ProtocolErrorFixture(t.NamedTuple):
    """Fixture for protocol error handling."""

    test_id: str
    line: str
    expected_reason: str


def test_command_result_wraps_tmux_cmd() -> None:
    """CommandResult should adapt cleanly into tmux_cmd wrapper."""
    result = CommandResult(
        argv=["tmux", "-V"],
        stdout=["tmux 3.4"],
        stderr=[],
        exit_status=ExitStatus.OK,
        cmd_id=7,
    )

    wrapped = command_result_to_tmux_cmd(result)

    assert wrapped.stdout == ["tmux 3.4"]
    assert wrapped.returncode == 0
    assert getattr(wrapped, "cmd_id", None) == 7


def test_control_protocol_parses_begin_end() -> None:
    """Parser should map %begin/%end into a completed context."""
    proto = ControlProtocol()
    ctx = CommandContext(argv=["tmux", "list-sessions"])
    proto.register_command(ctx)

    proto.feed_line("%begin 1700000000 10 0")
    proto.feed_line("session-one")
    proto.feed_line("%end 1700000001 10 0")

    assert ctx.done.wait(timeout=0.05)

    result = proto.build_result(ctx)
    assert result.stdout == ["session-one"]
    assert result.exit_status is ExitStatus.OK
    assert result.cmd_id == 10


def test_control_protocol_notifications() -> None:
    """Notifications should enqueue and track drop counts when bounded."""
    proto = ControlProtocol(notification_queue_size=1)
    proto.feed_line("%sessions-changed")

    notif = proto.get_notification(timeout=0.05)
    assert notif is not None
    assert notif.kind is NotificationKind.SESSIONS_CHANGED

    # queue is bounded; pushing another should increment drop counter when full
    proto.feed_line("%sessions-changed")
    proto.feed_line("%sessions-changed")
    assert proto.get_stats(restarts=0).dropped_notifications >= 1


PROTOCOL_ERROR_CASES: list[ProtocolErrorFixture] = [
    ProtocolErrorFixture(
        test_id="unexpected_end",
        line="%end 123 1 0",
        expected_reason="unexpected %end",
    ),
    ProtocolErrorFixture(
        test_id="no_pending_begin",
        line="%begin 999 1 0",
        expected_reason="no pending command for %begin",
    ),
]


@pytest.mark.parametrize("case", PROTOCOL_ERROR_CASES, ids=lambda c: c.test_id)
def test_control_protocol_errors(case: ProtocolErrorFixture) -> None:
    """Protocol errors should mark the parser DEAD and record last_error."""
    proto = ControlProtocol()
    proto.feed_line(case.line)
    stats = proto.get_stats(restarts=0)
    assert proto.state is ParserState.DEAD
    assert stats.last_error is not None
    assert case.expected_reason in stats.last_error


NOTIFICATION_FIXTURES: list[NotificationFixture] = [
    NotificationFixture(
        test_id="layout_change",
        line="%layout-change @1 abcd efgh 0",
        expected_kind=NotificationKind.WINDOW_LAYOUT_CHANGED,
        expected_subset={
            "window_id": "@1",
            "window_layout": "abcd",
            "window_visible_layout": "efgh",
            "window_raw_flags": "0",
        },
    ),
    NotificationFixture(
        test_id="unlinked_window_add",
        line="%unlinked-window-add @2",
        expected_kind=NotificationKind.UNLINKED_WINDOW_ADD,
        expected_subset={"window_id": "@2"},
    ),
    NotificationFixture(
        test_id="unlinked_window_close",
        line="%unlinked-window-close @3",
        expected_kind=NotificationKind.UNLINKED_WINDOW_CLOSE,
        expected_subset={"window_id": "@3"},
    ),
    NotificationFixture(
        test_id="unlinked_window_renamed",
        line="%unlinked-window-renamed @4 new-name",
        expected_kind=NotificationKind.UNLINKED_WINDOW_RENAMED,
        expected_subset={"window_id": "@4", "name": "new-name"},
    ),
    NotificationFixture(
        test_id="client_session_changed",
        line="%client-session-changed c1 $5 sname",
        expected_kind=NotificationKind.CLIENT_SESSION_CHANGED,
        expected_subset={
            "client_name": "c1",
            "session_id": "$5",
            "session_name": "sname",
        },
    ),
    NotificationFixture(
        test_id="client_detached",
        line="%client-detached c1",
        expected_kind=NotificationKind.CLIENT_DETACHED,
        expected_subset={"client_name": "c1"},
    ),
    NotificationFixture(
        test_id="session_renamed",
        line="%session-renamed $5 new-name",
        expected_kind=NotificationKind.SESSION_RENAMED,
        expected_subset={"session_id": "$5", "session_name": "new-name"},
    ),
    NotificationFixture(
        test_id="paste_buffer_changed",
        line="%paste-buffer-changed buf1",
        expected_kind=NotificationKind.PASTE_BUFFER_CHANGED,
        expected_subset={"name": "buf1"},
    ),
    NotificationFixture(
        test_id="paste_buffer_deleted",
        line="%paste-buffer-deleted buf1",
        expected_kind=NotificationKind.PASTE_BUFFER_DELETED,
        expected_subset={"name": "buf1"},
    ),
]


@pytest.mark.parametrize(
    list(NotificationFixture._fields),
    NOTIFICATION_FIXTURES,
    ids=[fixture.test_id for fixture in NOTIFICATION_FIXTURES],
)
def test_control_protocol_notification_parsing(
    test_id: str,
    line: str,
    expected_kind: NotificationKind,
    expected_subset: dict[str, str],
) -> None:
    """Ensure the parser recognizes mapped control-mode notifications."""
    proto = ControlProtocol()
    proto.feed_line(line)
    notif = proto.get_notification(timeout=0.05)
    assert notif is not None
    assert notif.kind is expected_kind
    for key, value in expected_subset.items():
        assert notif.data.get(key) == value
