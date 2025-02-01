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
    """Generate random string values (8 chars each) from a given character set.

    Examples
    --------
    >>> rng = RandomStrSequence()  # pragma: no cover
    >>> next(rng)  # pragma: no cover
    '...'
    >>> len(next(rng))  # pragma: no cover
    8
    >>> type(next(rng))  # pragma: no cover
    <class 'str'>
    """

    def __init__(
        self,
        characters: str = "abcdefghijklmnopqrstuvwxyz0123456789_",
    ) -> None:
        self.characters: str = characters

    def __iter__(self) -> RandomStrSequence:
        """Return self as iterator."""
        return self

    def __next__(self) -> str:
        """Return next random 8-character string."""
        return "".join(random.sample(self.characters, k=8))


namer = RandomStrSequence()


def get_test_session_name(server: Server, prefix: str = TEST_SESSION_PREFIX) -> str:
    """Generate a unique session name that does not exist on the server.

    Parameters
    ----------
    server : Server
        The tmux server instance.
    prefix : str
        Prefix for the generated session name. Defaults to 'libtmux_'.

    Returns
    -------
    str
        Random session name guaranteed not to collide with existing sessions.

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
    Generate a unique window name that does not exist in the given session.

    Parameters
    ----------
    session : Session
        The tmux session instance.
    prefix : str, optional
        Prefix for the generated window name. Defaults to 'libtmux_'.

    Returns
    -------
    str
        Random window name guaranteed not to collide with existing windows.

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
