"""Removed-API table and ``dir()`` scoping for the tmux object classes.

libtmux._surface
~~~~~~~~~~~~~~~~

Removed names are not defined on the classes, so completion and ``dir()``
never offer them. :class:`SurfaceMixin` raises :class:`~libtmux.exc.DeprecatedError`
when one is read, and narrows ``dir()`` to the format fields each object owns.
"""

from __future__ import annotations

import dataclasses
import functools
import typing as t

from libtmux import exc


@dataclasses.dataclass(frozen=True)
class Removed:
    """A removed API and the message :class:`~libtmux.exc.DeprecatedError` carries."""

    deprecated: str
    replacement: str
    version: str

    def error(self) -> exc.DeprecatedError:
        """Return the error to raise on access."""
        return exc.DeprecatedError(
            deprecated=self.deprecated,
            replacement=self.replacement,
            version=self.version,
        )


REMOVED: dict[str, dict[str, Removed]] = {
    "Server": {
        "kill_server": Removed(
            "Server.kill_server()",
            "Server.kill()",
            "0.30.0",
        ),
        "_list_panes": Removed(
            "Server._list_panes()",
            "Server.panes property",
            "0.17.0",
        ),
        "_update_panes": Removed(
            "Server._update_panes()",
            "Server.panes property",
            "0.17.0",
        ),
        "get_by_id": Removed(
            "Server.get_by_id()",
            "Server.sessions.get(session_id=..., default=None)",
            "0.16.0",
        ),
        "where": Removed(
            "Server.where()",
            "Server.sessions.filter()",
            "0.17.0",
        ),
        "find_where": Removed(
            "Server.find_where()",
            "Server.sessions.get(default=None, **kwargs)",
            "0.17.0",
        ),
        "_list_windows": Removed(
            "Server._list_windows()",
            "Server.windows property",
            "0.17.0",
        ),
        "_update_windows": Removed(
            "Server._update_windows()",
            "Server.windows property",
            "0.17.0",
        ),
        "_sessions": Removed(
            "Server._sessions",
            "Server.sessions property",
            "0.17.0",
        ),
        "_list_sessions": Removed(
            "Server._list_sessions()",
            "Server.sessions property",
            "0.17.0",
        ),
        "list_sessions": Removed(
            "Server.list_sessions()",
            "Server.sessions property",
            "0.17.0",
        ),
        "children": Removed(
            "Server.children",
            "Server.sessions property",
            "0.17.0",
        ),
    },
    "Session": {
        "attached_pane": Removed(
            "Session.attached_pane",
            "Session.active_pane",
            "0.31.0",
        ),
        "attached_window": Removed(
            "Session.attached_window",
            "Session.active_window",
            "0.31.0",
        ),
        "attach_session": Removed(
            "Session.attach_session()",
            "Session.attach()",
            "0.30.0",
        ),
        "kill_session": Removed(
            "Session.kill_session()",
            "Session.kill()",
            "0.30.0",
        ),
        "get": Removed(
            "Session.get()",
            "direct attribute access (e.g., session.session_name)",
            "0.17.0",
        ),
        "get_by_id": Removed(
            "Session.get_by_id()",
            "Session.windows.get(window_id=..., default=None)",
            "0.16.0",
        ),
        "where": Removed(
            "Session.where()",
            "Session.windows.filter()",
            "0.17.0",
        ),
        "find_where": Removed(
            "Session.find_where()",
            "Session.windows.get(default=None, **kwargs)",
            "0.17.0",
        ),
        "_list_windows": Removed(
            "Session._list_windows()",
            "Session.windows property",
            "0.17.0",
        ),
        "_windows": Removed(
            "Session._windows",
            "Session.windows property",
            "0.17.0",
        ),
        "list_windows": Removed(
            "Session.list_windows()",
            "Session.windows property",
            "0.17.0",
        ),
        "children": Removed(
            "Session.children",
            "Session.windows property",
            "0.17.0",
        ),
    },
    "Window": {
        "split_window": Removed(
            "Window.split_window()",
            "Window.split()",
            "0.33.0",
        ),
        "attached_pane": Removed(
            "Window.attached_pane",
            "Window.active_pane",
            "0.31.0",
        ),
        "select_window": Removed(
            "Window.select_window()",
            "Window.select()",
            "0.30.0",
        ),
        "kill_window": Removed(
            "Window.kill_window()",
            "Window.kill()",
            "0.30.0",
        ),
        "get": Removed(
            "Window.get()",
            "direct attribute access (e.g., window.window_name)",
            "0.17.0",
        ),
        "get_by_id": Removed(
            "Window.get_by_id()",
            "Window.panes.get(pane_id=..., default=None)",
            "0.16.0",
        ),
        "where": Removed(
            "Window.where()",
            "Window.panes.filter()",
            "0.17.0",
        ),
        "find_where": Removed(
            "Window.find_where()",
            "Window.panes.get(default=None, **kwargs)",
            "0.17.0",
        ),
        "_list_panes": Removed(
            "Window._list_panes()",
            "Window.panes property",
            "0.17.0",
        ),
        "_panes": Removed(
            "Window._panes",
            "Window.panes property",
            "0.17.0",
        ),
        "list_panes": Removed(
            "Window.list_panes()",
            "Window.panes property",
            "0.17.0",
        ),
        "children": Removed(
            "Window.children",
            "Window.panes property",
            "0.17.0",
        ),
    },
    "Pane": {
        "select_pane": Removed(
            "Pane.select_pane()",
            "Pane.select()",
            "0.30.0",
        ),
        "split_window": Removed(
            "Pane.split_window()",
            "Pane.split()",
            "0.33.0",
        ),
        "get": Removed(
            "Pane.get()",
            "direct attribute access (e.g., pane.pane_id)",
            "0.17.0",
        ),
        "resize_pane": Removed(
            "Pane.resize_pane()",
            "Pane.resize()",
            "0.28.0",
        ),
    },
}
"""Removed names by class name. See ``MIGRATION`` for the replacements."""

