"""Tests for libtmux Client object."""

from __future__ import annotations

import typing as t

from libtmux.client import Client

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_server_clients_returns_querylist(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """``Server.clients`` lists every attached tmux client as a :class:`Client`."""
    with control_mode():
        clients = server.clients
        assert len(clients) >= 1
        for client in clients:
            assert isinstance(client, Client)
            assert client.client_name is not None


def test_client_session_reports_attached_session(
    control_mode: t.Callable[..., t.Any],
    server: Server,
    session: Session,
) -> None:
    """``client.client_session`` reports the session this client is attached to."""
    with control_mode() as ctl:
        client = server.clients.get(client_name=ctl.client_name)
        assert client is not None
        assert client.client_session == session.session_name


def test_client_readonly_default_zero(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """A non-readonly attached client reports ``client_readonly == "0"``."""
    with control_mode() as ctl:
        client = server.clients.get(client_name=ctl.client_name)
        assert client is not None
        assert client.client_readonly == "0"


def test_client_refresh_rehydrates_fields(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """``Client.refresh()`` repopulates fields from tmux's live state."""
    with control_mode() as ctl:
        client = Client.from_client_name(server=server, client_name=ctl.client_name)
        assert client.client_name == ctl.client_name

        # Stash and clear a field, then refresh: it must come back.
        original_pid = client.client_pid
        client.client_pid = None
        client.refresh()
        assert client.client_pid == original_pid


def test_clients_property_hydrates_cross_scope(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """``Server.clients`` hydrates the client's active session/window/pane.

    Exercises the ``list-clients`` path. tmux's ``format_defaults``
    cascades via ``c->session`` → ``s->curw`` → ``wl->window->active``,
    so a Client object must surface ``session_id``, ``window_id``, and
    ``pane_id``, AND those values must match the client's attached
    session's current window's active pane — not arbitrary values.
    """
    with control_mode() as ctl:
        client = server.clients.get(client_name=ctl.client_name)
        assert client is not None
        assert client.session_id is not None
        assert client.window_id is not None
        assert client.pane_id is not None

        attached_session = server.sessions.get(session_id=client.session_id)
        assert attached_session is not None
        active_pane = attached_session.active_window.active_pane
        assert active_pane is not None
        assert client.window_id == attached_session.active_window.window_id
        assert client.pane_id == active_pane.pane_id
