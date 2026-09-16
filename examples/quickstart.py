"""Server, Session, Window, and Pane, end to end.

Run it as shown, with tmux on ``PATH`` and no existing session required::

    $ python examples/quickstart.py

Uses :meth:`~libtmux.Server.owned` for a private daemon on its own socket,
so this never touches a session you already have open on the default one.
"""

from __future__ import annotations

from libtmux.server import Server
from libtmux.test.retry import retry_until


def main() -> None:
    """Walk the Server -> Session -> Window -> Pane hierarchy."""
    with Server.owned() as server:
        # A plain POSIX shell reaches its prompt immediately, so the marker
        # below shows up without waiting on a login shell's own startup.
        session = server.new_session(
            session_name="quickstart",
            window_name="main",
            window_command="sh",
        )
        window = session.active_window
        pane = window.active_pane
        assert pane is not None

        pane.send_keys("echo hello-from-libtmux")

        # send_keys() returns as soon as the keys are sent, not once the
        # shell has run them -- poll capture_pane() for the marker line
        # rather than assuming it is already there.
        def marker_is_visible() -> bool:
            return any(
                line.rstrip(" ") == "hello-from-libtmux" for line in pane.capture_pane()
            )

        retry_until(marker_is_visible, raises=True)

        print(f"session: {session.session_name!r}")
        print(f"window: {window.window_name!r}")
        print(f"pane output: {pane.capture_pane()[-2:]}")


if __name__ == "__main__":
    main()
