"""Temporary object helpers for libtmux and downstream libtmux libraries."""

from __future__ import annotations

import contextlib
import logging
import typing as t

from libtmux.test.random import get_test_session_name, get_test_window_name

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:
    import sys
    from collections.abc import Generator

    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

    if sys.version_info >= (3, 11):
        pass


@contextlib.contextmanager
def temp_session(
    server: Server,
    *args: t.Any,
    **kwargs: t.Any,
) -> Generator[Session, t.Any, t.Any]:
    """
    Provide a context manager for a temporary session, killed on exit.

    If no ``session_name`` is specified, :func:`get_test_session_name` will
    generate an unused one. The session is destroyed upon exiting the context
    manager.

    Parameters
    ----------
    server : Server
        The tmux server instance.
    args : list
        Additional positional arguments for :meth:`Server.new_session`.
    kwargs : dict
        Keyword arguments for :meth:`Server.new_session`.

    Yields
    ------
    Session
        The newly created temporary session.

    Examples
    --------
    >>> with temp_session(server) as session:
    ...     session.new_window(window_name='my window')
    Window(@3 2:my window, Session($... ...))
    """
    if "session_name" in kwargs:
        session_name = kwargs.pop("session_name")
    else:
        session_name = get_test_session_name(server)

    session = server.new_session(session_name, *args, **kwargs)

    try:
        yield session
    finally:
        if server.has_session(session_name):
            session.kill()
    return


@contextlib.contextmanager
def temp_window(
    session: Session,
    *args: t.Any,
    **kwargs: t.Any,
) -> Generator[Window, t.Any, t.Any]:
    """
    Provide a context manager for a temporary window, killed on exit.

    If no ``window_name`` is specified, :func:`get_test_window_name` will
    generate an unused one. The window is destroyed upon exiting the context
    manager.

    Parameters
    ----------
    session : Session
        The tmux session instance.
    args : list
        Additional positional arguments for :meth:`Session.new_window`.
    kwargs : dict
        Keyword arguments for :meth:`Session.new_window`.

    Yields
    ------
    Window
        The newly created temporary window.

    Examples
    --------
    >>> with temp_window(session) as window:
    ...     window
    Window(@2 2:... Session($1 libtmux_...))

    >>> with temp_window(session) as window:
    ...     window.split()
    Pane(%4 Window(@3 2:libtmux_..., Session($1 libtmux_...)))
    """
    if "window_name" not in kwargs:
        window_name = get_test_window_name(session)
    else:
        window_name = kwargs.pop("window_name")

    window = session.new_window(window_name, *args, **kwargs)
    window_id = window.window_id
    assert window_id is not None
    assert isinstance(window_id, str)

    try:
        yield window
    finally:
        if len(session.windows.filter(window_id=window_id)) > 0:
            window.kill()
    return
