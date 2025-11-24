"""Diagnostic tests using raw control client logs."""

from __future__ import annotations

import typing as t

import pytest

from libtmux._internal.engines.control_protocol import CommandContext, ControlProtocol
from libtmux.common import has_lt_version


@pytest.mark.engines(["control"])
def test_control_client_lists_clients(
    control_client_logs: tuple[t.Any, ControlProtocol],
) -> None:
    """Raw control client should report itself with control-mode flag."""
    proc, proto = control_client_logs

    assert proc.stdin is not None
    list_ctx = CommandContext(
        argv=[
            "tmux",
            "list-clients",
            "-F",
            "#{client_pid} #{client_flags} #{session_name}",
        ],
    )
    proto.register_command(list_ctx)
    detach_ctx = CommandContext(argv=["tmux", "detach-client"])
    proto.register_command(detach_ctx)
    proc.stdin.write('list-clients -F"#{client_pid} #{client_flags} #{session_name}"\n')
    proc.stdin.write("detach-client\n")
    proc.stdin.flush()

    stdout_data, _ = proc.communicate(timeout=5)
    for line in stdout_data.splitlines():
        proto.feed_line(line.rstrip("\n"))

    assert list_ctx.done.wait(timeout=0.5)
    result = proto.build_result(list_ctx)
    if has_lt_version("3.2"):
        pytest.xfail("tmux < 3.2 omits client_flags field in list-clients")

    saw_control_flag = any(
        len(parts := line.split()) >= 2
        and ("C" in parts[1] or "control-mode" in parts[1])
        for line in result.stdout
    )
    assert saw_control_flag


@pytest.mark.engines(["control"])
def test_control_client_capture_stream_parses(
    control_client_logs: tuple[t.Any, ControlProtocol],
) -> None:
    """Ensure ControlProtocol can parse raw stream from the logged control client."""
    proc, proto = control_client_logs
    assert proc.stdin is not None

    display_ctx = CommandContext(argv=["tmux", "display-message", "-p", "hello"])
    proto.register_command(display_ctx)
    detach_ctx = CommandContext(argv=["tmux", "detach-client"])
    proto.register_command(detach_ctx)
    proc.stdin.write("display-message -p hello\n")
    proc.stdin.write("detach-client\n")
    proc.stdin.flush()

    stdout_data, _ = proc.communicate(timeout=5)

    for line in stdout_data.splitlines():
        proto.feed_line(line.rstrip("\n"))

    assert display_ctx.done.wait(timeout=0.5)
    result = proto.build_result(display_ctx)
    assert "hello" in result.stdout or "hello" in "".join(result.stdout)


def test_control_client_notification_parsing(
    control_client_logs: tuple[t.Any, ControlProtocol],
) -> None:
    """Control client log stream should produce notifications."""
    proc, proto = control_client_logs
    assert proc.stdin is not None

    ctx = CommandContext(argv=["tmux", "display-message", "-p", "ping"])
    proto.register_command(ctx)
    # send a trivial command and rely on session-changed notification from attach
    proc.stdin.write("display-message -p ping\n")
    proc.stdin.write("detach-client\n")
    proc.stdin.flush()

    stdout_data, _ = proc.communicate(timeout=5)
    for line in stdout_data.splitlines():
        proto.feed_line(line.rstrip("\n"))

    notif = proto.get_notification(timeout=0.1)
    assert notif is not None
    assert notif.kind.name in {"SESSION_CHANGED", "CLIENT_SESSION_CHANGED", "RAW"}


@pytest.mark.engines(["control"])
def test_control_client_lists_control_flag(
    control_client_logs: tuple[t.Any, ControlProtocol],
) -> None:
    """list-clients should show control client with C flag on tmux >= 3.2."""
    proc, proto = control_client_logs
    if has_lt_version("3.2"):
        pytest.skip("tmux < 3.2 omits client_flags")

    assert proc.stdin is not None
    list_ctx = CommandContext(
        argv=[
            "tmux",
            "list-clients",
            "-F",
            "#{client_pid} #{client_flags} #{session_name}",
        ],
    )
    proto.register_command(list_ctx)
    proc.stdin.write('list-clients -F"#{client_pid} #{client_flags} #{session_name}"\n')
    proc.stdin.write("detach-client\n")
    proc.stdin.flush()

    stdout_data, _ = proc.communicate(timeout=5)
    for line in stdout_data.splitlines():
        proto.feed_line(line.rstrip("\n"))

    assert list_ctx.done.wait(timeout=0.5)
    result = proto.build_result(list_ctx)
    assert any(
        len(parts := line.split()) >= 2 and "C" in parts[1] for line in result.stdout
    )
