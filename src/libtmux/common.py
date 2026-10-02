"""Helper methods and mixins for libtmux.

libtmux.common
~~~~~~~~~~~~~~

"""

from __future__ import annotations

import atexit
import contextlib
import functools
import inspect
import logging
import re
import subprocess
import sys
import threading
import typing as t
import warnings

from . import exc
from ._compat import LooseVersion
from ._internal.redaction import (
    _loggable_cmd,
    redact_env_values as redact_env_values,  # noqa: PLC0414
    redact_send_keys as redact_send_keys,  # noqa: PLC0414
    set_argv_redactor as set_argv_redactor,  # noqa: PLC0414
)
from .engines.base import CommandRequest, SupportsCommandLine
from .engines.subprocess import SubprocessEngine, _kill_and_reap

if t.TYPE_CHECKING:
    from collections.abc import Callable

    from .engines.base import CommandResult, TmuxEngine

logger = logging.getLogger(__name__)


#: Minimum version of tmux required to run libtmux
TMUX_MIN_VERSION = "3.2a"

#: Most recent version of tmux supported
TMUX_MAX_VERSION = "3.7"

SessionDict = dict[str, t.Any]
WindowDict = dict[str, t.Any]
WindowOptionDict = dict[str, t.Any]
PaneDict = dict[str, t.Any]


