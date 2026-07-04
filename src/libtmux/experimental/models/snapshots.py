"""Pure, immutable snapshots of the tmux object graph.

These are *values*, not live objects: a snapshot captures the state of a server,
session, window, or pane at one moment, with no reference to a
:class:`~libtmux.Server` and no ability to issue tmux commands. They resemble
:class:`libtmux.neo.Obj` but are decoupled from the query/dispatch pipeline and
from each other, so experimenting with them cannot affect the existing ORM APIs.

Each snapshot keeps a typed *core* of the most-used fields plus the full raw
format mapping in :attr:`fields`, so nothing tmux reported is lost. Snapshots
compose into a tree (:class:`ServerSnapshot` → :class:`SessionSnapshot` →
:class:`WindowSnapshot` → :class:`PaneSnapshot`), can be built from a single
``list-panes -a -F`` style row set via :meth:`ServerSnapshot.from_pane_rows`,
and round-trip to plain dicts for serialization or diffing.
"""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass, field

if t.TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_TRUE = {"1", "on", "yes", "true"}


def _as_int(value: str | None) -> int | None:
    """Coerce a tmux format value to ``int``, or ``None`` if absent/non-numeric.

    Examples
    --------
    >>> _as_int("3")
    3
    >>> _as_int("") is None
    True
    >>> _as_int(None) is None
    True
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _as_bool(value: str | None) -> bool:
    """Coerce a tmux flag value (``"1"``/``"0"``/``""``) to ``bool``.

    Examples
    --------
    >>> _as_bool("1")
    True
    >>> _as_bool("0")
    False
    >>> _as_bool(None)
    False
    """
    return value is not None and value.lower() in _TRUE


@dataclass(frozen=True)
class PaneSnapshot:
    """An immutable snapshot of one tmux pane.

    Examples
    --------
    >>> pane = PaneSnapshot.from_format({
    ...     "pane_id": "%1", "pane_index": "0", "window_id": "@1",
    ...     "session_id": "$0", "pane_active": "1", "pane_width": "80",
    ...     "pane_height": "24", "pane_current_command": "zsh",
    ... })
    >>> pane.pane_id, pane.pane_index, pane.active, pane.width
    ('%1', 0, True, 80)
    >>> pane.current_command
    'zsh'

    The ``floating`` flag reflects ``#{pane_floating_flag}`` (tmux 3.7+):

    >>> PaneSnapshot.from_format({"pane_id": "%9", "pane_floating_flag": "1"}).floating
    True
    >>> pane.floating
    False
    """

    pane_id: str = ""
    pane_index: int | None = None
    window_id: str = ""
    session_id: str = ""
    active: bool = False
    width: int | None = None
    height: int | None = None
    current_command: str | None = None
    current_path: str | None = None
    title: str | None = None
    pid: int | None = None
    floating: bool = False
    fields: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_format(cls, raw: Mapping[str, str]) -> PaneSnapshot:
        """Build a pane snapshot from a raw tmux format mapping."""
        return cls(
            pane_id=raw.get("pane_id", ""),
            pane_index=_as_int(raw.get("pane_index")),
            window_id=raw.get("window_id", ""),
            session_id=raw.get("session_id", ""),
            active=_as_bool(raw.get("pane_active")),
            width=_as_int(raw.get("pane_width")),
            height=_as_int(raw.get("pane_height")),
            current_command=raw.get("pane_current_command"),
            current_path=raw.get("pane_current_path"),
            title=raw.get("pane_title"),
            pid=_as_int(raw.get("pane_pid")),
            floating=_as_bool(raw.get("pane_floating_flag")),
            fields=dict(raw),
        )

    def to_dict(self) -> dict[str, t.Any]:
        """Serialize to a plain dict (raw fields only; typed core re-derives)."""
        return {"fields": dict(self.fields)}

    @classmethod
    def from_dict(cls, data: Mapping[str, t.Any]) -> PaneSnapshot:
        """Reconstruct from :meth:`to_dict` output."""
        return cls.from_format(data["fields"])


@dataclass(frozen=True)
class ClientSnapshot:
    """An immutable snapshot of one attached tmux client.

    A client is a view (a terminal attachment), not part of the ownership tree,
    so it is a leaf snapshot.

    Examples
    --------
    >>> client = ClientSnapshot.from_format({
    ...     "client_name": "/dev/pts/3", "client_tty": "/dev/pts/3",
    ...     "client_session": "$0", "client_pid": "4242",
    ... })
    >>> client.name, client.session, client.pid
    ('/dev/pts/3', '$0', 4242)
    """

    name: str = ""
    tty: str | None = None
    session: str = ""
    pid: int | None = None
    width: int | None = None
    height: int | None = None
    fields: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_format(cls, raw: Mapping[str, str]) -> ClientSnapshot:
        """Build a client snapshot from a raw tmux format mapping."""
        return cls(
            name=raw.get("client_name", ""),
            tty=raw.get("client_tty"),
            session=raw.get("client_session", ""),
            pid=_as_int(raw.get("client_pid")),
            width=_as_int(raw.get("client_width")),
            height=_as_int(raw.get("client_height")),
            fields=dict(raw),
        )


@dataclass(frozen=True)
class WindowSnapshot:
    """An immutable snapshot of one tmux window and its panes.

    Examples
    --------
    >>> win = WindowSnapshot.from_format({
    ...     "window_id": "@1", "window_index": "0", "window_name": "main",
    ...     "session_id": "$0", "window_active": "1",
    ... })
    >>> win.window_id, win.window_index, win.name, win.active
    ('@1', 0, 'main', True)
    >>> win.panes
    ()
    """

    window_id: str = ""
    window_index: int | None = None
    name: str | None = None
    session_id: str = ""
    active: bool = False
    layout: str | None = None
    panes: tuple[PaneSnapshot, ...] = ()
    fields: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_format(cls, raw: Mapping[str, str]) -> WindowSnapshot:
        """Build a window snapshot from a raw tmux format mapping."""
        return cls(
            window_id=raw.get("window_id", ""),
            window_index=_as_int(raw.get("window_index")),
            name=raw.get("window_name"),
            session_id=raw.get("session_id", ""),
            active=_as_bool(raw.get("window_active")),
            layout=raw.get("window_layout"),
            fields=dict(raw),
        )

    def to_dict(self) -> dict[str, t.Any]:
        """Serialize to a plain dict, including child panes."""
        return {
            "fields": dict(self.fields),
            "panes": [pane.to_dict() for pane in self.panes],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, t.Any]) -> WindowSnapshot:
        """Reconstruct from :meth:`to_dict` output."""
        return dataclasses.replace(
            cls.from_format(data["fields"]),
            panes=tuple(PaneSnapshot.from_dict(p) for p in data.get("panes", [])),
        )


@dataclass(frozen=True)
class SessionSnapshot:
    """An immutable snapshot of one tmux session and its windows."""

    session_id: str = ""
    name: str | None = None
    attached: bool = False
    windows: tuple[WindowSnapshot, ...] = ()
    fields: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_format(cls, raw: Mapping[str, str]) -> SessionSnapshot:
        """Build a session snapshot from a raw tmux format mapping."""
        return cls(
            session_id=raw.get("session_id", ""),
            name=raw.get("session_name"),
            attached=_as_bool(raw.get("session_attached")),
            fields=dict(raw),
        )

    def to_dict(self) -> dict[str, t.Any]:
        """Serialize to a plain dict, including child windows."""
        return {
            "fields": dict(self.fields),
            "windows": [window.to_dict() for window in self.windows],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, t.Any]) -> SessionSnapshot:
        """Reconstruct from :meth:`to_dict` output."""
        return dataclasses.replace(
            cls.from_format(data["fields"]),
            windows=tuple(WindowSnapshot.from_dict(w) for w in data.get("windows", [])),
        )


@dataclass(frozen=True)
class ServerSnapshot:
    """An immutable snapshot of a tmux server's session/window/pane tree.

    Examples
    --------
    Build the whole graph from a flat ``list-panes -a -F`` style row set:

    >>> rows = [
    ...     {"session_id": "$0", "session_name": "work", "window_id": "@1",
    ...      "window_index": "0", "window_name": "main", "pane_id": "%1",
    ...      "pane_index": "0", "pane_active": "1"},
    ...     {"session_id": "$0", "session_name": "work", "window_id": "@1",
    ...      "window_index": "0", "window_name": "main", "pane_id": "%2",
    ...      "pane_index": "1", "pane_active": "0"},
    ... ]
    >>> server = ServerSnapshot.from_pane_rows(rows, socket_name="default")
    >>> [s.name for s in server.sessions]
    ['work']
    >>> [p.pane_id for p in server.sessions[0].windows[0].panes]
    ['%1', '%2']
    """

    socket_name: str | None = None
    socket_path: str | None = None
    sessions: tuple[SessionSnapshot, ...] = ()

    @classmethod
    def from_pane_rows(
        cls,
        rows: Iterable[Mapping[str, str]],
        *,
        socket_name: str | None = None,
        socket_path: str | None = None,
    ) -> ServerSnapshot:
        """Group flat per-pane rows into a session/window/pane tree.

        Each row is one pane's format mapping carrying its ``session_*`` and
        ``window_*`` fields too (as ``tmux list-panes -a -F`` yields). The first
        row seen for a session/window supplies that level's fields; insertion
        order is preserved.
        """
        session_order: list[str] = []
        session_fields: dict[str, Mapping[str, str]] = {}
        window_order: dict[str, list[str]] = {}
        window_fields: dict[str, Mapping[str, str]] = {}
        window_panes: dict[str, list[PaneSnapshot]] = {}

        for row in rows:
            session_id = row.get("session_id", "")
            window_id = row.get("window_id", "")
            if session_id not in session_fields:
                session_fields[session_id] = row
                session_order.append(session_id)
                window_order[session_id] = []
            if window_id not in window_fields:
                window_fields[window_id] = row
                window_order[session_id].append(window_id)
                window_panes[window_id] = []
            window_panes[window_id].append(PaneSnapshot.from_format(row))

        sessions = tuple(
            dataclasses.replace(
                SessionSnapshot.from_format(session_fields[session_id]),
                windows=tuple(
                    dataclasses.replace(
                        WindowSnapshot.from_format(window_fields[window_id]),
                        panes=tuple(window_panes[window_id]),
                    )
                    for window_id in window_order[session_id]
                ),
            )
            for session_id in session_order
        )
        return cls(
            socket_name=socket_name,
            socket_path=socket_path,
            sessions=sessions,
        )

    def to_dict(self) -> dict[str, t.Any]:
        """Serialize the whole tree to plain data."""
        return {
            "socket_name": self.socket_name,
            "socket_path": self.socket_path,
            "sessions": [session.to_dict() for session in self.sessions],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, t.Any]) -> ServerSnapshot:
        """Reconstruct the whole tree from :meth:`to_dict` output."""
        return cls(
            socket_name=data.get("socket_name"),
            socket_path=data.get("socket_path"),
            sessions=tuple(
                SessionSnapshot.from_dict(s) for s in data.get("sessions", [])
            ),
        )
