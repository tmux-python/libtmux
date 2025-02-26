"""Provide helper methods and mixins for libtmux.

This module includes helper functions for version checking, environment variable
management, tmux command execution, and other miscellaneous utilities used by
libtmux. It preserves and respects existing doctests without removal.

libtmux.common
~~~~~~~~~~~~~~
"""

from __future__ import annotations

import logging
import re
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
TMUX_MIN_VERSION = "1.8"

#: Most recent version of tmux supported
TMUX_MAX_VERSION = "3.4"

SessionDict = dict[str, t.Any]
WindowDict = dict[str, t.Any]
WindowOptionDict = dict[str, t.Any]
PaneDict = dict[str, t.Any]


class EnvironmentMixin:
    """Manage session- and server-level environment variables within tmux."""

    _add_option = None

    cmd: Callable[[t.Any, t.Any], tmux_cmd]

    def __init__(self, add_option: str | None = None) -> None:
        self._add_option = add_option

    def set_environment(self, name: str, value: str) -> None:
        """Set an environment variable via ``tmux set-environment <name> <value>``.

        Parameters
        ----------
        name : str
            Name of the environment variable (e.g. 'PATH').
        value : str
            Value of the environment variable.
        """
        args = ["set-environment"]
        if self._add_option:
            args += [self._add_option]
        args += [name, value]

        cmd = self.cmd(*args)
        if cmd.stderr:
            msg = f"tmux set-environment stderr: {cmd.stderr}"
            raise ValueError(msg)

    def unset_environment(self, name: str) -> None:
        """Unset an environment variable via ``tmux set-environment -u <name>``.

        Parameters
        ----------
        name : str
            Name of the environment variable (e.g. 'PATH').
        """
        args = ["set-environment"]
        if self._add_option:
            args += [self._add_option]
        args += ["-u", name]

        cmd = self.cmd(*args)
        if cmd.stderr:
            msg = f"tmux set-environment stderr: {cmd.stderr}"
            raise ValueError(msg)

    def remove_environment(self, name: str) -> None:
        """Remove an environment variable via ``tmux set-environment -r <name>``.

        Parameters
        ----------
        name : str
            Name of the environment variable (e.g. 'PATH').
        """
        args = ["set-environment"]
        if self._add_option:
            args += [self._add_option]
        args += ["-r", name]

        cmd = self.cmd(*args)
        if cmd.stderr:
            msg = f"tmux set-environment stderr: {cmd.stderr}"
            raise ValueError(msg)

    def show_environment(self) -> dict[str, bool | str]:
        """Show environment variables via ``tmux show-environment``.

        Returns
        -------
        dict
            Dictionary of environment variables for the session.

        .. versionchanged:: 0.13
           Removed per-item lookups. Use :meth:`.getenv` to get a single env var.
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
        """Show value of an environment variable via ``tmux show-environment <name>``.

        Parameters
        ----------
        name : str
            The environment variable name (e.g. 'PATH').

        Returns
        -------
        str or bool or None
            The environment variable value, True if set without an '=' value, or
            None if not set.

        .. versionadded:: 0.13
        """
        tmux_args: list[str | int] = ["show-environment"]
        if self._add_option:
            tmux_args += [self._add_option]
        tmux_args.append(name)

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


class tmux_cmd:
    """Execute a tmux command via :py:mod:`subprocess`.

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

    def __init__(self, *args: t.Any) -> None:
        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise exc.TmuxCommandNotFound

        cmd = [tmux_bin]
        cmd += args  # add the command arguments to cmd
        cmd = [str(c) for c in cmd]

        self.cmd = cmd
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="backslashreplace",
            )
            stdout, stderr = self.process.communicate()
            returncode = self.process.returncode
        except Exception:
            logger.exception(f"Exception for {subprocess.list2cmdline(cmd)}")
            raise

        self.returncode = returncode

        stdout_split = stdout.split("\n")
        # remove trailing newlines from stdout
        # remove trailing empty lines
        while stdout_split and stdout_split[-1] == "":
            stdout_split.pop()

        stderr_split = stderr.split("\n")
        self.stderr = list(filter(None, stderr_split))  # filter empty values

        # fix for 'has-session' command output edge cases
        if "has-session" in cmd and len(self.stderr) and not stdout_split:
            self.stdout = [self.stderr[0]]
        else:
            self.stdout = stdout_split

        logger.debug(
            "self.stdout for %s: %s",
            " ".join(cmd),
            self.stdout,
        )


