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
line never contains them: only the shell's output does. The begin marker is
preceded by a newline so it always owns its row. A shell that never leaves
cooked mode (dash) lets the tty echo a line typed before its first prompt, and
the prompt then shares a row with whatever the line prints first; without the
newline the begin marker would be ``$ LTRUN_B_...``, match nothing, and the
echoed line would be returned as output.

The command runs through ``eval`` on a single-quoted string. The typed line is
therefore always well formed, so a syntax error or an unterminated quote in the
command is the shell's error and a nonzero status, not a half-typed line that
leaves the waiter blocked. A ``trap`` on ``INT`` keeps the line alive when the
command is interrupted (the status is 130).
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import shlex
import shutil
import threading
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

#: Per-pane locks, keyed by server socket and pane id, with a count of the calls
#: that hold or wait on each so an entry leaves the table with its last call.
_DRIVE_LOCKS: dict[tuple[str | None, str | None, str], list[t.Any]] = {}
_DRIVE_LOCKS_GUARD = threading.Lock()

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
    >>> line.startswith(" printf '\\n%s%s\\n' LTRUN_B_ T; tmux wait-for -S s; ")
    True
    >>> "\\; wait-for -S d" in line
    True
    >>> "eval \"$_lt_c\"" in line
    True
    """
    return (
        f" printf '\\n%s%s\\n' {_BEGIN} {token}; {tmux} wait-for -S {started}; "
        f"_lt_c={shlex.quote(command)}; trap : INT; "
        'if [ -n "$ZSH_VERSION" ]; then eval "$_lt_c"; '
        'else command eval "$_lt_c"; fi; '
        "_lt_s=$?; trap - INT; unset _lt_c; "
        f"printf '%s%s\\n' {_END} {token}; "
        '[ -n "$BASH_VERSION" ] && history -d $HISTCMD 2>/dev/null; '
        f'{tmux} set-option -p -t {pane_id} {option} "$_lt_s" \\; wait-for -S {done}; '
        "unset _lt_s"
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


def _lock_key(server: Server, pane_id: str) -> tuple[str | None, str | None, str]:
    """Return the drive-lock key: the server's socket, then the pane id."""
    path = server.socket_path
    return (server.socket_name, None if path is None else str(path), pane_id)


@contextlib.contextmanager
def _drive_lock(
    server: Server,
    pane_id: str,
    command: str,
    timeout: float,
) -> t.Iterator[None]:
    """Hold the pane's drive lock, so one call at a time types into it.

    A pane has one input stream and one screen. Two calls typing into it at
    once interleave their lines and read each other's markers, and neither
    notices. The lock is process-local and keyed by the server's socket and the
    pane id, so two :class:`~libtmux.Server` objects for one socket share it
    and calls on different panes do not wait on each other.

    Parameters
    ----------
    server : :class:`~libtmux.Server`
        The server that owns the pane.
    pane_id : str
        The pane's id.
    command : str
        The command waiting for the lock, reported if the wait expires.
    timeout : float
        Seconds the call may spend waiting for the lock.

    Raises
    ------
    :exc:`~libtmux.exc.PaneRunTimeout`
        With ``started=False`` when the lock stayed held for *timeout*. Nothing
        was typed into the pane.

    Examples
    --------
    >>> with _drive_lock(server, "%1", "true", 1.0):
    ...     pass
    >>> _drive_lock_count(server, "%1")
    0
    """
    key = _lock_key(server, pane_id)
    with _DRIVE_LOCKS_GUARD:
        entry = _DRIVE_LOCKS.setdefault(key, [threading.Lock(), 0])
        entry[1] += 1
    lock: threading.Lock = entry[0]
    try:
        if not lock.acquire(timeout=timeout):
            raise exc.PaneRunTimeout(command, timeout, [], cmd=[], started=False)
        try:
            yield
        finally:
            lock.release()
    finally:
        with _DRIVE_LOCKS_GUARD:
            entry[1] -= 1
            if entry[1] == 0:
                del _DRIVE_LOCKS[key]


