"""Helper methods and mixins for libtmux.

libtmux.common
~~~~~~~~~~~~~~

"""

from __future__ import annotations

import dataclasses
import functools
import logging
import re
import shlex
import sys
import typing as t
import warnings

from . import exc
from ._compat import LooseVersion
from .engines.base import (
    AsyncTmuxEngine,
    CommandRequest,
    CommandResult,
    SupportsCommandLine,
    split_direct_argv,
)
from .engines.subprocess import SubprocessEngine

if t.TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable

    from .engines.base import TmuxEngine

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

    def __call__(self, cmd: str, *args: t.Any, **kwargs: t.Any) -> CommandResult:
        """Wrap tmux_cmd."""
        ...


class CmdMixin:
    """Command mixin for tmux command."""

    cmd: CmdProtocol


class EnvironmentMixin:
    """Mixin for manager session and server level environment variables in tmux."""

    _add_option = None

    cmd: Callable[[t.Any, t.Any], CommandResult]

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


def raise_if_stderr(proc: CommandResult, subcommand: str) -> None:
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


def dispatch(
    engine: TmuxEngine,
    *args: t.Any,
    tmux_bin: str | None = None,
) -> CommandResult:
    """Run one tmux command through *engine* and adapt its result.

    The single dispatch path every wrapper uses. Two things happen here rather
    than in an engine, so that every engine stays a plain executor: the debug
    logging that names the command line before and after it runs, and tmux's
    ``has-session`` quirk.

    tmux answers ``has-session`` on stderr, while libtmux has always reported it
    on stdout. Adapting it here keeps that promise for whichever engine ran the
    command.

    Parameters
    ----------
    engine : TmuxEngine
        The executor.
    *args : typing.Any
        The tmux subcommand and its arguments, stringified.
    tmux_bin : str, optional
        Override the tmux binary for this one command.

    Returns
    -------
    CommandResult
        The adapted result.

    Examples
    --------
    >>> from libtmux.engines import SubprocessEngine
    >>> engine = SubprocessEngine.for_server(server)
    >>> dispatch(engine, "display-message", "-p", "hi").stdout
    ['hi']

    ``has-session`` reports on stdout, as it always has:

    >>> dispatch(engine, "has-session", "-t", "nope").stdout  # doctest: +ELLIPSIS
    ["can't find session: nope"]
    """
    request = CommandRequest.from_args(*args, tmux_bin=tmux_bin)

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "tmux command dispatched",
            extra={
                "tmux_cmd": shlex.join(
                    engine.command_line(request)
                    if isinstance(engine, SupportsCommandLine)
                    else request.args,
                ),
                "tmux_subcommand": request.subcommand,
            },
        )

    result = engine.run(request)

    cmd = list(result.cmd)
    stderr = list(result.stderr)
    stdout = list(result.stdout)
    if "has-session" in cmd and stderr and not stdout:
        stdout = [stderr[0]]
        result = dataclasses.replace(result, stdout=stdout)

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "tmux command completed",
            extra={
                "tmux_cmd": shlex.join(cmd),
                "tmux_subcommand": request.subcommand,
                "tmux_exit_code": result.returncode,
                "tmux_stdout": stdout[:100],
                "tmux_stderr": stderr[:100],
                "tmux_stdout_len": len(stdout),
                "tmux_stderr_len": len(stderr),
            },
        )
    return result


