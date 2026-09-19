"""Notice a new window without a subscription API -- libtmux has none.

libtmux has no event stream: nothing calls you back when a window opens or a
pane's process exits. ``Session.windows`` re-queries tmux on every access, so
polling it is the supported way to notice a change -- ``retry_until()`` is a
small wrapper around exactly that loop. See docs/topics/public-vs-internal.md
for why this is the answer rather than the internal ``ControlMode`` test
client.

Run it as shown, with tmux on ``PATH``::

    $ python examples/polling_for_changes.py
"""

from __future__ import annotations

import threading

from libtmux.server import Server
from libtmux.session import Session
from libtmux.test.retry import retry_until


def open_a_window_soon(session: Session) -> None:
    """Simulate another process changing the session, from a thread."""
    session.new_window(window_name="opened-elsewhere")


def main() -> None:
    """Poll a session's windows until one appears from elsewhere."""
    with Server.owned() as server:
        session = server.new_session(session_name="watcher")
        starting_count = len(session.windows)

        threading.Timer(0.3, open_a_window_soon, args=(session,)).start()

        def window_was_added() -> bool:
            return len(session.windows) > starting_count

        retry_until(window_was_added, raises=True)

        names = [w.window_name for w in session.windows]
        print(f"windows now: {names}")


if __name__ == "__main__":
    main()