_PARENT_IDENTITY: frozenset[str] = frozenset(
    {"session_id", "session_name", "window_id", "window_index", "window_name"},
)
"""The only fields of an ancestor object ``dir()`` lists on a child."""

_OWN_SCOPES: dict[str, tuple[str, ...]] = {
    "Session": ("session",),
    "Window": ("window",),
    "Pane": ("pane",),
}
"""Format-token scopes each class owns, as named by :func:`libtmux.neo._token_scope`."""


@functools.cache
def _hidden_fields(cls_name: str) -> frozenset[str]:
    """Return the format fields ``dir()`` leaves out for *cls_name*.

    A field stays listed when its scope is the class's own, or when it names
    the parent session or window. Every other field stays readable.
    """
    from libtmux.neo import Obj, _token_scope

    own = _OWN_SCOPES.get(cls_name)
    if own is None:
        return frozenset()
    return frozenset(
        name
        for name in Obj.__dataclass_fields__
        if name != "server"
        and _token_scope(name) not in own
        and name not in _PARENT_IDENTITY
    )


class SurfaceMixin:
    """Raise on removed names and keep ``dir()`` to the supported surface."""

    if not t.TYPE_CHECKING:

        def __getattr__(self, name: str) -> t.Any:
            for cls in type(self).__mro__:
                removed = REMOVED.get(cls.__name__, {}).get(name)
                if removed is not None:
                    raise removed.error()
            if hasattr(type(self), name):
                # A property raised AttributeError itself; surface that error.
                return object.__getattribute__(self, name)
            msg = f"{type(self).__name__!r} object has no attribute {name!r}"
            raise AttributeError(msg)

    def __dir__(self) -> list[str]:
        hidden = _hidden_fields(type(self).__name__)
        return [name for name in super().__dir__() if name not in hidden]
