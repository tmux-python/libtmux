"""Random helpers for libtmux and downstream libtmux libraries."""

from __future__ import annotations  # pragma: no cover

import logging
import random
import typing as t  # pragma: no cover

from libtmux.test.constants import (
    TEST_SESSION_PREFIX,
)

if t.TYPE_CHECKING:  # pragma: no cover
    import sys  # pragma: no cover

    from libtmux.server import Server  # pragma: no cover
    from libtmux.session import Session  # pragma: no cover

    if sys.version_info >= (3, 11):  # pragma: no cover
        pass  # pragma: no cover
    else:  # pragma: no cover
        pass  # pragma: no cover


logger = logging.getLogger(__name__)


class RandomStrSequence:
    """Factory to generate random string."""

    def __init__(
        self,
        characters: str = "abcdefghijklmnopqrstuvwxyz0123456789_",
    ) -> None:
        """Create a random letter / number generator. 8 chars in length.

        >>> rng = RandomStrSequence()  # pragma: no cover
        >>> next(rng)  # pragma: no cover
        '...'
        >>> len(next(rng))  # pragma: no cover
        8
        >>> type(next(rng))  # pragma: no cover
        <class 'str'>
        """
        self.characters: str = characters

    def __iter__(self) -> RandomStrSequence:
        """Return self."""
        return self

    def __next__(self) -> str:
        """Return next random string."""
        return "".join(random.sample(self.characters, k=8))


namer = RandomStrSequence()


def get_test_session_name(server: Server, prefix: str = TEST_SESSION_PREFIX) -> str:
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
    >>> get_test_session_name(server=server)  # pragma: no cover
    'libtmux_...'

    Never the same twice:
    >>> name1 = get_test_session_name(server=server)  # pragma: no cover
    >>> name2 = get_test_session_name(server=server)  # pragma: no cover
    >>> name1 != name2  # pragma: no cover
    True
    """
    while True:
        session_name = prefix + next(namer)
        if not server.has_session(session_name):
            break
    return session_name


def get_test_window_name(
    session: Session,
    prefix: str | None = TEST_SESSION_PREFIX,
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
    >>> get_test_window_name(session=session)  # pragma: no cover
    'libtmux_...'

    Never the same twice:
    >>> name1 = get_test_window_name(session=session)  # pragma: no cover
    >>> name2 = get_test_window_name(session=session)  # pragma: no cover
    >>> name1 != name2  # pragma: no cover
    True
    """
    assert prefix is not None
    while True:
        window_name = prefix + next(namer)
        if len(session.windows.filter(window_name=window_name)) == 0:
            break
    return window_name
