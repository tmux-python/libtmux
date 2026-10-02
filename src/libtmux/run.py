"""Run a shell command in a pane and report how it ended.

The public entry point is :meth:`libtmux.Pane.run`; this module holds the
result type and the private mechanism behind it.

Mechanism, in order:

1. The pane's shell is sent one line. The line signals a *started* channel,
   prints a begin marker, runs the command, stores ``$?`` in a pane user
   option, prints an end marker, and signals a *done* channel.
2. :meth:`Server.wait_for() <libtmux.Server.wait_for>` waits for *started*
   under a short bound, then for *done* under the caller's.
3. The option and the pane's text are read back.

The markers are assembled by ``printf`` from two words, so the echoed command
line never contains them: only the shell's output does.

The command runs through ``eval`` on a single-quoted string. The typed line is
therefore always well formed, so a syntax error or an unterminated quote in the
command is the shell's error and a nonzero status, not a half-typed line that
leaves the waiter blocked. A ``trap`` on ``INT`` keeps the line alive when the
command is interrupted (the status is 130).
"""

from __future__ import annotations

import dataclasses
import logging
import shlex
import shutil
import time
import typing as t
import uuid

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.server import Server

logger = logging.getLogger(__name__)

#: Seconds the pane's shell has to acknowledge the line before the call fails.
#: A pane busy with another program, or a shell that cannot reach this tmux
#: server, never acknowledges.
_START_TIMEOUT = 5.0

#: Hooks that fire when a pane's process ends: ``pane-exited`` when tmux closes
#: the pane, ``pane-died`` when ``remain-on-exit`` keeps it as a dead pane.
_GONE_HOOKS = ("pane-exited", "pane-died")

_BEGIN = "LTRUN_B_"
_END = "LTRUN_E_"


@dataclasses.dataclass(frozen=True)
class PaneRunResult:
    """What :meth:`libtmux.Pane.run` reports for a command that finished.

    Modelled on :class:`subprocess.CompletedProcess`.

    Attributes
    ----------
    args : str
        The command as passed to :meth:`~libtmux.Pane.run`.
    returncode : int
        The shell's ``$?`` after the command. A syntax error in the command
        is the shell's own nonzero status; an interrupt is 130.
    stdout : list of str
        Lines the command printed between the markers. The pane's terminal
        carries stdout and stderr together, so both are here.
    truncated : bool
        True when the begin marker had already left the pane's history, so
        *stdout* starts at the oldest line tmux still holds.
    """

    args: str
    returncode: int
    stdout: list[str]
    truncated: bool = False


def _tmux_prefix(server: Server) -> list[str]:
    """Return the tmux binary and the flags a pane's shell needs to reach *server*."""
    argv = [server.tmux_bin or shutil.which("tmux") or "tmux"]
    if server.socket_name:
        argv.append(f"-L{server.socket_name}")
    if server.socket_path:
        argv.append(f"-S{server.socket_path}")
    return argv


def _build_line(
    command: str,
    *,
    tmux: str,
    pane_id: str,
    token: str,
    started: str,
    done: str,
    option: str,
) -> str:
    r"""Return the shell line that runs *command* and reports back.

    The line begins with a space, which bash (``ignorespace``) and zsh
    (``hist_ignore_space``) keep out of history when configured to, and ends
    by deleting its own history entry in bash. dash keeps no history. zsh
    offers no way to delete an entry from inside the line.

    Examples
    --------
    >>> line = _build_line(
    ...     "true", tmux="tmux", pane_id="%1", token="T",
    ...     started="s", done="d", option="@o",
    ... )
    >>> line.startswith(" printf '%s%s\\n' LTRUN_B_ T; tmux wait-for -S s; ")
    True
    >>> line.endswith("tmux wait-for -S d")
    True
    >>> "eval \"$_lt_c\"" in line
    True
    """
    return (
        f" printf '%s%s\\n' {_BEGIN} {token}; {tmux} wait-for -S {started}; "
        f"_lt_c={shlex.quote(command)}; trap : INT; "
        'if [ -n "$ZSH_VERSION" ]; then eval "$_lt_c"; '
        'else command eval "$_lt_c"; fi; '
        f'{tmux} set-option -p -t {pane_id} {option} "$?"; trap - INT; '
        f"unset _lt_c; printf '%s%s\\n' {_END} {token}; "
        '[ -n "$BASH_VERSION" ] && history -d $HISTCMD 2>/dev/null; '
        f"{tmux} wait-for -S {done}"
    )


