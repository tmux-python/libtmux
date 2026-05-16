"""Tests for libtmux Client object."""

from __future__ import annotations

import typing as t

from libtmux.client import Client

if t.TYPE_CHECKING:
    from libtmux.server import Server


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
    session: t.Any,
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
