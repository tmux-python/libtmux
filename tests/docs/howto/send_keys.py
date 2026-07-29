"""Sidecar for ``docs/howto/send-keys.md``.

The page makes three claims a reader has to be able to trust: that a whole-line
wait really does see the shell's answer, that ``literal=True`` is what stops
tmux reading typed text as a key name, and that ``suppress_history`` only hides
a command in a shell configured to ignore space-prefixed lines.

The first is checked from the page's own printed verdicts — strictly, because a
containment test on ``capture_pane`` output matches the command tmux echoed
onto the pane and would pass in a world where no shell ever ran. The other two
are checked against the *opposite* configuration, in throwaway panes of this
module's own: text sent without ``literal=True`` has to actually execute, and a
suppressed command has to land in the history of a bash that was never told to
ignore it. Claims about what a flag protects you from are worth nothing until
the unprotected case has been watched failing.
"""

from __future__ import annotations

import typing as t

from libtmux.server import Server
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.window import Window
    from tests.docs.howto_harness import HowtoContext

SOCKET_NAME = "libtmux-howto"

#: A bash that reads no start-up file, so its history behaviour is the
#: documented default rather than whatever the machine running this configured.
BARE_BASH = "bash --norc --noprofile"


def has_line(pane: Pane, line: str) -> bool:
    """Report whether a captured line is exactly ``line``.

    Parameters
    ----------
    pane : libtmux.Pane
        Pane to read.
    line : str
        Expected line, compared whole rather than by containment.

    Returns
    -------
    bool
        True when the pane's visible screen holds that line.
    """
    return any(row.strip() == line for row in pane.capture_pane())


def history_entries(pane: Pane) -> list[str]:
    """Return the commands listed by bash's ``history`` builtin.

    Mirrors the page's own parsing: a listing row is a number, two spaces, and
    the command as it was recorded.

    Parameters
    ----------
    pane : libtmux.Pane
        Pane showing a ``history`` listing.

    Returns
    -------
    list of str
        One entry per numbered row on the visible screen.
    """
    entries = []
    for row in pane.capture_pane():
        number, _, command = row.strip().partition("  ")
        if number.isdigit():
            entries.append(command.strip())
    return entries


def check_1(ctx: HowtoContext) -> None:
    """Confirm the pane answers, and that the page's wait sees it.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert server.socket_name == SOCKET_NAME

    pane = ctx.namespace["pane"]
    assert ctx.output[1].strip() == "True", (
        f"block 1 printed {ctx.output[1]!r}: its wait gave up before the "
        f"shell answered, so the page teaches a wait that does not work"
    )
    assert has_line(pane, f"hello from {pane.pane_id}")


def check_2(ctx: HowtoContext) -> None:
    """``literal=True`` types the word, and dropping it presses the key.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    pane = ctx.namespace["pane"]
    message = (
        "the pane never printed 'Enter' on its own line, so the staged text "
        "was not typed as five characters — tmux resolved it as a key instead"
    )
    assert ctx.output[2].strip() == "True", message
    assert has_line(pane, "Enter"), message

    window: Window = ctx.namespace["window"]
    probe = window.split(shell=BARE_BASH)
    try:
        probe.send_keys("echo interpreted", enter=False)
        probe.send_keys("Enter", enter=False)
        retry_until(lambda: has_line(probe, "interpreted"))
    finally:
        probe.kill()


def check_3(ctx: HowtoContext) -> None:
    """Confirm the suppression holds here, and fails without the option.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    reported = dict(
        line.split(": ") for line in ctx.output[3].strip().splitlines() if line
    )
    assert reported == {"public recorded": "True", "private recorded": "False"}, (
        f"block 3 reported {reported}: with HISTCONTROL=ignorespace set, bash "
        f"should record the plain command and drop the suppressed one"
    )

    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert "send-keys" not in [session.session_name for session in server.sessions]

    unconfigured = server.new_session(session_name="howto-history", kill_session=True)
    try:
        pane = unconfigured.active_window.split(shell=BARE_BASH)
        pane.send_keys("echo private", suppress_history=True)
        pane.send_keys("history")
        retry_until(lambda: "history" in history_entries(pane))
        assert "echo private" in history_entries(pane), (
            "a shell without HISTCONTROL=ignorespace kept no record of the "
            "suppressed command, so the page's caveat overstates the risk"
        )
    finally:
        unconfigured.kill()