def _extract(lines: list[str], token: str) -> tuple[list[str], bool, bool]:
    """Return ``(output, ended, truncated)`` from a capture of the pane.

    Lines are matched whole (begin) or by suffix (end), never by substring, so
    the echoed command cannot match. The suffix match keeps output that has no
    trailing newline. Trailing blanks are dropped from every line: tmux 3.2a
    pads joined lines to the pane width, later versions do not.

    Examples
    --------
    >>> _extract(["$ x", "LTRUN_B_T", "a", "b", "LTRUN_E_T", "$"], "T")
    (['a', 'b'], True, False)

    >>> _extract(["LTRUN_B_T", "tail" + "LTRUN_E_T"], "T")
    (['tail'], True, False)

    >>> _extract(["LTRUN_B_T", "a", "", ""], "T")
    (['a'], False, False)

    >>> _extract(["LTRUN_B_T   ", "a   ", "LTRUN_E_T  "], "T")
    (['a'], True, False)

    >>> _extract(["gone", "b", "LTRUN_E_T"], "T")
    (['gone', 'b'], True, True)
    """
    lines = [line.rstrip() for line in lines]
    begin, end = f"{_BEGIN}{token}", f"{_END}{token}"
    start = max((i for i, line in enumerate(lines) if line == begin), default=None)
    body = lines if start is None else lines[start + 1 :]
    for i, line in enumerate(body):
        if line.endswith(end):
            head = line[: -len(end)]
            return (body[:i] + ([head] if head else []), True, start is None)
    while body and not body[-1]:
        body = body[:-1]
    return (body, False, start is None)


def _lost(pane: Pane) -> exc.LibTmuxException:
    """Return the error for a pane that cannot be read back."""
    if not pane.server.is_alive():
        return exc.TmuxServerGone(str(pane.pane_id))
    return exc.PaneNotFound(pane.pane_id)


def _pane_alive(pane: Pane) -> bool:
    """Return True when the server lists *pane* and its process is running."""
    proc = pane.server.cmd("list-panes", "-a", "-F", "#{pane_id} #{pane_dead}")
    return proc.returncode == 0 and f"{pane.pane_id} 0" in proc.stdout


def _install_gone_hooks(server: Server, pane_id: str, done: str, index: int) -> None:
    """Make the pane's disappearance signal *done*, so its waiter wakes at once.

    The hooks are server-wide and filter on ``#{hook_pane}``, because a hook set
    on the pane or its window dies with them before it can fire on tmux 3.2a
    through 3.7c. Each sits at its own array *index*, so a hook the caller
    already has is untouched.
    """
    action = f"if-shell -F '#{{==:#{{hook_pane}},{pane_id}}}' 'wait-for -S {done}'"
    for name in _GONE_HOOKS:
        proc = server.cmd("set-hook", "-g", f"{name}[{index}]", action)
        if proc.stderr:
            logger.warning(
                "could not install %s hook; a closed pane is reported at timeout",
                name,
                extra={"tmux_stderr": proc.stderr},
            )


def _remove_gone_hooks(server: Server, index: int) -> None:
    """Remove the hooks :func:`_install_gone_hooks` set."""
    for name in _GONE_HOOKS:
        server.cmd("set-hook", "-ug", f"{name}[{index}]")


def _run(
    pane: Pane,
    command: str,
    *,
    timeout: float,
) -> PaneRunResult:
    """Implement :meth:`libtmux.Pane.run`."""
    if timeout <= 0:
        msg = f"timeout must be positive, got {timeout}"
        raise ValueError(msg)
    pane_id = pane.pane_id
    assert pane_id is not None
    server = pane.server
    token = uuid.uuid4().hex[:16]
    started = f"libtmux-run-{token}-started"
    done = f"libtmux-run-{token}"
    option = f"@libtmux_run_{token}"
    deadline = time.monotonic() + timeout

    index = 7000 + int(token[:5], 16) % 90000
    _install_gone_hooks(server, pane_id, done, index)
    try:
        pane.send_keys(
            _build_line(
                command,
                tmux=shlex.join(_tmux_prefix(server)),
                pane_id=pane_id,
                token=token,
                started=started,
                done=done,
                option=option,
            ),
            literal=True,
        )

        failure: exc.TmuxTimeout | None = None
        did_start = True
        try:
            server.wait_for(started, timeout=_START_TIMEOUT)
        except exc.TmuxTimeout as err:
            failure, did_start = err, False
        else:
            try:
                server.wait_for(done, timeout=max(deadline - time.monotonic(), 0.001))
            except exc.TmuxTimeout as err:
                failure = err

        try:
            status = pane.cmd("show-options", "-pqv", option)
            lines = pane.capture_pane(start="-", join_wrapped=True)
        finally:
            pane.cmd("set-option", "-pu", option)
    finally:
        _remove_gone_hooks(server, index)

    output, ended, truncated = _extract(lines, token)
    if not status.stdout or not ended:
        if not _pane_alive(pane):
            raise _lost(pane)
        if failure is not None:
            raise exc.PaneRunTimeout(
                command,
                timeout if did_start else failure.timeout,
                output,
                cmd=failure.cmd,
                started=did_start,
            ) from failure
        raise _lost(pane)
    return PaneRunResult(
        args=command,
        returncode=int(status.stdout[0]),
        stdout=output,
        truncated=truncated,
    )
