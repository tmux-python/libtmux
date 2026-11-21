"""Queue-atomic tmux server generation fencing."""

from __future__ import annotations

import secrets
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DaemonGuard:
    """Expected tmux server identity for queue-atomic generation fencing.

    Attributes
    ----------
    pid : int
        Expected ``#{pid}`` of the target tmux server.
    start_time : int
        Expected ``#{start_time}`` epoch seconds of the target tmux server.

    Examples
    --------
    >>> from libtmux._internal.daemon_guard import DaemonGuard
    >>> DaemonGuard(pid=1234, start_time=1700000000).pid
    1234
    """

    pid: int
    start_time: int


def wrap_daemon_guard(
    commands: tuple[tuple[str, ...], ...],
    guard: DaemonGuard,
) -> tuple[tuple[tuple[str, ...], ...], str]:
    """Prepend a queue-atomic ``if-shell -F`` fence checking ``pid`` and ``start_time``.

    ``cmd_if_shell_exec`` evaluates ``-F`` synchronously on the server command
    queue. When the daemon generation differs, ``if-shell`` inserts the
    nonexistent refusal command, failing the command group before any
    subsequent command in *commands* executes.

    Examples
    --------
    >>> from libtmux._internal.daemon_guard import DaemonGuard, wrap_daemon_guard
    >>> guarded, marker = wrap_daemon_guard((("list-sessions",),), DaemonGuard(42, 99))
    >>> guarded[0][:3]
    ('if-shell', '-F', '#{&&:#{==:#{pid},42},#{==:#{start_time},99}}')
    >>> guarded[1]
    ('list-sessions',)
    >>> marker.startswith("__libtmux_daemon_replaced_")
    True
    """
    if not commands:
        msg = "daemon_guard requires at least one tmux command"
        raise ValueError(msg)
    marker = f"__libtmux_daemon_replaced_{secrets.token_hex(8)}"
    condition = (
        f"#{{&&:#{{==:#{{pid}},{guard.pid}}},"
        f"#{{==:#{{start_time}},{guard.start_time}}}}}"
    )
    fence = ("if-shell", "-F", condition, "", marker)
    return (fence, *commands), marker


def is_daemon_guard_refusal(stderr: bytes | str, marker: str) -> bool:
    """Return ``True`` when *stderr* reports the refusal *marker*."""
    if isinstance(stderr, bytes):
        return marker.encode("ascii") in stderr
    return marker in stderr