class CmdProtocol(t.Protocol):
    """Command protocol for tmux command."""

    def __call__(self, cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        """Wrap tmux_cmd."""
        ...


class CmdMixin:
    """Command mixin for tmux command."""

    cmd: CmdProtocol


class EnvironmentMixin:
    """Mixin for manager session and server level environment variables in tmux."""

    _add_option = None

    cmd: Callable[[t.Any, t.Any], tmux_cmd]

    def __init__(self, add_option: str | None = None) -> None:
        self._add_option = add_option

    def set_environment(
        self,
        name: str,
        value: str,
        *,
        expand_format: bool | None = None,
        hidden: bool | None = None,
    ) -> None:
        """Set environment ``$ tmux set-environment <name> <value>``.

        Parameters
        ----------
        name : str
            The environment variable name, e.g. 'PATH'.
        value : str
            Environment value.
        expand_format : bool, optional
            Expand tmux format strings in the value (``-F`` flag).

            .. versionadded:: 0.56
        hidden : bool, optional
            Mark the variable as hidden (``-h`` flag).

            .. versionadded:: 0.56

        Raises
        ------
        ValueError
            If tmux returns an error.
        """
        args = ["set-environment"]
        if self._add_option:
            args += [self._add_option]

        if expand_format:
            args += ["-F"]

        if hidden:
            args += ["-h"]

        args += [name, value]

        cmd = self.cmd(*args)

        if cmd.stderr:
            (
                cmd.stderr[0]
                if isinstance(cmd.stderr, list) and len(cmd.stderr) == 1
                else cmd.stderr
            )
            msg = f"tmux set-environment stderr: {cmd.stderr}"
            raise ValueError(msg)

    def unset_environment(self, name: str) -> None:
        """Unset environment variable ``$ tmux set-environment -u <name>``.

        Parameters
        ----------
        name : str
            The environment variable name, e.g. 'PATH'.

        Raises
        ------
        ValueError
            If tmux returns an error.
        """
        args = ["set-environment"]
        if self._add_option:
            args += [self._add_option]
        args += ["-u", name]

        cmd = self.cmd(*args)

        if cmd.stderr:
            (
                cmd.stderr[0]
                if isinstance(cmd.stderr, list) and len(cmd.stderr) == 1
                else cmd.stderr
            )
            msg = f"tmux set-environment stderr: {cmd.stderr}"
            raise ValueError(msg)

    def remove_environment(self, name: str) -> None:
        """Remove environment variable ``$ tmux set-environment -r <name>``.

        Parameters
        ----------
        name : str
            The environment variable name, e.g. 'PATH'.

        Raises
        ------
        ValueError
            If tmux returns an error.
        """
        args = ["set-environment"]
        if self._add_option:
            args += [self._add_option]
        args += ["-r", name]

        cmd = self.cmd(*args)

        if cmd.stderr:
            (
                cmd.stderr[0]
                if isinstance(cmd.stderr, list) and len(cmd.stderr) == 1
                else cmd.stderr
            )
            msg = f"tmux set-environment stderr: {cmd.stderr}"
            raise ValueError(msg)

    def show_environment(self) -> dict[str, bool | str]:
        """Show environment ``$ tmux show-environment -t [session]``.

        Return dict of environment variables for the session.

        .. versionchanged:: 0.13

           Removed per-item lookups. Use :meth:`libtmux.common.EnvironmentMixin.getenv`.

        Returns
        -------
        dict
            environmental variables in dict, if no name, or str if name
            entered.
        """
        tmux_args = ["show-environment"]
        if self._add_option:
            tmux_args += [self._add_option]
        cmd = self.cmd(*tmux_args)
        output = cmd.stdout
        opts = [tuple(item.split("=", 1)) for item in output]
        opts_dict: dict[str, str | bool] = {}
        for _t in opts:
            if len(_t) == 2:
                opts_dict[_t[0]] = _t[1]
            elif len(_t) == 1:
                opts_dict[_t[0]] = True
            else:
                raise exc.VariableUnpackingError(variable=_t)

        return opts_dict

    def getenv(self, name: str) -> str | bool | None:
        """Show environment variable ``$ tmux show-environment -t [session] <name>``.

        Return the value of a specific variable if the name is specified.

        .. versionadded:: 0.13

        Parameters
        ----------
        name : str
            the environment variable name. such as 'PATH'.

        Returns
        -------
        str
            Value of environment variable
        """
        tmux_args: tuple[str | int, ...] = ()

        tmux_args += ("show-environment",)
        if self._add_option:
            tmux_args += (self._add_option,)
        tmux_args += (name,)
        cmd = self.cmd(*tmux_args)
        output = cmd.stdout
        opts = [tuple(item.split("=", 1)) for item in output]
        opts_dict: dict[str, str | bool] = {}
        for _t in opts:
            if len(_t) == 2:
                opts_dict[_t[0]] = _t[1]
            elif len(_t) == 1:
                opts_dict[_t[0]] = True
            else:
                raise exc.VariableUnpackingError(variable=_t)

        return opts_dict.get(name)


def raise_if_stderr(proc: tmux_cmd, subcommand: str) -> None:
    """Raise :exc:`TmuxCommandFailed` tagged with the tmux subcommand on stderr.

    Centralizes the ``if proc.stderr: raise exc.LibTmuxException(proc.stderr)``
    pattern scattered across the wrappers. Tags the exception with the
    originating tmux subcommand so downstream consumers (e.g. libtmux-mcp's
    ``handle_tool_errors``) keep the "which tmux command failed" context.

    Parameters
    ----------
    proc : :class:`tmux_cmd`
        Result of a :meth:`Server.cmd` / :meth:`Session.cmd` / etc. call.
    subcommand : str
        The tmux subcommand the wrapper invoked, e.g. ``"last-window"``,
        ``"swap-pane"``. Surfaces in ``str(exc)`` as a ``"<subcommand>: …"``
        prefix.

    Raises
    ------
    :exc:`TmuxCommandFailed`
        When ``proc.stderr`` is non-empty. A :exc:`LibTmuxException`, which
        this raised before 0.63.

    Examples
    --------
    >>> from libtmux.common import raise_if_stderr
    >>> from libtmux import exc
    >>> proc = session.cmd("display-message", "-p", "#{session_id}")
    >>> raise_if_stderr(proc, "display-message")  # no stderr → no raise

    .. versionadded:: 0.57
    """
    if proc.stderr:
        raise exc.TmuxCommandFailed(
            "\n".join(proc.stderr),
            subcommand=subcommand,
        )


def _guard_sync(
    engine: object,
    member: Callable[[CommandRequest], t.Any],
    method: str,
    request: CommandRequest,
) -> t.Any:
    """Call one synchronous engine capability, guarding the result.

    The single call site every engine capability -- ``run()`` and the
    optional ``command_line()`` -- is invoked through.
    :class:`~libtmux.engines.base.TmuxEngine` and
    :class:`~libtmux.engines.base.SupportsCommandLine` are
    :func:`~typing.runtime_checkable` :class:`typing.Protocol` classes, so
    ``isinstance()`` accepts an engine on attribute *names* alone -- never
    signatures, never async-ness -- and an ``async def run`` (or ``async def
    command_line``) engine passes structurally and reaches here. Routing
    every dispatch through this one function means the guard below only has
    to be written once: a call site added later inherits it instead of
    needing its own copy.

    Parameters
    ----------
    engine : object
        The engine the capability belongs to; named in the error.
    member : :class:`~collections.abc.Callable`
        The already-resolved bound method to invoke.
    method : str
        Its name, ``"run"`` or ``"command_line"``, for the error message.
    request : CommandRequest
        Forwarded as the sole positional argument.

    Returns
    -------
    typing.Any
        Whatever *method* returned. Never an awaitable.

    Raises
    ------
    :exc:`~libtmux.exc.AsyncEngineMismatch`
        *method* returned an awaitable instead of the value its protocol
        promises.

    Notes
    -----
    Declared-``async def`` members are rejected *before* the call, so the
    common shape never creates a coroutine at all and nothing is left to warn
    about. That check cannot be complete on its own -- CPython says as much in
    :mod:`unittest.async_case`, whose case 3 is a "regular ``def`` that
    returns an awaitable object" -- so the value is tested too.

    A coroutine that did get created is closed, which is safe precisely
    because it has never been started: :c:func:`gen_close` on a frame still in
    ``FRAME_CREATED`` clears it without running a line of the body, and
    ``"coroutine ... was never awaited"`` is only warned for a frame still in
    that state at collection. Closing is best-effort -- guarded against
    :class:`BaseException`, since :exc:`asyncio.CancelledError` is not an
    :class:`Exception` -- so a hostile awaitable cannot replace the
    diagnostic with an error of its own.

    Only genuine coroutines are closed. A :class:`asyncio.Task` or
    :class:`asyncio.Future` is dropped untouched: one bound to another
    thread's event loop silently fails to receive
    :meth:`~asyncio.Task.cancel` (that needs ``loop.call_soon_threadsafe``),
    and cancelling one shared with another awaiter would destroy that
    awaiter's result. An eager-started ``Task`` (3.12+) has already run its
    body synchronously before ``run()`` returned, so nothing here could have
    prevented that side effect either way.
    """
    if inspect.iscoroutinefunction(member):
        raise exc.AsyncEngineMismatch(engine, method)

    result = member(request)
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            with contextlib.suppress(BaseException):
                result.close()
        raise exc.AsyncEngineMismatch(engine, method)
    return result


def _dispatch_run(engine: TmuxEngine, request: CommandRequest) -> CommandResult:
    """Run one command through *engine*, guarding the result.

    Parameters
    ----------
    engine : TmuxEngine
        The engine to dispatch through.
    request : CommandRequest
        The command.

    Returns
    -------
    CommandResult
        Whatever ``run()`` returned. Never an awaitable.

    Raises
    ------
    :exc:`~libtmux.exc.AsyncEngineMismatch`
        ``run`` is asynchronous.
    """
    return t.cast(
        "CommandResult",
        _guard_sync(engine, engine.run, "run", request),
    )


def _dispatch_command_line(
    engine: SupportsCommandLine,
    request: CommandRequest,
) -> tuple[str, ...]:
    """Render *request*'s argv through *engine*, guarding the result.

    Parameters
    ----------
    engine : SupportsCommandLine
        The engine to ask.
    request : CommandRequest
        The command.

    Returns
    -------
    tuple[str, ...]
        The argv. Never an awaitable.

    Raises
    ------
    :exc:`~libtmux.exc.AsyncEngineMismatch`
        ``command_line`` is asynchronous.
    """
    return t.cast(
        "tuple[str, ...]",
        _guard_sync(engine, engine.command_line, "command_line", request),
    )


_RELEASE_GRACE = 5.0
"""Seconds to let tmux answer the release signal and the waiter exit."""


def _release_waiter(
    waiter: subprocess.Popen[str],
    release_argv: list[str],
    grace: float = _RELEASE_GRACE,
    env: t.Mapping[str, str] | None = None,
    *,
    then_argv: list[str] | None = None,
) -> bool:
    """End a timed-out ``wait-for`` client without leaving a ghost waiter.

    tmux has no timeout for ``wait-for``, and before tmux 3.8-rc2 a waiter
    that is killed stays queued on its channel: tmux only remembers a signal
    while nobody waits, so the next signal is spent on the dead waiter.
    Releasing the waiter through tmux while it is still alive makes tmux
    dequeue it itself, so the channel is clean again.

    The client is killed only when the server does not answer, or when no
    release ended it, the one case where nothing can be left behind but the
    server's own state.

    Parameters
    ----------
    waiter : :class:`subprocess.Popen`
        The ``wait-for`` client that outlived its timeout.
    release_argv : list[str]
        Full command line that releases the waiter: a signal on its channel,
        or on tmux 3.8 a ``wait-for -w`` naming this waiter alone.
    grace : float, optional
        Seconds to give the release and the waiter's exit, each.
    env : mapping, optional
        Environment for the release commands; ``None`` inherits this process's.
    then_argv : list[str], optional
        A second release to try when *release_argv* ran but the waiter did
        not exit, such as a signal after a targeted release named the wrong
        client.

    Returns
    -------
    bool
        *True* when the waiter exited after a release, *False* when it had
        to be killed.

    Examples
    --------
    >>> from libtmux.common import _release_waiter
    >>> waiter = subprocess.Popen(
    ...     [sys.executable, '-c', 'import time; time.sleep(300)'],
    ...     stdout=subprocess.PIPE,
    ...     stderr=subprocess.PIPE,
    ...     text=True,
    ... )
    >>> _release_waiter(waiter, [sys.executable, '-c', 'pass'], grace=0.25)
    False
    >>> waiter.returncode
    -9

    A second release runs only when the first one did not end the waiter:

    >>> waiter = subprocess.Popen(
    ...     [sys.executable, '-c', 'import time; time.sleep(300)'],
    ...     stdout=subprocess.PIPE,
    ...     stderr=subprocess.PIPE,
    ...     text=True,
    ... )
    >>> _release_waiter(
    ...     waiter,
    ...     [sys.executable, '-c', 'pass'],
    ...     grace=0.25,
    ...     then_argv=[sys.executable, '-c', f'import os; os.kill({waiter.pid}, 15)'],
    ... )
    True
    >>> waiter.returncode
    -15
    """
    for argv in (release_argv, then_argv):
        if argv is None:
            continue
        try:
            subprocess.run(
                argv,
                capture_output=True,
                timeout=grace,
                check=False,
                env=env,
            )
        except (subprocess.TimeoutExpired, OSError):
            # The server did not answer; there is nothing to release through.
            break
        try:
            waiter.communicate(timeout=grace)
        except subprocess.TimeoutExpired:
            continue
        except OSError:
            break
        return True
    _kill_and_reap(waiter)
    return False


_LIVE_WAITERS: dict[int, tuple[subprocess.Popen[str], list[str]]] = {}
_LIVE_WAITERS_GUARD = threading.Lock()
_EXITING = threading.Event()


@contextlib.contextmanager
def _tracked_waiter(
    waiter: subprocess.Popen[str],
    release_argv: list[str],
) -> t.Iterator[None]:
    """Record a ``wait-for`` client for as long as it may be blocked.

    A normal exit, a timeout and an exception all release the waiter on their
    own path. What none of them reaches is the interpreter ending while a
    thread is still blocked on one, so the :mod:`atexit` hook below releases
    whatever is recorded here.

    Examples
    --------
    >>> from libtmux.common import _LIVE_WAITERS, _tracked_waiter
    >>> process = subprocess.Popen(
    ...     [sys.executable, '-c', 'pass'],
    ...     stdout=subprocess.PIPE,
    ...     stderr=subprocess.PIPE,
    ...     text=True,
    ... )
    >>> with _tracked_waiter(process, ['true']):
    ...     process.pid in _LIVE_WAITERS
    True

    >>> process.pid in _LIVE_WAITERS
    False
    >>> _ = process.communicate()
    """
    with _LIVE_WAITERS_GUARD:
        _LIVE_WAITERS[waiter.pid] = (waiter, release_argv)
    try:
        if _EXITING.is_set():
            # A thread that outlived the hook below started this one late.
            _release_waiter(waiter, release_argv, grace=1.0)
        yield
    finally:
        with _LIVE_WAITERS_GUARD:
            _LIVE_WAITERS.pop(waiter.pid, None)


@atexit.register
def _release_live_waiters() -> None:
    """Release every ``wait-for`` client still blocked when the interpreter exits.

    Without this a thread that was blocked on :meth:`Server.wait_for` when the
    process ended leaves its tmux client behind, waiting on a channel nobody
    may ever signal. A thread that is still running starts its next waiter
    released at once, so one wait cannot be replaced by another.
    """
    _EXITING.set()
    with _LIVE_WAITERS_GUARD:
        live = list(_LIVE_WAITERS.values())
        _LIVE_WAITERS.clear()
    for waiter, release_argv in live:
        if waiter.poll() is None:
            _release_waiter(waiter, release_argv, grace=1.0)


class tmux_cmd:
    """Run any :term:`tmux(1)` command, returning list-shaped output.

    Dispatches through a :class:`~libtmux.engines.base.TmuxEngine` --
    :class:`~libtmux.engines.subprocess.SubprocessEngine` unless one is passed --
    and adapts the engine's :class:`~libtmux.engines.base.CommandResult` to the
    ``list``-of-``str`` attributes libtmux's wrappers read.

    Parameters
    ----------
    *args : typing.Any
        tmux argv. Connection flags may be included inline (``"-Lwork"``); an
        engine supplies its own, so :meth:`libtmux.Server.cmd` passes only the
        subcommand.
    tmux_bin : str, optional
        Path to the tmux binary. Ignored when *engine* is given -- the engine
        owns its binary.
    engine : :class:`~libtmux.engines.base.TmuxEngine`, optional
        Executor to dispatch through.
    timeout : float, optional
        Seconds to allow tmux to run. *None* (the default) waits as long as
        tmux takes, which is what a rendezvous like ``wait-for`` needs when
        nobody is watching the clock. Give it a number when the command can
        block on something that may never happen.
    input : str or bytes, optional
        Data written to the tmux client's standard input, which is then
        closed. ``str`` is encoded as UTF-8 and raises
        :exc:`UnicodeEncodeError` when it cannot be; ``bytes`` are sent
        unchanged, so non-UTF-8 data works. ``None`` (the default) leaves
        standard input inherited from the calling process. Payload size is
        not limited by tmux's 16 KiB command size limit, which covers
        arguments only.

    Attributes
    ----------
    cmd : list[str]
        The full argv that ran, tmux binary first.
    stdout : list[str]
        Standard output, one line per item.
    stderr : list[str]
        Standard error, one line per item, blanks removed.
    returncode : int
        tmux exit code.

    Raises
    ------
    :exc:`~libtmux.exc.TmuxTimeout`
        When *timeout* elapses. A subprocess engine kills and reaps the tmux
        client it spawned before the exception leaves; work the command
        started -- a pane's foreground process, the tmux server -- keeps
        running.
    :exc:`~libtmux.exc.AsyncEngineMismatch`
        *engine* is asynchronous -- its ``run()`` (or ``command_line()``,
        while rendering a DEBUG log line) handed back an awaitable, which
        this synchronous dispatch cannot await. Both calls route through
        :func:`_guard_sync`, the one place this is checked.

    Parameters
    ----------
    *args : object
        tmux arguments, stringified and appended after the binary.
    tmux_bin : str, optional
        Path to the tmux binary. Resolved from ``$PATH`` when *None*.
    timeout : float, optional
        Seconds to allow tmux to run. *None* (the default) waits as long as
        tmux takes, which is what a rendezvous like ``wait-for`` needs when
        nobody is watching the clock. Give it a number when the command can
        block on something that may never happen.

    Raises
    ------
    :exc:`~libtmux.exc.TmuxTimeout`
        When *timeout* elapses. The tmux client this spawned is killed and
        reaped before the exception leaves, so the call leaves no child of its
        own behind. Work the command started -- a pane's foreground process,
        the tmux server -- is unaffected and keeps running.

    Examples
    --------
    Create a new session, check for error:

    >>> proc = tmux_cmd(f'-L{server.socket_name}', 'new-session', '-d', '-P', '-F#S')
    >>> if proc.stderr:
    ...     raise exc.LibTmuxException(
    ...         'Command: %s returned error: %s' % (proc.cmd, proc.stderr)
    ...     )
    ...

    >>> print(f'tmux command returned {" ".join(proc.stdout)}')
    tmux command returned 2

    Equivalent to:

    .. code-block:: console

        $ tmux new-session -s my session

    A foreground ``run-shell`` blocks until its shell command exits. Bound
    it, and a command that never exits costs a known amount of time:

    >>> try:
    ...     tmux_cmd(
    ...         f'-L{server.socket_name}', 'run-shell', 'sleep 5',
    ...         timeout=0.25,
    ...     )
    ... except exc.TmuxTimeout as e:
    ...     print(e.timeout, e.cmd[-2:])
    0.25 ['run-shell', 'sleep 5']

    Send data on the client's standard input with ``input``. Commands that
    take ``-`` as a path, such as ``load-buffer``, read it from there:

    >>> proc = tmux_cmd(
    ...     f'-L{server.socket_name}', 'load-buffer', '-b', 'doc_stdin', '-',
    ...     input='from stdin',
    ... )
    >>> proc.returncode
    0
    >>> server.show_buffer(buffer_name='doc_stdin')
    'from stdin'

    Notes
    -----
    Every command runs as ``tmux -u``, so output keeps its non-ASCII
    characters whatever locale the environment sets. ``attach-session``
    and a foreground ``new-session`` run an interactive client and do not
    get ``-u``.

    .. versionchanged:: 0.63
        Added *timeout*.

    .. versionchanged:: 0.8
        Renamed from ``tmux`` to ``tmux_cmd``.
    """

    def __init__(
        self,
        *args: t.Any,
        tmux_bin: str | None = None,
        engine: TmuxEngine | None = None,
        timeout: float | None = None,
        input: str | bytes | None = None,  # noqa: A002
    ) -> None:
        runner: TmuxEngine = (
            engine if engine is not None else SubprocessEngine.of(tmux_bin)
        )
        request = CommandRequest.from_args(*args, timeout=timeout, input=input)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "tmux command dispatched",
                extra={
                    "tmux_cmd": _loggable_cmd(
                        _dispatch_command_line(runner, request)
                        if isinstance(runner, SupportsCommandLine)
                        else request.args,
                    ),
                    "tmux_subcommand": request.subcommand,
                },
            )

        result = _dispatch_run(runner, request)

        self.cmd = list(result.cmd)
        self.returncode = result.returncode
        self.stderr = list(result.stderr)
        # Read defensively: ``process`` is the one field of ``CommandResult``
        # that no protocol declares, so an engine returning its own
        # result type -- which ``TmuxEngine`` permits -- need not carry it.
        process: subprocess.Popen[str] | subprocess.Popen[bytes] | None = getattr(
            result, "process", None
        )
        self._process = process

        # tmux writes ``has-session``'s answer to stderr; the wrappers have
        # always read it off stdout. Adapted here, not in an engine, so every
        # engine stays a plain executor.
        stdout = list(result.stdout)
        self.stdout = (
            [self.stderr[0]]
            if "has-session" in self.cmd and self.stderr and not stdout
            else stdout
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "tmux command completed",
                extra={
                    "tmux_cmd": _loggable_cmd(self.cmd),
                    "tmux_subcommand": request.subcommand,
                    "tmux_exit_code": self.returncode,
                    "tmux_stdout": self.stdout[:100],
                    "tmux_stderr": self.stderr[:100],
                    "tmux_stdout_len": len(self.stdout),
                    "tmux_stderr_len": len(self.stderr),
                },
            )

    @property
    def process(self) -> subprocess.Popen[str] | subprocess.Popen[bytes]:
        """Return the finished :class:`subprocess.Popen`.

        Returns
        -------
        subprocess.Popen
            The process the default engine forked.

        Raises
        ------
        :exc:`~libtmux.exc.LibTmuxException`
            The engine that ran the command never forked a process. Only an
            injected engine can do that; the default engine always forks.

        Notes
        -----
        Deprecated: read :attr:`returncode`, :attr:`stdout` and :attr:`stderr`,
        which every engine fills in. Accessing this emits a
        :exc:`DeprecationWarning`.

        Examples
        --------
        >>> import warnings
        >>> with warnings.catch_warnings():
        ...     warnings.simplefilter("ignore", DeprecationWarning)
        ...     server.cmd("display-message", "-p", "hi").process.returncode
        0
        """
        warnings.warn(
            "tmux_cmd.process is deprecated: it is unavailable on engines that "
            "fork no process. Read returncode, stdout and stderr instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if self._process is None:
            msg = "engine did not fork a subprocess; tmux_cmd.process is unavailable"
            raise exc.LibTmuxException(msg)
        return self._process


class _TmuxVersionUnavailable(Exception):
    """Internal signal: this tmux predates the ``-V`` flag (pre-1.7)."""


def _no_version_flag_fallback() -> str:
    """Return a synthetic version string when tmux lacks ``-V``.

    OpenBSD ships a ``-V``-less base tmux, so assume the maximum supported
    version; any other platform is genuinely too old.
    """
    if sys.platform.startswith("openbsd"):  # openbsd has no tmux -V
        return f"{TMUX_MAX_VERSION}-openbsd"
    msg = (
        f"libtmux supports tmux {TMUX_MIN_VERSION} and greater. This system"
        " does not meet the minimum tmux version requirement."
    )
    raise exc.VersionTooLow(msg)


def _query_version(tmux_bin: str | None = None) -> str:
    """Return the raw ``tmux -V`` version token, letter suffix intact.

    Runs ``tmux -V`` and extracts the version token (e.g. ``"3.7a"``,
    ``"master"``, ``"next-3.8"``). Not memoized -- :func:`get_version` and
    :func:`get_version_str` each cache their own result on top of this query.

    Parameters
    ----------
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    str
        Raw version token from ``tmux -V``.

    Raises
    ------
    _TmuxVersionUnavailable
        tmux predates the ``-V`` flag; callers apply
        :func:`_no_version_flag_fallback`.
    :exc:`~libtmux.exc.VersionTooLow`
        tmux reported another error on ``-V``.
    """
    proc = tmux_cmd("-V", tmux_bin=tmux_bin)
    if proc.stderr:
        if proc.stderr[0] == "tmux: unknown option -- V":
            raise _TmuxVersionUnavailable
        raise exc.VersionTooLow(proc.stderr)

    return proc.stdout[0].split("tmux ")[1]


@functools.cache
def get_version_str(tmux_bin: str | None = None) -> str:
    """Return the tmux version string verbatim, preserving letter suffixes.

    :func:`get_version` normalizes point releases for numeric comparison
    (``"3.7a"`` becomes ``LooseVersion("3.7")``). This helper keeps the raw
    suffix, so callers can distinguish patch releases whose behavior differs
    -- for example the tmux 3.7 break-pane crash, reverted in 3.7a.

    Parameters
    ----------
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    str
        Raw tmux version, e.g. ``"3.7a"``. Git builds return ``"master"``;
        OpenBSD base tmux returns ``"<max>-openbsd"``.

    Examples
    --------
    >>> isinstance(get_version_str(), str)
    True

    Notes
    -----
    Memoized via :func:`functools.cache`, keyed on *tmux_bin*, independently of
    :func:`get_version`. Call ``get_version_str.cache_clear()`` after swapping
    the tmux binary.
    """
    try:
        return _query_version(tmux_bin=tmux_bin)
    except _TmuxVersionUnavailable:
        return _no_version_flag_fallback()


@functools.cache
def get_version(tmux_bin: str | None = None) -> LooseVersion:
    """Return tmux version.

    If tmux is built from git master, the version returned will be the latest
    version appended with -master, e.g. ``2.4-master``.

    If using OpenBSD's base system tmux, the version will have ``-openbsd``
    appended to the latest version, e.g. ``2.4-openbsd``.

    A release candidate reads as its release: ``3.8-rc3`` returns ``3.8``.

    Parameters
    ----------
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux from
        :func:`shutil.which`.

    Returns
    -------
    :class:`distutils.version.LooseVersion`
        tmux version according to *tmux_bin* if provided, otherwise the
        system tmux from :func:`shutil.which`

    Notes
    -----
    Memoized via :func:`functools.cache`, keyed on the *tmux_bin* argument
    (``None`` is a distinct key from any explicit path), independently of
    :func:`get_version_str`. The cache is sticky across ``PATH`` changes and
    on-disk binary swaps when *tmux_bin* is ``None`` or the same path string --
    call ``get_version.cache_clear()`` to invalidate. Tests that monkey-patch
    :class:`tmux_cmd` should call ``cache_clear()`` before asserting
    parsed-version behavior.
    """
    try:
        version = _query_version(tmux_bin=tmux_bin)
    except _TmuxVersionUnavailable:
        # OpenBSD base tmux lacks ``-V``; skip letter-stripping on the synthetic.
        return LooseVersion(_no_version_flag_fallback())

    # Allow latest tmux HEAD
    if version == "master":
        return LooseVersion(f"{TMUX_MAX_VERSION}-master")

    # A release candidate (``3.8-rc``, ``3.8-rc3``) reads as its release; the
    # candidate number must not survive the letter strip as a minor digit.
    version = re.sub(r"-rc\d*$", "", version)
    version = re.sub(r"[a-z-]", "", version)

    return LooseVersion(version)


def has_version(version: str, tmux_bin: str | None = None) -> bool:
    """Return True if tmux version installed.

    Parameters
    ----------
    version : str
        version number, e.g. '3.2a'
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
        True if version matches
    """
    return get_version(tmux_bin=tmux_bin) == LooseVersion(version)


def has_gt_version(min_version: str, tmux_bin: str | None = None) -> bool:
    """Return True if tmux version greater than minimum.

    Parameters
    ----------
    min_version : str
        tmux version, e.g. '3.2a'
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
        True if version above min_version
    """
    return get_version(tmux_bin=tmux_bin) > LooseVersion(min_version)


def has_gte_version(min_version: str, tmux_bin: str | None = None) -> bool:
    """Return True if tmux version greater or equal to minimum.

    Parameters
    ----------
    min_version : str
        tmux version, e.g. '3.2a'
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
        True if version above or equal to min_version
    """
    return get_version(tmux_bin=tmux_bin) >= LooseVersion(min_version)


def has_lte_version(max_version: str, tmux_bin: str | None = None) -> bool:
    """Return True if tmux version less or equal to minimum.

    Parameters
    ----------
    max_version : str
        tmux version, e.g. '3.2a'
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
         True if version below or equal to max_version
    """
    return get_version(tmux_bin=tmux_bin) <= LooseVersion(max_version)


def has_lt_version(max_version: str, tmux_bin: str | None = None) -> bool:
    """Return True if tmux version less than minimum.

    Parameters
    ----------
    max_version : str
        tmux version, e.g. '3.2a'
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
        True if version below max_version
    """
    return get_version(tmux_bin=tmux_bin) < LooseVersion(max_version)


def has_minimum_version(raises: bool = True, tmux_bin: str | None = None) -> bool:
    """Return True if tmux meets version requirement. Version >= 3.2a.

    Parameters
    ----------
    raises : bool
        raise exception if below minimum version requirement
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
        True if tmux meets minimum required version.

    Raises
    ------
    libtmux.exc.VersionTooLow
        tmux version below minimum required for libtmux

    Notes
    -----
    .. versionchanged:: 0.49.0
        Minimum version bumped to 3.2a. For older tmux, use libtmux v0.48.x.

    .. versionchanged:: 0.7.0
        No longer returns version, returns True or False

    .. versionchanged:: 0.1.7
        Versions will now remove trailing letters per
        `Issue 55 <https://github.com/tmux-python/tmuxp/issues/55>`_.
    """
    current_version = get_version(tmux_bin=tmux_bin)
    if current_version < LooseVersion(TMUX_MIN_VERSION):
        if raises:
            msg = (
                f"libtmux only supports tmux {TMUX_MIN_VERSION} and greater. This "
                f"system has {current_version} installed. Upgrade your "
                "tmux to use libtmux, or use libtmux v0.48.x for older tmux versions."
            )
            raise exc.VersionTooLow(msg)
        return False
    return True


def session_check_name(session_name: str | None) -> None:
    """Raise exception session name invalid, modeled after tmux function.

    tmux(1) session names may not be empty, or include periods or colons.
    These delimiters are reserved for noting session, window and pane.

    Parameters
    ----------
    session_name : str
        Name of session.

    Raises
    ------
    :exc:`exc.BadSessionName`
        Invalid session name.
    """
    if session_name is None or len(session_name) == 0:
        raise exc.BadSessionName(reason="empty", session_name=session_name)
    if "." in session_name:
        raise exc.BadSessionName(reason="contains periods", session_name=session_name)
    if ":" in session_name:
        raise exc.BadSessionName(reason="contains colons", session_name=session_name)


_WINDOW_SPECIAL_TARGET = re.compile(r"\d+|[@=].*|[!^$]|[+-]\d*")


def _exact_window_target(target: str | int) -> str | int:
    """Return the window part of a tmux target so a name matches exactly.

    Window indexes, ids (``@1``), ``=name`` and tmux's relative tokens
    (``!``, ``^``, ``$``, ``+``, ``-``, ``+2``) pass through untouched; any
    other string is a window name and gets a leading ``=``.

    >>> _exact_window_target("foo")
    '=foo'
    >>> _exact_window_target("2")
    '2'
    >>> _exact_window_target("@3")
    '@3'
    """
    if isinstance(target, int) or _WINDOW_SPECIAL_TARGET.fullmatch(target):
        return target
    return f"={target}"


def get_libtmux_version() -> LooseVersion:
    """Return libtmux version is a PEP386 compliant format.

    Returns
    -------
    distutils.version.LooseVersion
        libtmux version
    """
    from libtmux.__about__ import __version__

    return LooseVersion(__version__)
