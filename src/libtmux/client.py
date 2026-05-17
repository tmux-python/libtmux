"""Pythonization of the :term:`tmux(1)` client.

libtmux.client
~~~~~~~~~~~~~~

"""

from __future__ import annotations

import dataclasses
import logging
import typing as t

from libtmux import exc
from libtmux.neo import Obj, fetch_obj

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window


logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Client(Obj):
    """:term:`tmux(1)` :term:`Client` [client_manual]_.

    A tmux client is an attached terminal. The same tmux server can have
    multiple clients attached simultaneously (e.g. ``$ tmux attach`` from
    several terminals) and each receives its own view of the active
    session, window, and pane.

    .. warning::

        ``client_session``, ``session_id``, ``window_id`` and
        ``pane_id`` are snapshots of the client's *currently attached
        view* at the moment the dataclass is hydrated — not stable
        identity for the client. When the client switches sessions via
        ``switch-client``, moves focus via ``select-window`` /
        ``select-pane``, or detaches, these fields go stale until
        :meth:`refresh` re-reads them from ``list-clients``. The
        ``client_name`` (tty path on Unix) is the client's stable
        identity.

        Prefer :meth:`attached_session`, :meth:`attached_window`, and
        :meth:`attached_pane` for typed access — each re-reads the
        client's current attachment before returning, so the
        :class:`Session` / :class:`Window` / :class:`Pane` you get
        back reflects where the client is attached *now*, not where
        it was when this :class:`Client` was constructed. If tmux no
        longer reports this ``client_name`` through ``list-clients``,
        these properties return ``None``.

        :meth:`attached_pane` is session-scope: it returns the
        session's current window's active pane, not the client's
        ``CLIENT_ACTIVEPANE`` focus. The two diverge once a client
        has used ``select-pane -P`` to set its own active pane.
        See :meth:`attached_pane` for the resolution detail.

    Parameters
    ----------
    server : :class:`Server`

    Examples
    --------
    >>> with control_mode() as ctl:
    ...     attached = [
    ...         c
    ...         for c in server.clients
    ...         if c.client_name == ctl.client_name
    ...     ]
    >>> bool(attached)
    True

    >>> with control_mode() as ctl:
    ...     client = server.clients.get(client_name=ctl.client_name)
    ...     client.client_readonly in {"0", "1"}
    True

    References
    ----------
    .. [client_manual] tmux client. openbsd manpage for TMUX(1).
           "tmux supports multiple attached clients. Each client has its
           own keymap, view of the session, and message log."

       https://man.openbsd.org/tmux.1#DESCRIPTION. Accessed 2026.
    """

    server: Server

    def refresh(self) -> None:
        """Refresh client attributes from tmux."""
        assert isinstance(self.client_name, str)
        return super()._refresh(
            obj_key="client_name",
            obj_id=self.client_name,
            list_cmd="list-clients",
        )

    @classmethod
    def from_client_name(cls, server: Server, client_name: str) -> Client:
        """Create Client from an existing client_name."""
        client = fetch_obj(
            obj_key="client_name",
            obj_id=client_name,
            list_cmd="list-clients",
            server=server,
        )
        return cls(server=server, **client)

    #
    # Computed properties
    #
    @property
    def attached_session(self) -> Session | None:
        """Return the :class:`Session` this client is currently attached to.

        Re-reads the client from ``list-clients`` before resolving, so the
        returned :class:`Session` reflects the client's *live* attachment
        rather than the snapshot captured when this :class:`Client` was
        hydrated. Returns ``None`` when tmux no longer reports this
        ``client_name`` through ``list-clients``, when the client is not
        attached to any session, or when the snapshot ``session_id`` no
        longer names a live session.

        Examples
        --------
        >>> with control_mode() as ctl:
        ...     client = server.clients.get(client_name=ctl.client_name)
        ...     attached = client.attached_session
        >>> attached is not None
        True
        """
        try:
            self.refresh()
        except exc.TmuxObjectDoesNotExist:
            return None
        if self.session_id is None:
            return None
        return self.server.sessions.get(
            session_id=self.session_id,
            default=None,
        )

    @property
    def attached_window(self) -> Window | None:
        """Return the :class:`Window` this client is currently viewing.

        Re-reads the client from ``list-clients``, looks up its attached
        session, and returns that session's :attr:`~libtmux.Session.active_window`.
        Returns ``None`` when no live attached session can be resolved.
        """
        session = self.attached_session
        if session is None:
            return None
        return session.active_window

    @property
    def attached_pane(self) -> Pane | None:
        """Return the :class:`Pane` this client is currently viewing.

        Re-reads the client from ``list-clients``, looks up its attached
        session's current window, and returns that window's
        :attr:`~libtmux.Window.active_pane`. Returns ``None`` when no
        live attached session or active pane can be resolved.

        Resolution follows tmux's downward ``format_defaults`` cascade
        (``c->session`` → ``s->curw`` → ``wl->window->active``), not
        the per-client ``CLIENT_ACTIVEPANE`` flag. When a client has
        used ``select-pane -P`` to set its own active pane, this
        property returns the *session's* current active pane, not the
        client's.
        """
        window = self.attached_window
        if window is None:
            return None
        return window.active_pane
