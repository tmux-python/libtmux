"""Own a private daemon, or just one session on a server you already run.

:meth:`~libtmux.Server.owned` creates a private socket for the block and
kills that daemon on exit -- nothing else on the machine can be listening on
it. :meth:`~libtmux.Server.owned_session` instead creates one session on a
``Server`` you already hold and kills only that session, leaving the rest of
the daemon (and any other sessions on it) alone.

Run it as shown, with tmux on ``PATH``::

    $ python examples/owned_scopes.py
"""

from __future__ import annotations

from libtmux.server import Server


def main() -> None:
    """Contrast a private daemon scope with a single-session scope."""
    with Server.owned() as server:
        # tmux itself only starts once the first session exists.
        server.new_session(session_name="starts-the-daemon")
        print(f"private daemon alive once a session exists: {server.is_alive()}")

        with server.owned_session("build") as build_session:
            print(f"session name: {build_session.session_name!r}")
            print(f"session exists during its block: {server.has_session('build')}")

        print(f"'build' cleaned up on exit: {not server.has_session('build')}")
        print(
            f"daemon still up -- owned_session killed only 'build': {server.is_alive()}"
        )

    # Server.owned()'s own cleanup already ran by here: the daemon is killed
    # and its socket directory removed.
    print(f"private daemon killed: {not server.is_alive()}")


if __name__ == "__main__":
    main()
