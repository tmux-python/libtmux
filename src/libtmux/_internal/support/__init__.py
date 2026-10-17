"""tmux version and feature support inside libtmux.

Here "support" means which tmux releases and features libtmux works with, not
helper code. libtmux checks the connected daemon's version, not the client
executable's, before every command. A program built on libtmux that dispatches
its own tmux subprocesses can reuse that check:

- :func:`server_version` reads the release a :class:`~libtmux.Server` talks to.
- :func:`require_version` and :func:`is_at_least` compare reports with a floor.
- :func:`check_fence` turns the replaced-daemon marker of a fenced batch into
  :exc:`~libtmux.exc.VersionTooLow`.

Examples
--------
>>> from libtmux._internal import support
>>> support.MINIMUM
'3.3a'
>>> support.is_at_least("3.4-rc", "3.3a")
True
>>> support.is_at_least("3.3", "3.3a")
False
>>> support.server_version(server) == server._get_version()
True
"""

from __future__ import annotations

import typing as t

from libtmux._internal.support.versions import (
    MINIMUM,
    check_result,
    is_at_least,
    require_version,
)
from libtmux.exc import VersionTooLow

if t.TYPE_CHECKING:
    from libtmux.server import Server

__all__ = (
    "MINIMUM",
    "VersionTooLow",
    "check_fence",
    "is_at_least",
    "require_version",
    "server_version",
)


def server_version(server: Server) -> str:
    """Return the tmux release *server* talks to, refusing an unsupported one.

    The release is read from the endpoint on every call, never from what
    *server* checked earlier, so a daemon replaced since then is reported as
    it is now. A live daemon answers with its own release; an absent endpoint
    answers with the configured executable's. Either must meet
    :data:`MINIMUM`.

    Raises
    ------
    :exc:`~libtmux.exc.VersionTooLow`
        When the release is below the minimum or cannot be established.
    """
    server._version_cache.clear()
    return server._get_version()


def check_fence(stderr: str, marker: str | None, server: Server | None = None) -> None:
    """Raise :exc:`~libtmux.exc.VersionTooLow` if a fenced batch was refused.

    A batch prefixed with ``if-shell -F '#{==:#{version},<V>}' '' <marker> ;``
    reports ``unknown command: <marker>`` on stderr when the daemon is not the
    release the caller checked, and none of its commands ran. Pass *server*
    so its next command reads the replacement daemon's release afresh.
    """
    try:
        check_result(stderr, marker)
    except VersionTooLow:
        if server is not None:
            server._version_cache.clear()
        raise
