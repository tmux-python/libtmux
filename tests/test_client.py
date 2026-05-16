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
