"""Deterministic shell preset for tests that read a pane's screen."""

from __future__ import annotations

import os
import shlex
import typing as t

#: Prompt of the deterministic shell.
DETERMINISTIC_PS1 = "$ "

#: ``TERM`` of the deterministic shell.
DETERMINISTIC_TERM = "xterm-256color"


def deterministic_shell_command(
    *,
    ps1: str = DETERMINISTIC_PS1,
    term: str = DETERMINISTIC_TERM,
    inherit: t.Iterable[str] = ("PATH",),
) -> str:
    """Return a command that starts a bash shell with a fixed screen.

    The shell runs with an empty environment apart from ``PS1``, ``TERM`` and
    the ``inherit`` variables, and reads no startup file, so the prompt, the
    terminal type and the environment do not depend on the machine running the
    test. ``TMUX`` and ``TMUX_PANE`` are not inherited either.

    Pass the result to ``window_command`` of
    :meth:`Server.new_session() <libtmux.Server.new_session>`, or to the shell
    argument of ``new_window()`` and ``split()``. Requires ``bash`` on the
    ``PATH`` of the process that runs the command.

    Parameters
    ----------
    ps1 : str
        Primary prompt. Defaults to ``"$ "``.
    term : str
        ``TERM`` value. Defaults to ``"xterm-256color"``.
    inherit : iterable of str
        Names of variables copied from the calling environment. Defaults to
        ``("PATH",)`` so programs under test stay reachable; pass ``()`` for a
        fully empty environment. Names that are unset are skipped.

    Examples
    --------
    >>> deterministic_shell_command(inherit=())
    "env -i 'PS1=$ ' TERM=xterm-256color bash --norc --noprofile"

    >>> from libtmux.test.retry import retry_until
    >>> clean = server.new_session(
    ...     session_name="clean",
    ...     window_command=deterministic_shell_command(),
    ... )
    >>> pane = clean.active_pane
    >>> pane.send_keys("printenv TERM", enter=True)
    >>> retry_until(lambda: "xterm-256color" in pane.capture_pane())
    True
    """
    env = [f"PS1={ps1}", f"TERM={term}"]
    env += [f"{name}={os.environ[name]}" for name in inherit if name in os.environ]
    return shlex.join(["env", "-i", *env, "bash", "--norc", "--noprofile"])
