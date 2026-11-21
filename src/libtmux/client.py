"""Pythonization of the :term:`tmux(1)` client.

libtmux.client
~~~~~~~~~~~~~~

"""

from __future__ import annotations

import dataclasses
import logging
import shlex
import typing as t

from libtmux import exc
from libtmux.common import raise_if_stderr
from libtmux.neo import Obj, fetch_obj

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window


logger = logging.getLogger(__name__)

# tmux compares format strings lexically. Match 3.6 patch letters and later
# numbered releases, including 3.10 and the next-X.Y and X.Y-rcN forms.
_AFTER_3_6 = r"(3[.]([7-9]|[1-9][0-9]+)|([4-9]|[1-9][0-9]+)[.][0-9]+)"
_CLIPBOARD_RELEASE = rf"^(3[.]6[a-z]|next-{_AFTER_3_6}|{_AFTER_3_6}([a-z]|-rc[0-9]*)?)$"
_CLIPBOARD_GATE = "#{m/r:" + _CLIPBOARD_RELEASE + ",#{version}}"


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
        view* at the moment this object was read — not stable identity
        for the client. When the client switches sessions via
        ``switch-client``, moves focus via ``select-window`` /
        ``select-pane``, or detaches, these fields go stale until
        :meth:`refresh` re-reads them from ``list-clients``. The
        ``client_name`` (tty path on Unix) is the client's stable
        identity.

        Prefer :meth:`attached_session`, :meth:`attached_window`, and
        :meth:`attached_pane` when you need the client's current
        attachment. Each property re-reads tmux before returning, so
        the :class:`Session` / :class:`Window` / :class:`Pane` you get
        back reflects where the client is attached *now*, not where it
        was when this :class:`Client` was constructed. If tmux no longer
        reports this ``client_name`` through ``list-clients``, these
        properties return ``None``.

        :meth:`attached_pane` follows the attached session's current
        window. That can differ from the per-client active pane set by
        ``select-pane -P``; see :meth:`attached_pane` for the exact
        behavior. Each property re-reads tmux on every access.

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

    def request_clipboard(self) -> None:
        """Ask this client's terminal for its clipboard via ``tmux refresh-client -l``.

        Requires a tmux 3.6a or later server. The call returns when tmux
        accepts the request. If the terminal permits OSC 52 clipboard reads
        and replies with data, tmux creates a new paste buffer.

        Raises
        ------
        ValueError
            If the client has no name to target.
        :exc:`~libtmux.exc.VersionTooLow`
            If the daemon reports an older or unrecognized release.
        :exc:`~libtmux.exc.LibTmuxException`
            If tmux reports an error, including when the client has detached.
        """
        if not self.client_name:
            msg = "Client must have a client_name to request the clipboard"
            raise ValueError(msg)

        # Evaluate the gate and issue the request on the same daemon.
        refused = "libtmux-clipboard-unavailable:"
        proc = self.server.cmd(
            "if-shell",
            "-F",
            _CLIPBOARD_GATE,
            shlex.join(["refresh-client", "-t", self.client_name, "-l"]),
            f"display-message -p '{refused}#{{version}}'",
        )
        raise_if_stderr(proc, "refresh-client")
        if proc.returncode:
            msg = f"tmux exited with status {proc.returncode}"
            raise exc.LibTmuxException(msg, subcommand="refresh-client")
        if proc.stdout and proc.stdout[0].startswith(refused):
            version = proc.stdout[0].removeprefix(refused)
            msg = f"clipboard requests require tmux 3.6a or later (daemon: {version!r})"
            raise exc.VersionTooLow(msg, subcommand="refresh-client")

    def refresh(self) -> None:
        """Refresh client attributes from tmux.

        Raises
        ------
        ValueError
            When ``client_name`` is unset. Surfaces a clear error under
            ``python -O``, where an ``assert`` would be stripped.
        """
        if self.client_name is None:
            msg = "Client must have a client_name to refresh"
            raise ValueError(msg)
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
        read. Returns ``None`` when tmux no longer reports this
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

        This follows the attached session's current window and active
        pane. When a client has used ``select-pane -P`` to set its own
        active pane, this property returns the *session's* current
        active pane, not the client's per-client focus.
        """
        window = self.attached_window
        if window is None:
            return None
        return window.active_pane

    def _resolve_attached(
        self,
    ) -> tuple[Session | None, Window | None, Pane | None]:
        """Resolve live attachment with a single ``list-clients`` refresh.

        The three :attr:`attached_session` / :attr:`attached_window` /
        :attr:`attached_pane` properties each trigger their own
        ``list-clients`` refresh — calling them in sequence performs three
        tmux reads for one conceptual "where is this client attached *now*"
        read. ``_resolve_attached`` shares a single refresh across the
        triple and returns the three values together.

        Returns
        -------
        tuple[Session | None, Window | None, Pane | None]
            * ``(None, None, None)`` when tmux no longer reports this
              ``client_name`` through ``list-clients``, when the client
              snapshot has no ``session_id``, or when the snapshot
              ``session_id`` no longer names a live session.
            * ``(session, None, None)`` when the attached session has no
              active window.
            * ``(session, window, pane)`` for a fully-resolved live
              attachment. ``pane`` is ``None`` only when the active
              window has no active pane.

        :exc:`~libtmux.exc.MultipleActiveWindows` propagates rather than
        collapsing to ``(session, None, None)`` — multiple active windows
        in one session indicates inconsistent tmux state that callers
        should see, not absent attachment.
        """
        try:
            self.refresh()
        except exc.TmuxObjectDoesNotExist:
            return None, None, None
        if self.session_id is None:
            return None, None, None
        session = self.server.sessions.get(
            session_id=self.session_id,
            default=None,
        )
        if session is None:
            return None, None, None
        try:
            window = session.active_window
        except exc.NoActiveWindow:
            return session, None, None
        return session, window, window.active_pane
