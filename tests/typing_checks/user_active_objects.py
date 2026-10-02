"""How adopter code reads the active window and pane under ``mypy --strict``."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from typing import assert_type
else:
    from typing_extensions import assert_type

from libtmux import Pane, Server, Session, Window


def a_live_window_always_has_an_active_pane(window: Window) -> None:
    """Use ``Window.active_pane`` without a ``None`` check."""
    assert_type(window.active_pane, Pane)
    window.active_pane.send_keys("echo ok")


def a_live_session_always_has_an_active_pane(session: Session) -> None:
    """Use ``Session.active_pane`` without a ``None`` check."""
    assert_type(session.active_window, Window)
    assert_type(session.active_pane, Pane)
    session.active_pane.send_keys("echo ok")


def commands_that_select_return_the_pane(window: Window, session: Session) -> None:
    """Chain from the pane a selecting command returns."""
    assert_type(window.select_pane("%1"), Pane)
    assert_type(window.last_pane(), Pane)
    assert_type(session.select_window("1"), Window)


def a_client_may_be_attached_to_nothing(server: Server) -> None:
    """Keep ``None`` where the object really can be absent."""
    for client in server.clients:
        assert_type(client.attached_session, Session | None)
        assert_type(client.attached_window, Window | None)
        assert_type(client.attached_pane, Pane | None)
