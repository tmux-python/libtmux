"""Unit tests for engine protocol and wrappers."""

from __future__ import annotations

from libtmux._internal.engines.base import (
    CommandResult,
    ExitStatus,
    NotificationKind,
    command_result_to_tmux_cmd,
)
from libtmux._internal.engines.control_protocol import CommandContext, ControlProtocol


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
