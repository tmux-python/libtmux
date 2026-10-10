"""Run tmux commands directly with run_command() and CommandResult.

:func:`~libtmux.common.run_command` executes tmux without an object hierarchy
in the way. Reach for it for one-off queries and diagnostics; reach for
``Server``/``Session``/``Window``/``Pane`` for anything you traverse or hold
onto.

Run it as shown, with tmux on ``PATH``::

    $ python examples/command_results.py
"""

from __future__ import annotations

from libtmux.common import CommandResult, run_command


def main() -> None:
    """Run a command with run_command() and inspect the CommandResult."""
    result: CommandResult = run_command("-V")

    print(f"cmd: {result.cmd}")
    print(f"returncode: {result.returncode}")
    print(f"stdout: {result.stdout}")

    # A nonzero exit is still just data on the result, not an exception --
    # useful for probing whether a subcommand exists on this tmux version.
    # -L names a socket that cannot already exist, so "no server running"
    # is deterministic here regardless of whether the reader happens to
    # have their own default-socket tmux running -- run_command() takes no
    # socket by default, and probing without one would reach for it.
    probe = run_command(
        "-L",
        "libtmux-examples-command-results-no-such-server",
        "has-session",
        "-t",
        "definitely-not-a-real-session",
    )
    print(f"probe returncode: {probe.returncode}")
    print(f"probe stderr: {probe.stderr}")


if __name__ == "__main__":
    main()
