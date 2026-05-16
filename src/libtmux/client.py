"""Pythonization of the :term:`tmux(1)` client.

libtmux.client
~~~~~~~~~~~~~~

"""

from __future__ import annotations

import dataclasses
import logging
import typing as t

from libtmux.neo import Obj, fetch_obj

if t.TYPE_CHECKING:
    from libtmux.server import Server


logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Client(Obj):
    """:term:`tmux(1)` :term:`Client` [client_manual]_.

    A tmux client is an attached terminal. The same tmux server can have
    multiple clients attached simultaneously (e.g. ``$ tmux attach`` from
    several terminals) and each receives its own view of the active
    session, window, and pane.

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
