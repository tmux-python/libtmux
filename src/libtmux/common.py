"""Helper methods and mixins for libtmux.

libtmux.common
~~~~~~~~~~~~~~

"""

from __future__ import annotations

import functools
import logging
import re
import shlex
import shutil
import subprocess
import sys
import typing as t

from . import exc
from ._compat import LooseVersion

if t.TYPE_CHECKING:
    from collections.abc import Callable

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
    """Raise :exc:`LibTmuxException` tagged with the tmux subcommand on stderr.

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
    :exc:`LibTmuxException`
        When ``proc.stderr`` is non-empty.

    Examples
    --------
    >>> from libtmux.common import raise_if_stderr
    >>> from libtmux import exc
    >>> proc = session.cmd("display-message", "-p", "#{session_id}")
    >>> raise_if_stderr(proc, "display-message")  # no stderr → no raise

    .. versionadded:: 0.57
    """
    if proc.stderr:
        raise exc.LibTmuxException(
            "\n".join(proc.stderr),
            subcommand=subcommand,
        )


# tmux's global flags that take a value, and new-session's (getopt "...").
_TMUX_GLOBAL_VALUE_FLAGS = "cfLST"
_NEW_SESSION_VALUE_FLAGS = "cefFnstxy"


def _flag_letters(
    tokens: t.Sequence[str],
    value_flags: str,
) -> tuple[str, list[str]]:
    """Return ``(flag_letters, rest)`` for the leading option tokens.

    Stops at the first token that is not an option or a flag's value.
    """
    letters = ""
    i = 0
    while i < len(tokens) and tokens[i].startswith("-") and len(tokens[i]) > 1:
        token = tokens[i]
        i += 1
        for pos, letter in enumerate(token[1:], start=1):
            letters += letter
            if letter in value_flags:
                if pos == len(token) - 1:
                    i += 1  # the value is the next token
                break
    return letters, list(tokens[i:])


def _runs_interactive_client(args: t.Sequence[t.Any]) -> bool:
    """Return whether *args* make tmux run an interactive client.

    ``attach-session`` and a foreground ``new-session`` (or a bare ``tmux``)
    own a terminal. They must detect its encoding themselves, so
    :class:`tmux_cmd` does not force ``-u`` on them.
    """
    letters, rest = _flag_letters([str(a) for a in args], _TMUX_GLOBAL_VALUE_FLAGS)
    if "C" in letters or "V" in letters:
        return False
    if not rest:
        return True  # bare ``tmux`` starts a foreground session
    name = rest[0]
    if "attach-session".startswith(name) or name == "attach":
        return True
    if name == "new" or ("new-session".startswith(name) and len(name) > 4):
        flags, _ = _flag_letters(rest[1:], _NEW_SESSION_VALUE_FLAGS)
        return "d" not in flags
    return False


def _kill_and_reap(process: subprocess.Popen[t.Any]) -> None:
    """Kill a subprocess that outstayed its timeout, then reap it.

    :meth:`subprocess.Popen.communicate` leaves the child running when its
    *timeout* expires -- the caller has to kill and reap it, the same dance
    :func:`subprocess.run` does on its own timeout path. Skipping it leaks one
    tmux process per expiry.

    The child is waited for rather than drained: after ``SIGKILL`` it exits
    promptly, while reading its pipes to EOF could block on a grandchild that
    inherited them -- past the bound the caller just asked to enforce. The
    pipes are closed by hand instead, since nothing will read them.

    Parameters
    ----------
    process : :class:`subprocess.Popen`
        The timed-out child.

    Examples
    --------
    >>> from libtmux.common import _kill_and_reap
    >>> process = subprocess.Popen(
    ...     [sys.executable, '-c', 'import time; time.sleep(300)'],
    ...     stdout=subprocess.PIPE,
    ...     stderr=subprocess.PIPE,
    ...     text=True,
    ... )
    >>> process.poll() is None  # still running
    True

    >>> _kill_and_reap(process)
    >>> process.returncode is not None  # dead, and its exit status collected
    True
    """
    process.kill()
    process.wait()
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()


_RELEASE_GRACE = 5.0
"""Seconds to let tmux answer the release signal and the waiter exit."""


def _release_waiter(
    waiter: subprocess.Popen[str],
    release_argv: list[str],
    grace: float = _RELEASE_GRACE,
) -> bool:
    """End a timed-out ``wait-for`` client without leaving a ghost waiter.

    tmux has no timeout for ``wait-for``, and a waiter that is killed stays
    queued on its channel: tmux only remembers a signal while nobody waits,
    so the next signal is spent on the dead waiter. Signalling the channel
    while the waiter is still alive makes tmux dequeue it itself, so the
    signal is spent on exactly that waiter and the channel is clean again.

    The client is killed only when the server does not answer, the one case
    where nothing can be left behind but the server's own state.

    Parameters
    ----------
    waiter : :class:`subprocess.Popen`
        The ``wait-for`` client that outlived its timeout.
    release_argv : list[str]
        Full command line that signals the waiter's channel.
    grace : float, optional
        Seconds to give the signal and the waiter's exit, each.

    Returns
    -------
    bool
        *True* when the waiter exited after the signal, *False* when it had
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
    """
    try:
        subprocess.run(
            release_argv,
            capture_output=True,
            timeout=grace,
            check=False,
        )
        waiter.communicate(timeout=grace)
    except (subprocess.TimeoutExpired, OSError):
        _kill_and_reap(waiter)
        return False
    return True


