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

import collections
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
from libtmux.engines.base import CommandSeparator

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


class PaneRunCancel:
    """Cancel :meth:`Pane.run() <libtmux.Pane.run>` from another thread.

    A thread blocked in ``run`` cannot be interrupted from outside: cancelling
    the :mod:`asyncio` task around :func:`asyncio.to_thread` abandons the
    result but leaves the thread, its tmux waiter and the pane's lock in place
    until the command ends or ``timeout`` expires. Pass one of these as
    ``cancel`` and call :meth:`cancel` instead; the call wakes at once,
    releases its waiter, and raises :exc:`~libtmux.exc.PaneRunCancelled`.

    The command is not interrupted. It is the same contract as ``timeout``:
    the caller stops waiting, and the command keeps running in the pane.

    One instance may be passed to several calls and cancels all of them. It
    cannot be reused: once cancelled, every later call that receives it
    raises immediately without typing anything.

    Examples
    --------
    >>> import threading
    >>> from libtmux import exc
    >>> from libtmux.run import PaneRunCancel
    >>> cancel = PaneRunCancel()
    >>> cancel.cancelled
    False
    >>> threading.Timer(0.5, cancel.cancel).start()
    >>> try:
    ...     pane.run('echo before; sleep 30', timeout=60, cancel=cancel)
    ... except exc.PaneRunCancelled as e:
    ...     print(e.stdout)
    ['before']
    >>> cancel.cancelled
    True
    >>> pane.send_keys('C-c', enter=False)

    .. versionadded:: 0.63
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._cancelled = False
        self._callbacks: list[t.Callable[[], None]] = []

    @property
    def cancelled(self) -> bool:
        """Whether :meth:`cancel` has been called."""
        return self._cancelled

    def cancel(self) -> None:
        """Cancel every call that holds or waits with this instance.

        Safe from any thread and idempotent.
        """
        with self._guard:
            self._cancelled = True
            callbacks = list(self._callbacks)
        for callback in callbacks:
            callback()

    @contextlib.contextmanager
    def _watching(self, callback: t.Callable[[], None]) -> t.Iterator[None]:
        """Run *callback* when this is cancelled, or now if it already was."""
        with self._guard:
            self._callbacks.append(callback)
            already = self._cancelled
        try:
            if already:
                callback()
            yield
        finally:
            with self._guard:
                self._callbacks.remove(callback)


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


class _Waiter:
    """One call queued for a pane's lock."""

    __slots__ = ("event", "granted")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.granted = False


class _PaneLock:
    """A first-come lock whose waiters a timeout or a cancel can leave."""

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self._held = False
        self._queue: collections.deque[_Waiter] = collections.deque()

    def acquire(self, timeout: float, cancel: PaneRunCancel | None) -> bool:
        """Take the lock; False when *timeout* ran out or *cancel* fired first."""
        with self._mutex:
            if not self._held:
                self._held = True
                return True
            waiter = _Waiter()
            self._queue.append(waiter)
        watch = (
            cancel._watching(waiter.event.set)
            if cancel is not None
            else contextlib.nullcontext()
        )
        with watch:
            waiter.event.wait(timeout)
        with self._mutex:
            if waiter.granted:
                return True
            with contextlib.suppress(ValueError):
                self._queue.remove(waiter)
            return False

    def release(self) -> None:
        """Hand the lock to the next waiter, or free it."""
        with self._mutex:
            if self._queue:
                waiter = self._queue.popleft()
                waiter.granted = True
                waiter.event.set()
            else:
                self._held = False


