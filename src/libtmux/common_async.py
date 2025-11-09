"""Async helper methods and mixins for libtmux.

libtmux.common_async
~~~~~~~~~~~~~~~~~~~~

This is the async-first implementation. The sync version (common.py) is
auto-generated from this file using tools/async_to_sync.py.

Async Support Patterns
----------------------

libtmux provides two complementary async patterns:

**Pattern A**: `.acmd()` methods on Server/Session/Window/Pane objects:

>>> import asyncio
>>> async def example():
...     # Uses 'server' fixture from conftest
...     result = await server.acmd('list-sessions')
...     return isinstance(result.stdout, list)
>>> asyncio.run(example())
True

**Pattern B**: Direct async execution with `tmux_cmd_async()`:

>>> async def example_b():
...     # Uses test server socket for isolation
...     result = await tmux_cmd_async('-L', server.socket_name, 'list-sessions')
...     return isinstance(result.stdout, list)
>>> asyncio.run(example_b())
True

Both patterns preserve 100% of the synchronous API. See the quickstart guide
for more information: https://libtmux.git-pull.com/quickstart_async.html

Performance
-----------

Async provides significant performance benefits for concurrent operations:

>>> async def concurrent():
...     # 2-3x faster than sequential execution
...     sock = server.socket_name
...     results = await asyncio.gather(
...         tmux_cmd_async('-L', sock, 'list-sessions'),
...         tmux_cmd_async('-L', sock, 'list-windows', '-a'),
...         tmux_cmd_async('-L', sock, 'list-panes', '-a'),
...     )
...     return len(results) == 3
>>> asyncio.run(concurrent())
True

See Also
--------
- Quickstart: https://libtmux.git-pull.com/quickstart_async.html
- Async Guide: https://libtmux.git-pull.com/topics/async_programming.html
- Examples: https://github.com/tmux-python/libtmux/tree/master/examples
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import sys
import typing as t

from . import exc
from ._compat import LooseVersion

if t.TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)


#: Minimum version of tmux required to run libtmux
TMUX_MIN_VERSION = "1.8"

#: Most recent version of tmux supported
TMUX_MAX_VERSION = "3.4"

SessionDict = dict[str, t.Any]
WindowDict = dict[str, t.Any]
WindowOptionDict = dict[str, t.Any]
PaneDict = dict[str, t.Any]


class AsyncEnvironmentMixin:
    """Async mixin for manager session and server level environment variables in tmux."""

    _add_option = None

    acmd: Callable[[t.Any, t.Any], Coroutine[t.Any, t.Any, tmux_cmd_async]]

    def __init__(self, add_option: str | None = None) -> None:
        self._add_option = add_option

    async def set_environment(self, name: str, value: str) -> None:
        """Set environment ``$ tmux set-environment <name> <value>``.

        Parameters
        ----------
        name : str
            the environment variable name. such as 'PATH'.
        option : str
            environment value.
        """
        args = ["set-environment"]
        if self._add_option:
            args += [self._add_option]

        args += [name, value]

        cmd = await self.acmd(*args)

        if cmd.stderr:
            (
                cmd.stderr[0]
                if isinstance(cmd.stderr, list) and len(cmd.stderr) == 1
                else cmd.stderr
            )
            msg = f"tmux set-environment stderr: {cmd.stderr}"
            raise ValueError(msg)

    async def unset_environment(self, name: str) -> None:
        """Unset environment variable ``$ tmux set-environment -u <name>``.

        Parameters
        ----------
        name : str
            the environment variable name. such as 'PATH'.
        """
        args = ["set-environment"]
        if self._add_option:
            args += [self._add_option]
        args += ["-u", name]

        cmd = await self.acmd(*args)

        if cmd.stderr:
            (
                cmd.stderr[0]
                if isinstance(cmd.stderr, list) and len(cmd.stderr) == 1
                else cmd.stderr
            )
            msg = f"tmux set-environment stderr: {cmd.stderr}"
            raise ValueError(msg)

    async def remove_environment(self, name: str) -> None:
        """Remove environment variable ``$ tmux set-environment -r <name>``.

        Parameters
        ----------
        name : str
            the environment variable name. such as 'PATH'.
        """
        args = ["set-environment"]
        if self._add_option:
            args += [self._add_option]
        args += ["-r", name]

        cmd = await self.acmd(*args)

        if cmd.stderr:
            (
                cmd.stderr[0]
                if isinstance(cmd.stderr, list) and len(cmd.stderr) == 1
                else cmd.stderr
            )
            msg = f"tmux set-environment stderr: {cmd.stderr}"
            raise ValueError(msg)

    async def show_environment(self) -> dict[str, bool | str]:
        """Show environment ``$ tmux show-environment -t [session]``.

        Return dict of environment variables for the session.

        .. versionchanged:: 0.13

           Removed per-item lookups. Use :meth:`libtmux.common_async.AsyncEnvironmentMixin.getenv`.

        Returns
        -------
        dict
            environmental variables in dict, if no name, or str if name
            entered.
        """
        tmux_args = ["show-environment"]
        if self._add_option:
            tmux_args += [self._add_option]
        cmd = await self.acmd(*tmux_args)
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

    async def getenv(self, name: str) -> str | bool | None:
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
        cmd = await self.acmd(*tmux_args)
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


class tmux_cmd_async:
    """Run any :term:`tmux(1)` command through :py:mod:`asyncio.subprocess`.

    This is the async-first implementation. The tmux_cmd class is auto-generated
    from this file.

    Examples
    --------
    **Basic Usage**: Execute a single tmux command asynchronously:

    >>> async def basic_example():
    ...     # Execute command with isolated socket
    ...     proc = await tmux_cmd_async('-L', server.socket_name, 'new-session', '-d', '-P', '-F#S')
    ...     # Verify command executed successfully
    ...     return len(proc.stdout) > 0 and not proc.stderr
    >>> asyncio.run(basic_example())
    True

    **Concurrent Operations**: Execute multiple commands in parallel for 2-3x speedup:

    >>> async def concurrent_example():
    ...     # All commands run concurrently
    ...     sock = server.socket_name
    ...     results = await asyncio.gather(
    ...         tmux_cmd_async('-L', sock, 'list-sessions'),
    ...         tmux_cmd_async('-L', sock, 'list-windows', '-a'),
    ...         tmux_cmd_async('-L', sock, 'list-panes', '-a'),
    ...     )
    ...     return all(isinstance(r.stdout, list) for r in results)
    >>> asyncio.run(concurrent_example())
    True

    **Error Handling**: Check return codes and stderr:

    >>> async def check_session():
    ...     # Non-existent session returns non-zero returncode
    ...     sock = server.socket_name
    ...     result = await tmux_cmd_async('-L', sock, 'has-session', '-t', 'nonexistent_12345')
    ...     return result.returncode != 0
    >>> asyncio.run(check_session())
    True

    Equivalent to:

    .. code-block:: console

        $ tmux new-session -s my session

    Performance
    -----------
    Async execution provides significant performance benefits when running
    multiple commands:

    - Sequential (sync): 4 commands ≈ 0.12s
    - Concurrent (async): 4 commands ≈ 0.04s
    - **Speedup: 2-3x faster**

    See Also
    --------
    - Pattern A (.acmd()): Use `server.acmd()` for object-oriented approach
    - Quickstart: https://libtmux.git-pull.com/quickstart_async.html
    - Examples: https://github.com/tmux-python/libtmux/tree/master/examples

    Notes
    -----
    .. versionchanged:: 0.8
        Renamed from ``tmux`` to ``tmux_cmd``.
    .. versionadded:: 0.48
        Added async support via ``tmux_cmd_async``.
    """

    def __init__(
        self,
        *args: t.Any,
        cmd: list[str] | None = None,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
    ) -> None:
        """Initialize async tmux command.

        This constructor is sync, but allows pre-initialization for testing.
        Use the async factory method or await __new__ for async execution.
        """
        if cmd is None:
            tmux_bin = shutil.which("tmux")
            if not tmux_bin:
                raise exc.TmuxCommandNotFound

            cmd = [tmux_bin]
            cmd += args  # add the command arguments to cmd
            cmd = [str(c) for c in cmd]

        self.cmd = cmd
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._executed = False

    async def execute(self) -> None:
        """Execute the tmux command asynchronously."""
        if self._executed:
            return

        try:
            process = await asyncio.create_subprocess_exec(
                *self.cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await process.communicate()
            self.returncode = process.returncode or 0
            self._stdout = stdout_bytes.decode("utf-8", errors="backslashreplace")
            self._stderr = stderr_bytes.decode("utf-8", errors="backslashreplace")
        except Exception:
            logger.exception(f"Exception for {' '.join(self.cmd)}")
            raise

        self._executed = True

    @property
    def stdout(self) -> list[str]:
        """Return stdout as list of lines."""
        stdout_split = self._stdout.split("\n")
        # remove trailing newlines from stdout
        while stdout_split and stdout_split[-1] == "":
            stdout_split.pop()

        if "has-session" in self.cmd and len(self.stderr) and not stdout_split:
            return [self.stderr[0]]

        logger.debug(
            "stdout for {cmd}: {stdout}".format(
                cmd=" ".join(self.cmd),
                stdout=stdout_split,
            ),
        )
        return stdout_split

    @property
    def stderr(self) -> list[str]:
        """Return stderr as list of non-empty lines."""
        stderr_split = self._stderr.split("\n")
        return list(filter(None, stderr_split))  # filter empty values

    async def __new__(cls, *args: t.Any, **kwargs: t.Any) -> tmux_cmd_async:
        """Create and execute tmux command asynchronously."""
        instance = object.__new__(cls)
        instance.__init__(*args, **kwargs)
        await instance.execute()
        return instance


async def get_version() -> LooseVersion:
    """Return tmux version (async).

    If tmux is built from git master, the version returned will be the latest
    version appended with -master, e.g. ``2.4-master``.

    If using OpenBSD's base system tmux, the version will have ``-openbsd``
    appended to the latest version, e.g. ``2.4-openbsd``.

    Examples
    --------
    Get tmux version asynchronously:

    >>> async def check_version():
    ...     version = await get_version()
    ...     return len(str(version)) > 0
    >>> asyncio.run(check_version())
    True

    Use in concurrent operations:

    >>> async def check_all():
    ...     sock = server.socket_name
    ...     version, sessions = await asyncio.gather(
    ...         get_version(),
    ...         tmux_cmd_async('-L', sock, 'list-sessions'),
    ...     )
    ...     return isinstance(str(version), str) and isinstance(sessions.stdout, list)
    >>> asyncio.run(check_all())
    True

    Returns
    -------
    :class:`distutils.version.LooseVersion`
        tmux version according to :func:`shtuil.which`'s tmux
    """
    proc = await tmux_cmd_async("-V")
    if proc.stderr:
        if proc.stderr[0] == "tmux: unknown option -- V":
            if sys.platform.startswith("openbsd"):  # openbsd has no tmux -V
                return LooseVersion(f"{TMUX_MAX_VERSION}-openbsd")
            msg = (
                f"libtmux supports tmux {TMUX_MIN_VERSION} and greater. This system"
                " is running tmux 1.3 or earlier."
            )
            raise exc.LibTmuxException(
                msg,
            )
        raise exc.VersionTooLow(proc.stderr)

    version = proc.stdout[0].split("tmux ")[1]

    # Allow latest tmux HEAD
    if version == "master":
        return LooseVersion(f"{TMUX_MAX_VERSION}-master")

    version = re.sub(r"[a-z-]", "", version)

    return LooseVersion(version)


async def has_version(version: str) -> bool:
    """Return True if tmux version installed (async).

    Parameters
    ----------
    version : str
        version number, e.g. '1.8'

    Returns
    -------
    bool
        True if version matches
    """
    return await get_version() == LooseVersion(version)


async def has_gt_version(min_version: str) -> bool:
    """Return True if tmux version greater than minimum (async).

    Parameters
    ----------
    min_version : str
        tmux version, e.g. '1.8'

    Returns
    -------
    bool
        True if version above min_version
    """
    return await get_version() > LooseVersion(min_version)


async def has_gte_version(min_version: str) -> bool:
    """Return True if tmux version greater or equal to minimum (async).

    Parameters
    ----------
    min_version : str
        tmux version, e.g. '1.8'

    Returns
    -------
    bool
        True if version above or equal to min_version
    """
    return await get_version() >= LooseVersion(min_version)


async def has_lte_version(max_version: str) -> bool:
    """Return True if tmux version less or equal to minimum (async).

    Parameters
    ----------
    max_version : str
        tmux version, e.g. '1.8'

    Returns
    -------
    bool
         True if version below or equal to max_version
    """
    return await get_version() <= LooseVersion(max_version)


async def has_lt_version(max_version: str) -> bool:
    """Return True if tmux version less than minimum (async).

    Parameters
    ----------
    max_version : str
        tmux version, e.g. '1.8'

    Returns
    -------
    bool
        True if version below max_version
    """
    return await get_version() < LooseVersion(max_version)


async def has_minimum_version(raises: bool = True) -> bool:
    """Return True if tmux meets version requirement. Version >1.8 or above (async).

    Parameters
    ----------
    raises : bool
        raise exception if below minimum version requirement

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
    .. versionchanged:: 0.7.0
        No longer returns version, returns True or False

    .. versionchanged:: 0.1.7
        Versions will now remove trailing letters per `Issue 55`_.

        .. _Issue 55: https://github.com/tmux-python/tmuxp/issues/55.
    """
    if await get_version() < LooseVersion(TMUX_MIN_VERSION):
        if raises:
            msg = (
                f"libtmux only supports tmux {TMUX_MIN_VERSION} and greater. This "
                f"system has {await get_version()} installed. Upgrade your tmux to use "
                "libtmux."
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


def handle_option_error(error: str) -> type[exc.OptionError]:
    """Raise exception if error in option command found.

    In tmux 3.0, show-option and show-window-option return invalid option instead of
    unknown option. See https://github.com/tmux/tmux/blob/3.0/cmd-show-options.c.

    In tmux >2.4, there are 3 different types of option errors:

    - unknown option
    - invalid option
    - ambiguous option

    In tmux <2.4, unknown option was the only option.

    All errors raised will have the base error of :exc:`exc.OptionError`. So to
    catch any option error, use ``except exc.OptionError``.

    Parameters
    ----------
    error : str
        Error response from subprocess call.

    Raises
    ------
    :exc:`exc.OptionError`, :exc:`exc.UnknownOption`, :exc:`exc.InvalidOption`,
    :exc:`exc.AmbiguousOption`
    """
    if "unknown option" in error:
        raise exc.UnknownOption(error)
    if "invalid option" in error:
        raise exc.InvalidOption(error)
    if "ambiguous option" in error:
        raise exc.AmbiguousOption(error)
    raise exc.OptionError(error)  # Raise generic option error


def get_libtmux_version() -> LooseVersion:
    """Return libtmux version is a PEP386 compliant format.

    Returns
    -------
    distutils.version.LooseVersion
        libtmux version
    """
    from libtmux.__about__ import __version__

    return LooseVersion(__version__)