def _decode_text(data: bytes) -> str:
    r"""Decode tmux output as ``tmux_cmd`` does in text mode.

    Examples
    --------
    >>> _decode_text(b"a\r\nb\rc\xff")
    'a\nb\nc\\xff'
    """
    text = data.decode("utf-8", errors="backslashreplace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _escape_trailing_semicolon(text: str) -> str:
    r"""Return ``text`` so tmux keeps a trailing ``;`` as data.

    tmux ends a command at an argument that ends in ``;`` and drops the
    character. A backslash before the ``;`` keeps it, so a text that already
    ends in ``\;`` gains a second backslash.

    Examples
    --------
    >>> _escape_trailing_semicolon("echo A;")
    'echo A\\;'
    >>> _escape_trailing_semicolon("echo A\\;")
    'echo A\\\\;'
    >>> _escape_trailing_semicolon("a;b")
    'a;b'
    """
    if text.endswith(";"):
        return f"{text[:-1]}\\;"
    return text


class tmux_cmd:
    """Run any :term:`tmux(1)` command through :py:mod:`subprocess`.

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

    >>> from libtmux import exc
    >>> try:
    ...     tmux_cmd(
    ...         f'-L{server.socket_name}', 'run-shell', 'sleep 5',
    ...         timeout=0.25,
    ...     )
    ... except exc.TmuxTimeout as e:
    ...     print(e)
    tmux command timed out after 0.25s: ...run-shell 'sleep 5'

    The exception carries what was killed and the bound it blew, so a caller
    does not have to parse the message back apart:

    >>> try:
    ...     tmux_cmd(
    ...         f'-L{server.socket_name}', 'run-shell', 'sleep 5',
    ...         timeout=0.25,
    ...     )
    ... except exc.TmuxTimeout as e:
    ...     (e.timeout, e.cmd[-2:])
    (0.25, ['run-shell', 'sleep 5'])
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

    Parameters
    ----------
    input : str or bytes, optional
        Data written to the tmux client's standard input, which is then
        closed. ``str`` is encoded as UTF-8 and raises
        :exc:`UnicodeEncodeError` when it cannot be; ``bytes`` are sent
        unchanged, so non-UTF-8 data works. ``None`` (the default) leaves
        standard input inherited from the calling process. Payload size is
        not limited by tmux's 16 KiB command size limit, which covers
        arguments only.

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
        timeout: float | None = None,
        input: str | bytes | None = None,  # noqa: A002
    ) -> None:
        self.process: subprocess.Popen[str] | subprocess.Popen[bytes]
        resolved = tmux_bin or shutil.which("tmux")
        if not resolved:
            raise exc.TmuxCommandNotFound

        cmd = [resolved]
        # -u: tmux treats a client as UTF-8 only from -u, $TMUX or a UTF-8
        # LC_ALL/LC_CTYPE/LANG, and otherwise rewrites every non-ASCII
        # character in its output to "_" -- FORMAT_SEPARATOR included.
        # An interactive client keeps the terminal's own locale detection.
        if not _runs_interactive_client(args):
            cmd.append("-u")
        cmd += args  # add the command arguments to cmd
        cmd = [str(c) for c in cmd]

        self.cmd = cmd

        if logger.isEnabledFor(logging.DEBUG):
            cmd_str = shlex.join(cmd)
            logger.debug(
                "tmux command dispatched",
                extra={"tmux_cmd": cmd_str},
            )

        try:
            if input is None:
                text_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="backslashreplace",
                )
                self.process = text_process
                stdout, stderr = text_process.communicate(timeout=timeout)
            else:
                # Bytes cannot go through a text-mode pipe, so this branch
                # reads binary and decodes the way text mode does.
                payload = input.encode("utf-8") if isinstance(input, str) else input
                binary_process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.process = binary_process
                raw_out, raw_err = binary_process.communicate(
                    payload,
                    timeout=timeout,
                )
                stdout = _decode_text(raw_out)
                stderr = _decode_text(raw_err)
            returncode = self.process.returncode
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None
        except subprocess.TimeoutExpired as e:
            _kill_and_reap(self.process)
            logger.error(  # noqa: TRY400
                "tmux command timed out",
                extra={
                    "tmux_cmd": shlex.join(cmd),
                    "tmux_timeout": e.timeout,
                },
            )
            raise exc.TmuxTimeout(cmd=cmd, timeout=e.timeout) from None
        except Exception:
            logger.error(  # noqa: TRY400
                "tmux subprocess failed",
                extra={
                    "tmux_cmd": shlex.join(cmd),
                },
            )
            raise

        self.returncode = returncode

        stdout_split = stdout.split("\n")
        # remove trailing newlines from stdout
        while stdout_split and stdout_split[-1] == "":
            stdout_split.pop()

        stderr_split = stderr.split("\n")
        self.stderr = list(filter(None, stderr_split))  # filter empty values

        if "has-session" in cmd and len(self.stderr) and not stdout_split:
            self.stdout = [self.stderr[0]]
        else:
            self.stdout = stdout_split

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "tmux command completed",
                extra={
                    "tmux_cmd": shlex.join(cmd),
                    "tmux_exit_code": self.returncode,
                    "tmux_stdout": self.stdout[:100],
                    "tmux_stderr": self.stderr[:100],
                    "tmux_stdout_len": len(self.stdout),
                    "tmux_stderr_len": len(self.stderr),
                },
            )


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
    raise exc.LibTmuxException(msg)


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
