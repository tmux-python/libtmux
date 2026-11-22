"""Temporary object helpers for libtmux and downstream libtmux libraries."""

from __future__ import annotations

import contextlib
import typing as t

from libtmux.test.random import get_test_session_name, get_test_window_name

if t.TYPE_CHECKING:
    from collections.abc import Generator

    from libtmux._internal.types import StrPath
    from libtmux.constants import WindowDirection
    from libtmux.server import DashLiteral, Server
    from libtmux.session import Session
    from libtmux.window import Window


@contextlib.contextmanager
def temp_session(
    server: Server,
    session_name: str | None = None,
    kill_session: bool = False,
    attach: bool = False,
    start_directory: StrPath | None = None,
    window_name: str | None = None,
    window_command: str | None = None,
    x: int | DashLiteral | None = None,
    y: int | DashLiteral | None = None,
    environment: dict[str, str] | None = None,
    *args: object,
    detach_others: bool | None = None,
    no_size: bool | None = None,
    client_flags: str | None = None,
    **kwargs: object,
) -> Generator[Session, None, None]:
    """
    Return a context manager with a temporary session.

    If no ``session_name`` is entered, :func:`get_test_session_name` will make
    an unused session name.

    The session will destroy itself upon closing with :meth:`Session.session()`.

    Parameters
    ----------
    server : :class:`libtmux.Server`

    Other Parameters
    ----------------
    args : list
        Arguments passed into :meth:`Server.new_session`
    kwargs : dict
        Keyword arguments passed into :meth:`Server.new_session`

    Yields
    ------
    :class:`libtmux.Session`
        Temporary session

    Examples
    --------
    >>> with temp_session(server) as session:
    ...     session.new_window(window_name='my window')
    Window(@3 2:my window, Session($... ...))
    """
    resolved_name = (
        session_name if session_name is not None else get_test_session_name(server)
    )

    session = server.new_session(
        resolved_name,
        kill_session,
        attach,
        start_directory,
        window_name,
        window_command,
        x,
        y,
        environment,
        *args,
        detach_others=detach_others,
        no_size=no_size,
        client_flags=client_flags,
        **kwargs,
    )

    try:
        yield session
    finally:
        if server.has_session(resolved_name):
            session.kill()
    return


@contextlib.contextmanager
def temp_window(
    session: Session,
    window_name: str | None = None,
    *,
    start_directory: StrPath | None = None,
    attach: bool = False,
    window_index: str = "",
    window_shell: str | None = None,
    environment: dict[str, str] | None = None,
    direction: WindowDirection | None = None,
    target_window: str | None = None,
    kill_existing: bool | None = None,
    select_existing: bool | None = None,
) -> Generator[Window, None, None]:
    """
    Return a context manager with a temporary window.

    The window will destroy itself upon closing with :meth:`window.
    kill()`.

    If no ``window_name`` is entered, :func:`get_test_window_name` will make
    an unused window name.

    Parameters
    ----------
    session : :class:`libtmux.Session`

    Other Parameters
    ----------------
    args : list
        Arguments passed into :meth:`Session.new_window`
    kwargs : dict
        Keyword arguments passed into :meth:`Session.new_window`

    Yields
    ------
    :class:`libtmux.Window`
        temporary window

    Examples
    --------
    >>> with temp_window(session) as window:
    ...     window
    Window(@2 2:... Session($1 libtmux_...))


    >>> with temp_window(session) as window:
    ...     window.split()
    Pane(%4 Window(@3 2:libtmux_..., Session($1 libtmux_...)))
    """
    resolved_window_name = (
        get_test_window_name(session) if window_name is None else window_name
    )

    window = session.new_window(
        resolved_window_name,
        start_directory=start_directory,
        attach=attach,
        window_index=window_index,
        window_shell=window_shell,
        environment=environment,
        direction=direction,
        target_window=target_window,
        kill_existing=kill_existing,
        select_existing=select_existing,
    )

    # Get ``window_id`` before returning it, it may be killed within context.
    window_id = window.window_id
    assert window_id is not None
    assert isinstance(window_id, str)

    try:
        yield window
    finally:
        if len(session.windows.filter(window_id=window_id)) > 0:
            window.kill()
    return
