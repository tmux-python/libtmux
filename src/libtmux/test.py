"""Helper methods for libtmux and downstream libtmux libraries."""

import contextlib
import logging
import os
import pathlib
import random
import time
import types
import typing as t
from typing import Callable, Optional

from libtmux.server import Server

from .exc import WaitTimeout

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:
    from libtmux.session import Session
    from libtmux.window import Window

TEST_SESSION_PREFIX = "libtmux_"
RETRY_TIMEOUT_SECONDS = int(os.getenv("RETRY_TIMEOUT_SECONDS", 8))
RETRY_INTERVAL_SECONDS = float(os.getenv("RETRY_INTERVAL_SECONDS", 0.05))


class RandomStrSequence:
    """Factory to generate random string."""

    def __init__(
        self,
        characters: str = "abcdefghijklmnopqrstuvwxyz0123456789_",
    ) -> None:
        """Create a random letter / number generator. 8 chars in length.

        >>> rng = RandomStrSequence()
        >>> next(rng)
        '...'
        >>> len(next(rng))
        8
        >>> type(next(rng))
        <class 'str'>
        """
        self.characters: str = characters

    def __iter__(self) -> "RandomStrSequence":
        """Return self."""
        return self

    def __next__(self) -> str:
        """Return next random string."""
        return "".join(random.sample(self.characters, k=8))


namer = RandomStrSequence()
current_dir = pathlib.Path(__file__)
example_dir = current_dir.parent / "examples"
fixtures_dir = current_dir / "fixtures"


def retry_until(
    fun: Callable[[], bool],
    seconds: float = RETRY_TIMEOUT_SECONDS,
    *,
    interval: float = RETRY_INTERVAL_SECONDS,
    raises: Optional[bool] = True,
) -> bool:
    """
    Retry a function until a condition meets or the specified time passes.

    Parameters
    ----------
    fun : callable
        A function that will be called repeatedly until it returns ``True``  or
        the specified time passes.
    seconds : float
        Seconds to retry. Defaults to ``8``, which is configurable via
        ``RETRY_TIMEOUT_SECONDS`` environment variables.
    interval : float
        Time in seconds to wait between calls. Defaults to ``0.05`` and is
        configurable via ``RETRY_INTERVAL_SECONDS`` environment variable.
    raises : bool
        Whether or not to raise an exception on timeout. Defaults to ``True``.

    Examples
    --------
    >>> def fn():
    ...     p = session.active_window.active_pane
    ...     return p.pane_current_path is not None

    >>> retry_until(fn)
    True

    In pytest:

    >>> assert retry_until(fn, raises=False)
    """
    ini = time.time()

    while not fun():
        end = time.time()
        if end - ini >= seconds:
            if raises:
                raise WaitTimeout
            return False
        time.sleep(interval)
    return True


def get_test_session_name(server: "Server", prefix: str = TEST_SESSION_PREFIX) -> str:
    """
    Faker to create a session name that doesn't exist.

    Parameters
    ----------
    server : :class:`libtmux.Server`
        libtmux server
    prefix : str
        prefix for sessions (e.g. ``libtmux_``). Defaults to
        ``TEST_SESSION_PREFIX``.

    Returns
    -------
    str
        Random session name guaranteed to not collide with current ones.

    Examples
    --------
    >>> get_test_session_name(server=server)
    'libtmux_...'

    Never the same twice:
    >>> get_test_session_name(server=server) != get_test_session_name(server=server)
    True
    """
    while True:
        session_name = prefix + next(namer)
        if not server.has_session(session_name):
            break
    return session_name


def get_test_window_name(
    session: "Session",
    prefix: t.Optional[str] = TEST_SESSION_PREFIX,
) -> str:
    """
    Faker to create a window name that doesn't exist.

    Parameters
    ----------
    session : :class:`libtmux.Session`
        libtmux session
    prefix : str
        prefix for windows (e.g. ``libtmux_``). Defaults to
        ``TEST_SESSION_PREFIX``.

        ATM we reuse the test session prefix here.

    Returns
    -------
    str
        Random window name guaranteed to not collide with current ones.

    Examples
    --------
    >>> get_test_window_name(session=session)
    'libtmux_...'

    Never the same twice:
    >>> get_test_window_name(session=session) != get_test_window_name(session=session)
    True
    """
    assert prefix is not None
    while True:
        window_name = prefix + next(namer)
        if len(session.windows.filter(window_name=window_name)) == 0:
            break
    return window_name


@contextlib.contextmanager
def temp_session(
    server: Server,
    *args: t.Any,
    **kwargs: t.Any,
) -> t.Generator["Session", t.Any, t.Any]:
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
    session: "Session",
    *args: t.Any,
    **kwargs: t.Any,
) -> t.Generator["Window", t.Any, t.Any]:
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
    if "window_name" not in kwargs:
        window_name = get_test_window_name(session)
    else:
        window_name = kwargs.pop("window_name")

    window = session.new_window(window_name, *args, **kwargs)

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


class EnvironmentVarGuard:
    """Mock environmental variables safely.

    Helps rotect the environment variable properly.  Can be used as context
    manager.

    Notes
    -----
    Vendorized to fix issue with Anaconda Python 2 not including test module,
    see #121 [1]_

    References
    ----------
    .. [1] Just installed, "ImportError: cannot import name test_support".
       GitHub issue for tmuxp. https://github.com/tmux-python/tmuxp/issues/121.
       Created October 12th, 2015. Accessed April 7th, 2018.
    """

    def __init__(self) -> None:
        self._environ = os.environ
        self._unset: t.Set[str] = set()
        self._reset: t.Dict[str, str] = {}

    def set(self, envvar: str, value: str) -> None:
        """Set environment variable."""
        if envvar not in self._environ:
            self._unset.add(envvar)
        else:
            self._reset[envvar] = self._environ[envvar]
        self._environ[envvar] = value

    def unset(self, envvar: str) -> None:
        """Unset environment variable."""
        if envvar in self._environ:
            self._reset[envvar] = self._environ[envvar]
            del self._environ[envvar]

    def __enter__(self) -> "EnvironmentVarGuard":
        """Return context for for context manager."""
        return self

    def __exit__(
        self,
        exc_type: t.Union[t.Type[BaseException], None],
        exc_value: t.Optional[BaseException],
        exc_tb: t.Optional[types.TracebackType],
    ) -> None:
        """Cleanup to run after context manager finishes."""
        for envvar, value in self._reset.items():
            self._environ[envvar] = value
        for unset in self._unset:
            del self._environ[unset]
