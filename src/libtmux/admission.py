"""Version admission for programs built on libtmux.

libtmux admits the connected daemon, not the client executable, before every
command. A program that dispatches its own tmux subprocesses can reuse that
decision without depending on libtmux's internal modules:

- :func:`admitted_version` reads the release a :class:`~libtmux.Server` talks to.
- :func:`require_version` and :func:`is_at_least` compare reports with a floor.
- :func:`require_commands` refuses literal commands that an admitted release
  cannot run safely, such as named-buffer deletion before 3.4.
- :func:`check_fence` turns the replaced-daemon marker of a fenced batch into
  :exc:`~libtmux.exc.VersionTooLow`.

Examples
--------
>>> from libtmux import admission
>>> admission.MINIMUM
'3.3a'
>>> admission.is_at_least("3.4-rc", "3.3a")
True
>>> admission.is_at_least("3.3", "3.3a")
False
>>> admission.admitted_version(server) == server._get_version()
True
>>> admission.require_commands("3.3a", ["list-sessions"])
"""

from __future__ import annotations

import typing as t

from libtmux._internal.support import (
    MINIMUM,
    _require_commands,
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
    "admitted_version",
    "check_fence",
    "is_at_least",
    "require_commands",
    "require_version",
)


def admitted_version(server: Server) -> str:
    """Return the tmux release *server* talks to, refusing an unsupported one.

    A live daemon answers with its own release; an absent endpoint answers
    with the configured executable's. Either must meet :data:`MINIMUM`.

    Raises
    ------
    :exc:`~libtmux.exc.VersionTooLow`
        When the release is below the minimum or cannot be established.
    """
    return server._get_version()


def check_fence(stderr: str, marker: str | None) -> None:
    """Raise :exc:`~libtmux.exc.VersionTooLow` if a fenced batch was refused.

    A batch prefixed with ``if-shell -F '#{==:#{version},<V>}' '' <marker> ;``
    reports ``unknown command: <marker>`` on stderr when the daemon is not the
    release the caller admitted, and none of its commands ran.
    """
    check_result(stderr, marker)


def require_commands(
    version: str, arguments: list[str], *, repaired_break: bool = False
) -> None:
    """Refuse literal tmux commands that *version* cannot run safely.

    *arguments* is the argv after any global options, with ``;`` ending each
    command as tmux reads it. Raises :exc:`~libtmux.exc.VersionTooLow` for a
    command whose feature needs a newer release (exact named-buffer deletion
    and rename before 3.4, ``split-window -p`` on 3.4, raw ``break-pane`` on
    3.7 unless *repaired_break* says the caller names the window), and
    :exc:`~libtmux.exc.InvalidLayout` for a layout 3.3a would mishandle.
    """
    _require_commands(version, arguments, repaired_break=repaired_break)
