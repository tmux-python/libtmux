"""Integration tests for ``Server.subscribe`` against a live tmux server.

The control-mode engine routes ``%subscription-changed`` notifications
to per-subscription bounded queues. These tests exercise the whole
chain: ``refresh-client -B`` issuance, server-side change detection,
reader-thread routing, drop-oldest behaviour, and idempotent
unsubscribe.
"""

from __future__ import annotations

import queue as queue_mod
import typing as t
import uuid

import pytest

from libtmux import exc, pytest_plugin
from libtmux.engines.control_mode.base import ControlModeEngine
from libtmux.engines.control_mode.subscription import Subscription
from libtmux.server import Server

if t.TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def control_server() -> Iterator[Server]:
    """Yield a Server backed by the control-mode engine, attached to a known session.

    ``tmux -C`` auto-creates a default session on connect (named ``0``
    by default — see ``server-client.c:3724``). We rename it to a
    test-specific value here so subscription assertions are stable
    regardless of how many sessions exist on the server.
    """
    socket_name = f"libtmux_test_cm_sub_{uuid.uuid4().hex[:8]}"
    server = Server(socket_name=socket_name, engine="control_mode")
    session_name = "subtest"
    try:
        # First cmd triggers engine spawn, which auto-attaches us to
        # session "0". Rename it so tests can assert against a known name.
        server.cmd("rename-session", "-t", "0", session_name)
        yield server
    finally:
        if isinstance(server.engine, ControlModeEngine):
            server.engine.close()
        pytest_plugin._reap_test_server(socket_name)


def _wait_for_value(
    sub: Subscription,
    *,
    timeout: float = 2.0,
) -> str:
    """Drain values until one arrives or *timeout* elapses."""
    return sub.queue.get(timeout=timeout)


# ---------------------------------------------------- input validation --


def test_subscribe_rejects_name_with_colon() -> None:
    """Tmux's ``-B name:target:fmt`` parser breaks on colons in name."""
    with pytest.raises(ValueError, match="cannot contain"):
        Subscription(
            name="bad:name",
            fmt="#{pane_id}",
            target=None,
            queue=queue_mod.Queue(),
        )


def test_server_subscribe_requires_control_mode_engine() -> None:
    """``Server.subscribe`` rejects subprocess and imsg engines explicitly."""
    server = Server(socket_name="libtmux_test_unused", engine="subprocess")
    with pytest.raises(exc.LibTmuxException, match="requires the control_mode"):
        server.subscribe("name", "#{session_name}")


# ----------------------------------------------------------- routing --


def test_subscribe_receives_initial_value(control_server: Server) -> None:
    """Subscribing emits the current format value immediately."""
    sub = control_server.subscribe("session-name", "#{session_name}")
    try:
        value = _wait_for_value(sub)
        assert value == "subtest"
    finally:
        sub.unsubscribe()


def test_subscribe_value_changes_drive_queue(control_server: Server) -> None:
    """Renaming the session pushes the new value onto the queue."""
    sub = control_server.subscribe("session-name", "#{session_name}")
    try:
        first = _wait_for_value(sub)
        assert first == "subtest"

        control_server.cmd("rename-session", "-t", "subtest", "renamed")
        new_value = _wait_for_value(sub)
        assert new_value == "renamed"
    finally:
        sub.unsubscribe()


def test_subscribe_multiplexes_distinct_names(control_server: Server) -> None:
    """Two subscriptions on the same engine route their own values independently."""
    sub_a = control_server.subscribe("session-name", "#{session_name}")
    sub_b = control_server.subscribe("session-id", "#{session_id}")
    try:
        assert _wait_for_value(sub_a) == "subtest"
        b_value = _wait_for_value(sub_b)
        assert b_value.startswith("$")
    finally:
        sub_a.unsubscribe()
        sub_b.unsubscribe()


def test_unsubscribe_stops_future_values(control_server: Server) -> None:
    """After ``unsubscribe`` the queue stops receiving updates."""
    sub = control_server.subscribe("session-name", "#{session_name}")
    _wait_for_value(sub)  # initial value
    sub.unsubscribe()

    # Drain anything queued during the unsubscribe round-trip, then
    # provoke a change and confirm nothing arrives.
    _drain_queue(sub.queue)

    control_server.cmd("rename-session", "-t", "subtest", "renamed")
    with pytest.raises(queue_mod.Empty):
        sub.queue.get(timeout=0.5)


def test_unsubscribe_is_idempotent(control_server: Server) -> None:
    """Calling unsubscribe twice does not raise or send a second wire command."""
    sub = control_server.subscribe("session-name", "#{session_name}")
    sub.unsubscribe()
    sub.unsubscribe()
    sub.unsubscribe()
    assert sub.closed is True


def test_subscribe_drop_oldest_logic_on_full_queue() -> None:
    """``_deliver`` keeps the newest value when the bounded queue is full.

    Tested via direct ``_deliver`` calls — the wire-level "rapid
    rename" path is too tmux-side timing dependent to assert against
    deterministically; what matters for engine correctness is that
    the routing helper itself never blocks and always retains the
    latest value under pressure.
    """
    sub = Subscription(
        name="bench",
        fmt="#{pane_id}",
        target=None,
        queue=queue_mod.Queue(maxsize=2),
    )
    sub._deliver("v0")
    sub._deliver("v1")
    sub._deliver("v2")
    sub._deliver("v3")

    drained = _drain_queue(sub.queue)
    assert drained == ["v2", "v3"]


def _drain_queue(q: queue_mod.Queue[str]) -> list[str]:
    """Drain *q* synchronously without raising on emptiness."""
    out: list[str] = []
    try:
        while True:
            out.append(q.get_nowait())
    except queue_mod.Empty:
        return out
