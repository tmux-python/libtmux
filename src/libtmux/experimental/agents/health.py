"""Is the process behind a pane still alive.

Local panes carry a ``pane_pid`` we can probe with ``os.kill(pid, 0)``. Remote
(SSH) panes are PID-less; this check never declares them dead — they expire on a
keepalive TTL owned by the monitor instead.
"""

from __future__ import annotations

import os


def is_alive(pid: int | None) -> bool:
    """Return whether *pid* is a live process (``None`` → always alive).

    Examples
    --------
    >>> import os
    >>> is_alive(os.getpid())
    True
    >>> is_alive(None)
    True
    """
    if pid is None:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True