async def adispatch(
    engine: AsyncTmuxEngine,
    *args: t.Any,
    tmux_bin: str | None = None,
) -> CommandResult:
    """Await one tmux command through *engine* and adapt its result.

    The async twin of :func:`dispatch`, sharing its adaptations so a command
    reads the same whichever kind of engine ran it. Two things happen here rather
    than in an engine, so that every engine stays a plain executor: the debug
    logging that names the command line before and after it runs, and tmux's
    ``has-session`` quirk.

    tmux answers ``has-session`` on stderr, while libtmux has always reported it
    on stdout. Adapting it here keeps that promise for whichever engine ran the
    command.

    Parameters
    ----------
    engine : TmuxEngine
        The executor.
    *args : typing.Any
        The tmux subcommand and its arguments, stringified.
    tmux_bin : str, optional
        Override the tmux binary for this one command.

    Returns
    -------
    CommandResult
        The adapted result.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.engines import AsyncSubprocessEngine
    >>> engine = AsyncSubprocessEngine.for_server(server)
    >>> async def main():
    ...     return await adispatch(engine, "display-message", "-p", "hi")
    >>> asyncio.run(main()).stdout
    ['hi']
    """
    request = CommandRequest.from_args(*args, tmux_bin=tmux_bin)

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "tmux command dispatched",
            extra={
                "tmux_cmd": shlex.join(
                    engine.command_line(request)
                    if isinstance(engine, SupportsCommandLine)
                    else request.args,
                ),
                "tmux_subcommand": request.subcommand,
            },
        )

    result = await engine.run(request)

    cmd = list(result.cmd)
    stderr = list(result.stderr)
    stdout = list(result.stdout)
    if "has-session" in cmd and stderr and not stdout:
        stdout = [stderr[0]]
        result = dataclasses.replace(result, stdout=stdout)

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "tmux command completed",
            extra={
                "tmux_cmd": shlex.join(cmd),
                "tmux_subcommand": request.subcommand,
                "tmux_exit_code": result.returncode,
                "tmux_stdout": stdout[:100],
                "tmux_stderr": stderr[:100],
                "tmux_stdout_len": len(stdout),
                "tmux_stderr_len": len(stderr),
            },
        )
    return result


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

    Notes
    -----
    .. versionchanged:: 0.8
        Renamed from ``tmux`` to ``tmux_cmd``.
    """

    def __init__(
        self,
        *args: t.Any,
        tmux_bin: str | None = None,
        engine: TmuxEngine | None = None,
    ) -> None:
        runner: TmuxEngine = (
            engine if engine is not None else SubprocessEngine.of(tmux_bin)
        )
        result = dispatch(runner, *args)

        self.cmd = list(result.cmd)
        self.returncode = result.returncode
        self.stdout = list(result.stdout)
        self.stderr = list(result.stderr)
        self._process = result.process

    @property
    def ok(self) -> bool:
        """Whether tmux accepted the command.

        The same accessor :attr:`CommandResult.ok
        <libtmux.engines.base.CommandResult.ok>` carries, so code reads the same
        whether it holds an engine result or a wrapper's return value.

        Returns
        -------
        bool
            ``True`` when :attr:`returncode` is zero.

        Examples
        --------
        >>> server.cmd("display-message", "-p", "hi").ok
        True
        """
        return self.returncode == 0

    def raise_for_status(self) -> tmux_cmd:
        """Raise when tmux rejected the command, otherwise return self.

        Returns
        -------
        tmux_cmd
            This object, when :attr:`ok`.

        Raises
        ------
        :exc:`~libtmux.exc.LibTmuxException`
            tmux exited non-zero. The message carries tmux's own stderr.

        Examples
        --------
        >>> server.cmd("display-message", "-p", "hi").raise_for_status().stdout
        ['hi']

        >>> server.cmd("kill-window", "-t", "@999").raise_for_status()
        Traceback (most recent call last):
        ...
        libtmux.exc.LibTmuxException: kill-window: can't find window: @999
        """
        if self.ok:
            return self
        detail = " ".join(self.stderr) or f"exited {self.returncode}"
        command_argv = split_direct_argv(tuple(self.cmd[1:])).command_argv
        subcommand = command_argv[0] if command_argv else "tmux"
        msg = f"{subcommand}: {detail}"
        raise exc.LibTmuxException(msg)

    @property
    def process(self) -> subprocess.Popen[str]:
        """Return the finished :class:`subprocess.Popen`.

        Returns
        -------
        subprocess.Popen
            The process the default engine forked.

        Raises
        ------
        :exc:`~libtmux.exc.LibTmuxException`
            The engine that ran the command never forked a process.

        Examples
        --------
        >>> import warnings
        >>> proc = tmux_cmd(
        ...     f"-L{server.socket_name}", "display-message", "-p", "hi"
        ... )
        >>> with warnings.catch_warnings(record=True) as caught:
        ...     warnings.simplefilter("always")
        ...     returncode = proc.process.returncode
        >>> returncode
        0
        >>> caught[0].category.__name__
        'DeprecationWarning'

        .. deprecated:: 0.63
            Read :attr:`returncode`, :attr:`stdout` and :attr:`stderr` instead.
            Only engines that fork an OS process can supply this.
        """
        warnings.warn(
            "tmux_cmd.process is deprecated; use .returncode, .stdout, .stderr",
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


def get_libtmux_version() -> LooseVersion:
    """Return libtmux version is a PEP386 compliant format.

    Returns
    -------
    distutils.version.LooseVersion
        libtmux version
    """
    from libtmux.__about__ import __version__

    return LooseVersion(__version__)