@contextlib.contextmanager
def _drive_lock(
    server: Server,
    pane_id: str,
    command: str,
    timeout: float,
    cancel: PaneRunCancel | None = None,
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
        The command waiting for the lock, reported if the wait ends early.
    timeout : float
        Seconds the call may spend waiting for the lock.
    cancel : PaneRunCancel, optional
        Leaves the queue when cancelled.

    Raises
    ------
    :exc:`~libtmux.exc.PaneRunTimeout`
        With ``started=False`` when the lock stayed held for *timeout*. Nothing
        was typed into the pane.
    :exc:`~libtmux.exc.PaneRunCancelled`
        With ``started=False`` when *cancel* fired before the lock was taken.

    Examples
    --------
    >>> with _drive_lock(server, "%1", "true", 1.0):
    ...     pass
    >>> _drive_lock_count(server, "%1")
    0
    """
    key = _lock_key(server, pane_id)
    with _DRIVE_LOCKS_GUARD:
        entry = _DRIVE_LOCKS.setdefault(key, [_PaneLock(), 0])
        entry[1] += 1
    lock: _PaneLock = entry[0]
    try:
        if not lock.acquire(timeout, cancel):
            if cancel is not None and cancel.cancelled:
                raise exc.PaneRunCancelled(command, [], started=False)
            raise exc.PaneRunTimeout(command, timeout, [], cmd=[], started=False)
        try:
            if cancel is not None and cancel.cancelled:
                raise exc.PaneRunCancelled(command, [], started=False)
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
    """Join tmux commands into one argv, separated by a ``CommandSeparator``.

    Only the separator is a boundary: the engine escapes a final ``;`` on every
    other argument, so command text is passed through untouched.

    Examples
    --------
    >>> _chain([("a", "-x"), ("b",)])
    ['a', '-x', ';', 'b']
    """
    argv: list[str] = []
    for command in commands:
        if argv:
            argv.append(CommandSeparator(";"))
        argv.extend(command)
    return argv


def _run(
    pane: Pane,
    command: str,
    *,
    timeout: float,
    cancel: PaneRunCancel | None = None,
) -> PaneRunResult:
    """Implement :meth:`libtmux.Pane.run`."""
    if timeout <= 0:
        msg = f"timeout must be positive, got {timeout}"
        raise ValueError(msg)
    pane_id = pane.pane_id
    assert pane_id is not None
    deadline = time.monotonic() + timeout
    with _drive_lock(pane.server, pane_id, command, timeout, cancel):
        return _run_locked(
            pane,
            pane_id,
            command,
            timeout=timeout,
            deadline=deadline,
            cancel=cancel,
        )


def _run_locked(
    pane: Pane,
    pane_id: str,
    command: str,
    *,
    timeout: float,
    deadline: float,
    cancel: PaneRunCancel | None,
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
        pending = [started, done]

        def wake() -> None:
            """Signal what the call still waits on, so a cancel ends the wait."""
            server.cmd(*_chain(("wait-for", "-S", c) for c in list(pending)))

        watch = (
            cancel._watching(wake) if cancel is not None else contextlib.nullcontext()
        )
        try:
            with watch:
                try:
                    server._wait_for_signal(started, _START_TIMEOUT, verify=False)
                except exc.TmuxTimeout as err:
                    failure, did_start = err, False
                else:
                    pending.remove(started)
                    # A cancel wakes this wait too, so it proves no start.
                    did_start = not (cancel is not None and cancel.cancelled)
                    try:
                        server._wait_for_signal(
                            done,
                            max(deadline - time.monotonic(), 0.001),
                            verify=False,
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
        except BaseException:
            # An interrupt or exit in this thread: the waiter is already
            # released; take the status option with us.
            with contextlib.suppress(Exception):
                server.cmd("set-option", "-t", pane_id, "-pu", option)
            raise
        split = proc.stdout.index(sep) if sep in proc.stdout else 0
        status = proc.stdout[:split]
        lines = proc.stdout[split + 1 :] if sep in proc.stdout else []
    finally:
        _remove_gone_hooks(server, index)

    output, ended, truncated = _extract(lines, token)
    if not did_start and truncated:
        # No begin marker was printed, so every row is the pane's own text,
        # the echoed line included, not output of the command.
        output = []
    if cancel is not None and cancel.cancelled:
        raise exc.PaneRunCancelled(command, output, started=did_start)
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
