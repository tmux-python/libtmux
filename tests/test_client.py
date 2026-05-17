"""Tests for libtmux Client object."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.client import Client
from libtmux.pane import Pane
from libtmux.session import Session
from libtmux.window import Window

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


def test_client_attached_session_returns_typed_session(
    control_mode: t.Callable[..., t.Any],
    server: Server,
    session: Session,
) -> None:
    """``client.attached_session`` resolves to the live :class:`Session`."""
    with control_mode() as ctl:
        client = server.clients.get(client_name=ctl.client_name)
        assert client is not None

        attached = client.attached_session
        assert isinstance(attached, Session)
        assert attached.session_id == session.session_id


def test_client_attached_window_tracks_active_window(
    control_mode: t.Callable[..., t.Any],
    server: Server,
    session: Session,
) -> None:
    """``client.attached_window`` reflects the live active window.

    Selects a freshly created window after hydrating the client, then
    asserts the property reports the new selection — proves the
    property re-reads rather than returning the snapshot.
    """
    with control_mode() as ctl:
        client = server.clients.get(client_name=ctl.client_name)
        assert client is not None
        snapshot_window_id = client.window_id

        new_window = session.new_window(window_name="attached_window_probe")
        assert new_window.window_index is not None
        session.select_window(new_window.window_index)

        attached = client.attached_window
        assert isinstance(attached, Window)
        assert attached.window_id == new_window.window_id
        assert attached.window_id != snapshot_window_id


def test_client_attached_pane_tracks_active_pane(
    control_mode: t.Callable[..., t.Any],
    server: Server,
    session: Session,
) -> None:
    """``client.attached_pane`` reflects the active pane in the active window."""
    with control_mode() as ctl:
        client = server.clients.get(client_name=ctl.client_name)
        assert client is not None

        attached = client.attached_pane
        assert isinstance(attached, Pane)
        assert attached.pane_id == session.active_window.active_pane.pane_id  # type: ignore[union-attr]


def test_client_attached_properties_return_none_after_detach(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """``attached_*`` returns ``None`` after the client leaves ``list-clients``."""
    with control_mode() as ctl:
        client = server.clients.get(client_name=ctl.client_name)
        assert client is not None

        assert client.attached_session is not None
        assert client.attached_window is not None
        assert client.attached_pane is not None

    assert client.attached_session is None
    assert client.attached_window is None
    assert client.attached_pane is None


def test_client_refresh_raises_when_client_name_is_none(server: Server) -> None:
    """``Client.refresh()`` raises ``ValueError`` when ``client_name`` is unset.

    The previous ``assert isinstance(...)`` stripped under ``python -O`` and
    let ``None`` flow into ``_refresh``, surfacing as a confusing downstream
    error. The explicit raise keeps the failure mode loud regardless of
    optimization level.
    """
    client = Client(server=server)
    assert client.client_name is None

    with pytest.raises(ValueError, match="client_name"):
        client.refresh()


def test_resolve_attached_returns_full_triple_for_live_client(
    control_mode: t.Callable[..., t.Any],
    server: Server,
    session: Session,
) -> None:
    """``_resolve_attached`` returns ``(session, window, pane)`` for a live client."""
    with control_mode() as ctl:
        client = server.clients.get(client_name=ctl.client_name)
        assert client is not None

        resolved_session, resolved_window, resolved_pane = client._resolve_attached()

        assert resolved_session is not None
        assert resolved_session.session_id == session.session_id
        assert resolved_window is not None
        assert resolved_pane is not None


def test_resolve_attached_returns_none_triple_after_detach(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """``_resolve_attached`` returns ``(None, None, None)`` after detach.

    Once tmux no longer reports this ``client_name``, the refresh raises
    ``TmuxObjectDoesNotExist`` internally and the helper returns the
    none-triple — matching :attr:`attached_session` / etc.'s contract for
    a stale client name.
    """
    with control_mode() as ctl:
        client = server.clients.get(client_name=ctl.client_name)
        assert client is not None

    # Client has detached at this point.
    resolved = client._resolve_attached()
    assert resolved == (None, None, None)


def test_resolve_attached_catches_no_active_window(
    control_mode: t.Callable[..., t.Any],
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_resolve_attached`` returns ``(session, None, None)`` on NoActiveWindow.

    Patches the live session's ``active_window`` to raise
    :exc:`~libtmux.exc.NoActiveWindow` (a state tmux normally prevents
    but the helper still has to handle gracefully), and asserts the
    helper falls back to the no-active-window triple rather than
    propagating.
    """
    from libtmux import exc as libtmux_exc
    from libtmux.session import Session as SessionCls

    with control_mode() as ctl:
        client = server.clients.get(client_name=ctl.client_name)
        assert client is not None

        def raise_no_active_window(self: SessionCls) -> Window:
            raise libtmux_exc.NoActiveWindow

        monkeypatch.setattr(
            SessionCls, "active_window", property(raise_no_active_window)
        )

        resolved_session, resolved_window, resolved_pane = client._resolve_attached()
        assert resolved_session is not None
        assert resolved_window is None
        assert resolved_pane is None