def _drive_lock_count(server: Server, pane_id: str) -> int:
    """Return how many calls hold or wait on the pane's drive lock."""
    key = _lock_key(server, pane_id)
    with _DRIVE_LOCKS_GUARD:
        return t.cast("int", _DRIVE_LOCKS.get(key, [None, 0])[1])


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
    already has is untouched. Both are set by one chained tmux invocation.
    """
    action = f"if-shell -F '#{{==:#{{hook_pane}},{pane_id}}}' 'wait-for -S {done}'"
    proc = server.cmd(
        *_chain(("set-hook", "-g", f"{n}[{index}]", action) for n in _GONE_HOOKS)
    )
    if proc.stderr:
        logger.warning(
            "could not install pane hooks; a closed pane is reported at timeout",
            extra={"tmux_stderr": proc.stderr},
        )


def _remove_gone_hooks(server: Server, index: int) -> None:
    """Remove the hooks :func:`_install_gone_hooks` set, in one invocation."""
    server.cmd(*_chain(("set-hook", "-ug", f"{n}[{index}]") for n in _GONE_HOOKS))


def _chain(commands: t.Iterable[tuple[str, ...]]) -> list[str]:
    """Join tmux commands into one argv, separated by the ``;`` argument.

    tmux reads an argument that *ends* in ``;`` as a separator, so only a
    lone ``;`` is added here and no command text is touched. Text that may
    itself end in ``;`` would be split, so it must be escaped before it is
    passed in; the lines :func:`_build_line` types never end that way.

    Examples
    --------
    >>> _chain([("a", "-x"), ("b",)])
    ['a', '-x', ';', 'b']
    """
    argv: list[str] = []
    for command in commands:
        if argv:
            argv.append(";")
        argv.extend(command)
    return argv


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
    deadline = time.monotonic() + timeout
    with _drive_lock(pane.server, pane_id, command, timeout):
        return _run_locked(pane, pane_id, command, timeout=timeout, deadline=deadline)


def _run_locked(
    pane: Pane,
    pane_id: str,
    command: str,
    *,
    timeout: float,
    deadline: float,
) -> PaneRunResult:
    """Run *command* in *pane* while holding its drive lock."""
    server = pane.server
    token = uuid.uuid4().hex[:16]
    started = f"libtmux-run-{token}-started"
    done = f"libtmux-run-{token}"
    option = f"@libtmux_run_{token}"

    index = 7000 + int(token[:5], 16) % 90000
    _install_gone_hooks(server, pane_id, done, index)
    try:
        line = _build_line(
            command,
            tmux=shlex.join(_tmux_prefix(server)),
            pane_id=pane_id,
            token=token,
            started=started,
            done=done,
            option=option,
        )
        server.cmd(
            *_chain(
                [
                    ("send-keys", "-t", pane_id, "-l", line),
                    ("send-keys", "-t", pane_id, "Enter"),
                ]
            )
        )

        failure: exc.TmuxTimeout | None = None
        did_start = True
        try:
            server._wait_for_signal(started, _START_TIMEOUT, verify=False)
        except exc.TmuxTimeout as err:
            failure, did_start = err, False
        else:
            try:
                server._wait_for_signal(
                    done, max(deadline - time.monotonic(), 0.001), verify=False
                )
            except exc.TmuxTimeout as err:
                failure = err

        sep = f"LTRUN_S_{token}"
        proc = server.cmd(
            *_chain(
                [
                    ("show-options", "-t", pane_id, "-pqv", option),
                    ("display-message", "-p", sep),
                    ("capture-pane", "-t", pane_id, "-p", "-S", "-", "-J"),
                    ("set-option", "-t", pane_id, "-pu", option),
                ]
            )
        )
        split = proc.stdout.index(sep) if sep in proc.stdout else 0
        status = proc.stdout[:split]
        lines = proc.stdout[split + 1 :] if sep in proc.stdout else []
    finally:
        _remove_gone_hooks(server, index)

    output, ended, truncated = _extract(lines, token)
    if not status or not ended:
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
        returncode=int(status[0]),
        stdout=output,
        truncated=truncated,
    )
