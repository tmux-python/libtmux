"""Temporary object helpers for libtmux and downstream libtmux libraries."""

from __future__ import annotations

import contextlib
import logging
import typing as t

from libtmux.test.random import get_test_session_name, get_test_window_name

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:
    import sys

    from typing_extensions import Unpack

    from libtmux._internal.types import StrPath
    from libtmux.constants import WindowDirection
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

    if sys.version_info >= (3, 11):
        pass


class TempSessionParams(t.TypedDict, total=False):
    """Keyword arguments for :func:`temp_session`."""

    session_name: str | None
    kill_session: bool
    attach: bool
    start_directory: StrPath | None
    window_name: str | None
    window_command: str | None
    x: int | t.Literal["-"] | None
    y: int | t.Literal["-"] | None
    environment: dict[str, str] | None


class TempSessionKwargs(t.TypedDict, total=False):
    """Keyword arguments forwarded to :meth:`Server.new_session`."""

    kill_session: bool
    attach: bool
    start_directory: StrPath | None
    window_name: str | None
    window_command: str | None
    x: int | t.Literal["-"] | None
    y: int | t.Literal["-"] | None
    environment: dict[str, str] | None


class TempWindowParams(t.TypedDict, total=False):
    """Keyword arguments for :func:`temp_window`."""

    window_name: str | None
    start_directory: StrPath | None
    attach: bool
    window_index: str
    window_shell: str | None
    environment: dict[str, str] | None
    direction: WindowDirection | None
    target_window: str | None


class TempWindowKwargs(t.TypedDict, total=False):
    """Keyword arguments forwarded to :meth:`Session.new_window`."""

    start_directory: StrPath | None
    attach: bool
    window_index: str
    window_shell: str | None
    environment: dict[str, str] | None
    direction: WindowDirection | None
    target_window: str | None


@contextlib.contextmanager
def _temp_session(
    server: Server,
    *args: t.Any,
    **kwargs: object,
) -> t.Iterator[Session]:
    kwargs_typed = t.cast("TempSessionParams", dict(kwargs))
    if "session_name" in kwargs_typed:
        session_name = kwargs_typed["session_name"]
    else:
        session_name = get_test_session_name(server)
    kwargs_no_name = t.cast(
        "TempSessionKwargs",
        {k: v for k, v in kwargs_typed.items() if k != "session_name"},
    )

    session = server.new_session(
        session_name,
        *args,
        **kwargs_no_name,
    )

    try:
        yield session
    finally:
        if isinstance(session_name, str) and server.has_session(session_name):
            session.kill()


@t.overload
def temp_session(
    server: Server,
    **kwargs: Unpack[TempSessionParams],
) -> contextlib.AbstractContextManager[Session]: ...


@t.overload
def temp_session(
    server: Server,
    *args: t.Any,
    **kwargs: object,
) -> contextlib.AbstractContextManager[Session]: ...


def temp_session(
    server: Server,
    *args: t.Any,
    **kwargs: object,
) -> contextlib.AbstractContextManager[Session]:
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
    return _temp_session(server, *args, **kwargs)


@contextlib.contextmanager
def _temp_window(
    session: Session,
    *args: t.Any,
    **kwargs: object,
) -> t.Iterator[Window]:
    kwargs_typed = t.cast("TempWindowParams", dict(kwargs))
    if "window_name" in kwargs_typed:
        window_name = kwargs_typed["window_name"]
    else:
        window_name = get_test_window_name(session)
    kwargs_no_name = t.cast(
        "TempWindowKwargs",
        {k: v for k, v in kwargs_typed.items() if k != "window_name"},
    )

    window = session.new_window(
        window_name,
        *args,
        **kwargs_no_name,
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


@t.overload
def temp_window(
    session: Session,
    **kwargs: Unpack[TempWindowParams],
) -> contextlib.AbstractContextManager[Window]: ...


@t.overload
def temp_window(
    session: Session,
    *args: t.Any,
    **kwargs: object,
) -> contextlib.AbstractContextManager[Window]: ...


def temp_window(
    session: Session,
    *args: t.Any,
    **kwargs: object,
) -> contextlib.AbstractContextManager[Window]:
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
    return _temp_window(session, *args, **kwargs)
