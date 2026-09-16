"""Bound a command with a timeout, and verify state instead of assuming it.

send_keys() returns as soon as the keys are sent, not once the shell has
acted on them, and a slow or hung command has no default deadline of its
own. This example gives one call an explicit timeout and catches
:exc:`~libtmux.exc.TmuxTimeout`, then checks a pane's decoded
:attr:`~libtmux.Pane.is_dead` instead of assuming a command completed
because nothing raised.

Run it as shown, with tmux on ``PATH``::

    $ python examples/resilient_automation.py
"""

from __future__ import annotations

from libtmux import exc
from libtmux.server import Server
from libtmux.test.retry import retry_until


def main() -> None:
    """Bound one call with a timeout and confirm pane state afterward."""
    with Server.owned() as server:
        # A plain POSIX shell reaches its prompt immediately, so markers show
        # up without waiting on a login shell's own startup.
        session = server.new_session(session_name="resilient", window_command="sh")
        pane = session.active_pane
        assert pane is not None

        # A per-call timeout only bounds this one command; the server and
        # every other call remain unbounded unless Server(timeout=...) sets
        # a default for all of them.
        try:
            server.cmd("wait-for", "a-signal-nobody-sends", timeout=0.5)
        except exc.TmuxTimeout as e:
            print(f"bounded call timed out as expected: {e}")

        # Whether or not that timed out, the pane itself was never touched --
        # verify that locally rather than assuming it from the exception.
        pane.refresh()
        print(f"pane still running: {pane.is_dead is False}")

        # A command that does complete: send it, then poll for its own
        # completion marker rather than trusting that it already ran.
        pane.send_keys("echo automation-marker-done")
        retry_until(
            lambda: any(
                line.rstrip(" ") == "automation-marker-done"
                for line in pane.capture_pane()
            ),
            raises=True,
        )
        print("marker observed: command completed")


if __name__ == "__main__":
    main()