def get_version() -> LooseVersion:
    """Return the installed tmux version.

    If tmux is built from git master, appends '-master', e.g. '2.4-master'.
    If using OpenBSD's base system tmux, appends '-openbsd', e.g. '2.4-openbsd'.

    Returns
    -------
    LooseVersion
        Detected tmux version.
    """
    proc = tmux_cmd("-V")
    if proc.stderr:
        if proc.stderr[0] == "tmux: unknown option -- V":
            if sys.platform.startswith("openbsd"):  # openbsd has no tmux -V
                return LooseVersion(f"{TMUX_MAX_VERSION}-openbsd")
            msg = (
                f"libtmux supports tmux {TMUX_MIN_VERSION} and greater. "
                "This system is running tmux 1.3 or earlier."
            )
            raise exc.LibTmuxException(msg)
        raise exc.VersionTooLow(proc.stderr)

    version = proc.stdout[0].split("tmux ")[1]

    # allow HEAD to be recognized
    if version == "master":
        return LooseVersion(f"{TMUX_MAX_VERSION}-master")

    version = re.sub(r"[a-z-]", "", version)
    return LooseVersion(version)


def has_version(version: str) -> bool:
    """Return True if the installed tmux version matches exactly.

    Parameters
    ----------
    version : str
        e.g. '1.8'

    Returns
    -------
    bool
        True if installed tmux matches the version exactly.
    """
    return get_version() == LooseVersion(version)


def has_gt_version(min_version: str) -> bool:
    """Return True if the installed tmux version is greater than min_version.

    Parameters
    ----------
    min_version : str
        e.g. '1.8'

    Returns
    -------
    bool
        True if version above min_version.
    """
    return get_version() > LooseVersion(min_version)


def has_gte_version(min_version: str) -> bool:
    """Return True if the installed tmux version is >= min_version.

    Parameters
    ----------
    min_version : str
        e.g. '1.8'

    Returns
    -------
    bool
        True if version is above or equal to min_version.
    """
    return get_version() >= LooseVersion(min_version)


def has_lte_version(max_version: str) -> bool:
    """Return True if the installed tmux version is <= max_version.

    Parameters
    ----------
    max_version : str
        e.g. '1.8'

    Returns
    -------
    bool
        True if version is below or equal to max_version.
    """
    return get_version() <= LooseVersion(max_version)


def has_lt_version(max_version: str) -> bool:
    """Return True if the installed tmux version is < max_version.

    Parameters
    ----------
    max_version : str
        e.g. '1.8'

    Returns
    -------
    bool
        True if version is below max_version.
    """
    return get_version() < LooseVersion(max_version)


def has_minimum_version(raises: bool = True) -> bool:
    """Return True if tmux meets the required minimum version.

    The minimum version is defined by ``TMUX_MIN_VERSION``, default '1.8'.

    Parameters
    ----------
    raises : bool, optional
        If True (default), raise an exception if below the min version.

    Returns
    -------
    bool
        True if tmux meets the minimum required version, otherwise False.

    Raises
    ------
    exc.VersionTooLow
        If `raises=True` and tmux is below the minimum required version.

    Notes
    -----
    .. versionchanged:: 0.7.0
       No longer returns version, returns True/False.
    .. versionchanged:: 0.1.7
       Versions remove trailing letters per Issue #55.
    """
    if get_version() < LooseVersion(TMUX_MIN_VERSION):
        if raises:
            msg = (
                f"libtmux only supports tmux {TMUX_MIN_VERSION} and greater. This "
                + f"system has {get_version()} installed. Upgrade your tmux to use "
                + "libtmux."
            )
            raise exc.VersionTooLow(msg)
        return False
    return True


def session_check_name(session_name: str | None) -> None:
    """Raise if session name is invalid, as tmux forbids periods/colons.

    Parameters
    ----------
    session_name : str
        The session name to validate.

    Raises
    ------
    exc.BadSessionName
        If the session name is empty, contains colons, or contains periods.
    """
    if session_name is None or len(session_name) == 0:
        raise exc.BadSessionName(reason="empty", session_name=session_name)
    if "." in session_name:
        raise exc.BadSessionName(reason="contains periods", session_name=session_name)
    if ":" in session_name:
        raise exc.BadSessionName(reason="contains colons", session_name=session_name)


def handle_option_error(error: str) -> t.NoReturn:
    """Raise appropriate exception if an option error is encountered.

    In tmux 3.0, 'show-option' or 'show-window-option' return 'invalid option'
    instead of 'unknown option'. In tmux >=2.4, there are three types of
    option errors: unknown, invalid, ambiguous.

    For older tmux (<2.4), 'unknown option' was the only possibility.

    Parameters
    ----------
    error : str
        Error string from tmux.

    Raises
    ------
    exc.UnknownOption
    exc.InvalidOption
    exc.AmbiguousOption
    exc.OptionError
    """
    if "unknown option" in error:
        raise exc.UnknownOption(error)
    if "invalid option" in error:
        raise exc.InvalidOption(error)
    if "ambiguous option" in error:
        raise exc.AmbiguousOption(error)
    raise exc.OptionError(error)


def get_libtmux_version() -> LooseVersion:
    """Return the PEP386-compliant libtmux version.

    Returns
    -------
    LooseVersion
        The libtmux version.
    """
    from libtmux.__about__ import __version__

    return LooseVersion(__version__)
