"""Helper methods and mixins for libtmux.

libtmux.common
~~~~~~~~~~~~~~

"""

import logging
import re
import shutil
import subprocess
import sys
import typing as t
from typing import Dict, Optional, Union

from . import exc
from ._compat import LooseVersion, console_to_str, str_from_console

logger = logging.getLogger(__name__)


#: Minimum version of tmux required to run libtmux
TMUX_MIN_VERSION = "1.8"

#: Most recent version of tmux supported
TMUX_MAX_VERSION = "3.4"

SessionDict = t.Dict[str, t.Any]
WindowDict = t.Dict[str, t.Any]
WindowOptionDict = t.Dict[str, t.Any]
PaneDict = t.Dict[str, t.Any]


class EnvironmentMixin:
    """Mixin for manager session and server level environment variables in tmux."""

    _add_option = None

    cmd: t.Callable[[t.Any, t.Any], "tmux_cmd"]

    def __init__(self, add_option: Optional[str] = None) -> None:
        self._add_option = add_option

    def set_environment(self, name: str, value: str) -> None:
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
            the environment variable name. such as 'PATH'.
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
            the environment variable name. such as 'PATH'.
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

    def show_environment(self) -> Dict[str, Union[bool, str]]:
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
        opts_dict: t.Dict[str, t.Union[str, bool]] = {}
        for _t in opts:
            if len(_t) == 2:
                opts_dict[_t[0]] = _t[1]
            elif len(_t) == 1:
                opts_dict[_t[0]] = True
            else:
                raise exc.VariableUnpackingError(variable=_t)

        return opts_dict

    def getenv(self, name: str) -> Optional[t.Union[str, bool]]:
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
        tmux_args: t.Tuple[t.Union[str, int], ...] = ()

        tmux_args += ("show-environment",)
        if self._add_option:
            tmux_args += (self._add_option,)
        tmux_args += (name,)
        cmd = self.cmd(*tmux_args)
        output = cmd.stdout
        opts = [tuple(item.split("=", 1)) for item in output]
        opts_dict: t.Dict[str, t.Union[str, bool]] = {}
        for _t in opts:
            if len(_t) == 2:
                opts_dict[_t[0]] = _t[1]
            elif len(_t) == 1:
                opts_dict[_t[0]] = True
            else:
                raise exc.VariableUnpackingError(variable=_t)

        return opts_dict.get(name)


class tmux_cmd:
    """Run any :term:`tmux(1)` command through :py:mod:`subprocess`.

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
        cmd = [str_from_console(c) for c in cmd]

        self.cmd = cmd

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = self.process.communicate()
            returncode = self.process.returncode
        except Exception:
            logger.exception(f"Exception for {subprocess.list2cmdline(cmd)}")
            raise

        self.returncode = returncode

        stdout_str = console_to_str(stdout)
        stdout_split = stdout_str.split("\n")
        # remove trailing newlines from stdout
        while stdout_split and stdout_split[-1] == "":
            stdout_split.pop()

        stderr_str = console_to_str(stderr)
        stderr_split = stderr_str.split("\n")
        self.stderr = list(filter(None, stderr_split))  # filter empty values

        if "has-session" in cmd and len(self.stderr) and not stdout_split:
            self.stdout = [self.stderr[0]]
        else:
            self.stdout = stdout_split

        logger.debug(
            "self.stdout for {cmd}: {stdout}".format(
                cmd=" ".join(cmd),
                stdout=self.stdout,
            ),
        )


def get_version() -> LooseVersion:
    """Return tmux version.

    If tmux is built from git master, the version returned will be the latest
    version appended with -master, e.g. ``2.4-master``.

    If using OpenBSD's base system tmux, the version will have ``-openbsd``
    appended to the latest version, e.g. ``2.4-openbsd``.

    Returns
    -------
    :class:`distutils.version.LooseVersion`
        tmux version according to :func:`shtuil.which`'s tmux
    """
    proc = tmux_cmd("-V")
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


def has_version(version: str) -> bool:
    """Return True if tmux version installed.

    Parameters
    ----------
    version : str
        version number, e.g. '1.8'

    Returns
    -------
    bool
        True if version matches
    """
    return get_version() == LooseVersion(version)


def has_gt_version(min_version: str) -> bool:
    """Return True if tmux version greater than minimum.

    Parameters
    ----------
    min_version : str
        tmux version, e.g. '1.8'

    Returns
    -------
    bool
        True if version above min_version
    """
    return get_version() > LooseVersion(min_version)


def has_gte_version(min_version: str) -> bool:
    """Return True if tmux version greater or equal to minimum.

    Parameters
    ----------
    min_version : str
        tmux version, e.g. '1.8'

    Returns
    -------
    bool
        True if version above or equal to min_version
    """
    return get_version() >= LooseVersion(min_version)


def has_lte_version(max_version: str) -> bool:
    """Return True if tmux version less or equal to minimum.

    Parameters
    ----------
    max_version : str
        tmux version, e.g. '1.8'

    Returns
    -------
    bool
         True if version below or equal to max_version
    """
    return get_version() <= LooseVersion(max_version)


def has_lt_version(max_version: str) -> bool:
    """Return True if tmux version less than minimum.

    Parameters
    ----------
    max_version : str
        tmux version, e.g. '1.8'

    Returns
    -------
    bool
        True if version below max_version
    """
    return get_version() < LooseVersion(max_version)


def has_minimum_version(raises: bool = True) -> bool:
    """Return True if tmux meets version requirement. Version >1.8 or above.

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


def session_check_name(session_name: t.Optional[str]) -> None:
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


def handle_option_error(error: str) -> t.Type[exc.OptionError]:
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
