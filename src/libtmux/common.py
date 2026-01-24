"""Helper methods and mixins for libtmux.

libtmux.common
~~~~~~~~~~~~~~

"""

from __future__ import annotations

import contextlib
import logging
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import typing as t

from . import exc
from ._compat import LooseVersion
from ._internal import trace as libtmux_trace

if t.TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


#: Minimum version of tmux required to run libtmux
TMUX_MIN_VERSION = "3.2a"

#: Most recent version of tmux supported
TMUX_MAX_VERSION = "3.6"

SessionDict = dict[str, t.Any]
WindowDict = dict[str, t.Any]
WindowOptionDict = dict[str, t.Any]
PaneDict = dict[str, t.Any]

_RUST_BACKEND = os.getenv("LIBTMUX_BACKEND") == "rust"
_RUST_SERVER_CACHE: dict[
    tuple[str | None, str | None, int | None, str | None, str | None, bool | None],
    t.Any,
] = {}
_RUST_SERVER_CONFIG: dict[
    tuple[str | None, str | None, int | None, str | None, str | None, bool | None],
    set[str],
] = {}


def _resolve_rust_socket_path(socket_path: str | None, socket_name: str | None) -> str:
    if socket_path:
        return socket_path
    uid = os.geteuid()
    name = socket_name or "default"
    base = (
        os.getenv("TMUX_TMPDIR")
        or os.getenv("XDG_RUNTIME_DIR")
        or f"/run/user/{uid}"
        or "/tmp"
    )
    base_path = pathlib.Path(base)
    socket_dir = base_path / f"tmux-{uid}"
    socket_dir.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        socket_dir.chmod(0o700)
    return str(socket_dir / name)


def _env_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def _rust_run_with_config(
    socket_path: str | None,
    socket_name: str | None,
    config_file: str,
    cmd_parts: list[str],
    cmd_list: list[str],
) -> tuple[list[str], list[str], int, list[str]]:
    with libtmux_trace.span(
        "rust_run_with_config",
        layer="tmux-bin",
        cmd=" ".join(cmd_parts),
        socket_name=socket_name,
        socket_path=socket_path,
        config_file=config_file,
    ):
        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise exc.TmuxCommandNotFound
        resolved_socket = _resolve_rust_socket_path(socket_path, socket_name)
        process = subprocess.Popen(
            [tmux_bin, "-S", resolved_socket, "-f", config_file, *cmd_parts],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="backslashreplace",
        )
        stdout_raw, stderr_raw = process.communicate()
        stdout_lines = stdout_raw.split("\n") if stdout_raw else []
        while stdout_lines and stdout_lines[-1] == "":
            stdout_lines.pop()
        stderr_lines = list(filter(None, stderr_raw.split("\n"))) if stderr_raw else []
        if "has-session" in cmd_list and stderr_lines and not stdout_lines:
            stdout_lines = [stderr_lines[0]]
        return stdout_lines, stderr_lines, process.returncode, cmd_list


def _parse_tmux_args(args: tuple[t.Any, ...]) -> tuple[
    str | None, str | None, str | None, int | None, list[str]
]:
    socket_name: str | None = None
    socket_path: str | None = None
    config_file: str | None = None
    colors: int | None = None
    cmd_parts: list[str] = []
    parsing_globals = True

    idx = 0
    while idx < len(args):
        arg = str(args[idx])
        if parsing_globals and arg == "--":
            parsing_globals = False
            idx += 1
            continue
        if parsing_globals and arg.startswith("-L") and len(arg) > 2:
            socket_name = arg[2:]
            idx += 1
            continue
        if parsing_globals and arg == "-L" and idx + 1 < len(args):
            socket_name = str(args[idx + 1])
            idx += 2
            continue
        if parsing_globals and arg.startswith("-S") and len(arg) > 2:
            socket_path = arg[2:]
            idx += 1
            continue
        if parsing_globals and arg == "-S" and idx + 1 < len(args):
            socket_path = str(args[idx + 1])
            idx += 2
            continue
        if parsing_globals and arg.startswith("-f") and len(arg) > 2:
            config_file = arg[2:]
            idx += 1
            continue
        if parsing_globals and arg == "-f" and idx + 1 < len(args):
            config_file = str(args[idx + 1])
            idx += 2
            continue
        if parsing_globals and arg == "-2":
            colors = 256
            idx += 1
            continue
        if parsing_globals and arg == "-8":
            colors = 88
            idx += 1
            continue
        if parsing_globals:
            parsing_globals = False
        cmd_parts.append(arg)
        idx += 1

    return socket_name, socket_path, config_file, colors, cmd_parts


def _rust_server(
    socket_name: str | None,
    socket_path: str | None,
    colors: int | None,
) -> t.Any:
    connection_kind = os.getenv("LIBTMUX_RUST_CONNECTION_KIND")
    server_kind = os.getenv("LIBTMUX_RUST_SERVER_KIND")
    control_autostart = _env_bool("LIBTMUX_RUST_CONTROL_AUTOSTART")
    key = (
        socket_name,
        socket_path,
        colors,
        connection_kind,
        server_kind,
        control_autostart,
    )
    server = _RUST_SERVER_CACHE.get(key)
    if server is None:
        from libtmux import _rust as rust_backend

        kwargs: dict[str, t.Any] = {}
        if connection_kind:
            kwargs["connection_kind"] = connection_kind
        if server_kind:
            kwargs["server_kind"] = server_kind
        if control_autostart is not None:
            kwargs["control_autostart"] = control_autostart
        with libtmux_trace.span(
            "rust_server_init",
            layer="python",
            socket_name=socket_name,
            socket_path=socket_path,
            connection_kind=connection_kind,
            server_kind=server_kind,
            control_autostart=control_autostart,
        ):
            server = rust_backend.Server(
                socket_path=socket_path,
                socket_name=socket_name,
                **kwargs,
            )
        _RUST_SERVER_CACHE[key] = server
        _RUST_SERVER_CONFIG[key] = set()

    return server


def _rust_cmd_result(
    args: tuple[t.Any, ...],
) -> tuple[list[str], list[str], int, list[str]]:
    socket_name, socket_path, config_file, colors, cmd_parts = _parse_tmux_args(args)
    cmd_list = [str(c) for c in args]
    if not cmd_parts:
        return [], [], 0, cmd_list
    if cmd_parts == ["-V"]:
        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise exc.TmuxCommandNotFound
        process = subprocess.Popen(
            [tmux_bin, "-V"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="backslashreplace",
        )
        stdout_raw, stderr_raw = process.communicate()
        stdout = stdout_raw.split("\n") if stdout_raw else []
        while stdout and stdout[-1] == "":
            stdout.pop()
        stderr = list(filter(None, stderr_raw.split("\n"))) if stderr_raw else []
        return stdout, stderr, process.returncode, cmd_list

    connection_kind = os.getenv("LIBTMUX_RUST_CONNECTION_KIND")
    server_kind = os.getenv("LIBTMUX_RUST_SERVER_KIND")
    control_autostart = _env_bool("LIBTMUX_RUST_CONTROL_AUTOSTART")
    with libtmux_trace.span(
        "rust_cmd_result",
        layer="python",
        cmd=" ".join(cmd_parts),
        socket_name=socket_name,
        socket_path=socket_path,
        config_file=config_file,
        connection_kind=connection_kind,
        server_kind=server_kind,
        control_autostart=control_autostart,
    ):
        if connection_kind in {"bin", "tmux-bin"} and config_file:
            cmd_parts = ["-f", config_file, *cmd_parts]
            config_file = None

        server = _rust_server(socket_name, socket_path, colors)
        key = (
            socket_name,
            socket_path,
            colors,
            connection_kind,
            server_kind,
            control_autostart,
        )
        if config_file:
            loaded = _RUST_SERVER_CONFIG.setdefault(key, set())
            if config_file not in loaded:
                with libtmux_trace.span("rust_server_is_alive", layer="rust"):
                    server_alive = bool(server.is_alive())
                if not server_alive:
                    stdout_lines, stderr_lines, exit_code, cmd_args = (
                        _rust_run_with_config(
                            socket_path,
                            socket_name,
                            config_file,
                            cmd_parts,
                            cmd_list,
                        )
                    )
                    if exit_code == 0:
                        loaded.add(config_file)
                    return stdout_lines, stderr_lines, exit_code, cmd_args
                quoted = shlex.quote(config_file)
                try:
                    with libtmux_trace.span(
                        "rust_server_source_file",
                        layer="rust",
                        config_file=config_file,
                    ):
                        server.cmd(f"source-file {quoted}")
                except Exception as err:
                    message = str(err)
                    error_stdout: list[str] = []
                    error_stderr = [message] if message else []
                    if "has-session" in cmd_list and error_stderr and not error_stdout:
                        error_stdout = [error_stderr[0]]
                    return error_stdout, error_stderr, 1, cmd_list
                loaded.add(config_file)

        cmd_line = " ".join(shlex.quote(part) for part in cmd_parts)
        try:
            with libtmux_trace.span(
                "rust_server_cmd",
                layer="rust",
                cmd=cmd_line,
                socket_name=socket_name,
                socket_path=socket_path,
                config_file=config_file,
                connection_kind=connection_kind,
            ):
                result = server.cmd(cmd_line)
        except Exception as err:
            message = str(err)
            error_stdout_lines: list[str] = []
            error_stderr_lines = [message] if message else []
            if (
                "has-session" in cmd_list
                and error_stderr_lines
                and not error_stdout_lines
            ):
                error_stdout_lines = [error_stderr_lines[0]]
            return error_stdout_lines, error_stderr_lines, 1, cmd_list

    stdout_lines = result.stdout.split("\n") if result.stdout else []
    while stdout_lines and stdout_lines[-1] == "":
        stdout_lines.pop()
    stderr_raw = getattr(result, "exit_message", None) or ""
    stderr_lines = list(filter(None, stderr_raw.split("\n"))) if stderr_raw else []
    if "has-session" in cmd_list and stderr_lines and not stdout_lines:
        stdout_lines = [stderr_lines[0]]
    return stdout_lines, stderr_lines, result.exit_code, cmd_list


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

    def set_environment(self, name: str, value: str) -> None:
        """Set environment ``$ tmux set-environment <name> <value>``.

        Parameters
        ----------
        name : str
            The environment variable name, e.g. 'PATH'.
        value : str
            Environment value.

        Raises
        ------
        ValueError
            If tmux returns an error.
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
        if _RUST_BACKEND:
            with libtmux_trace.span("tmux_cmd", layer="python", backend="rust"):
                stdout, stderr, returncode, cmd = _rust_cmd_result(args)
                self.cmd = cmd
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr
                return

        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise exc.TmuxCommandNotFound

        cmd = [tmux_bin]
        cmd += args  # add the command arguments to cmd
        cmd = [str(c) for c in cmd]

        self.cmd = cmd

        try:
            with libtmux_trace.span(
                "tmux_cmd",
                layer="tmux-bin",
                backend="tmux-bin",
                cmd=" ".join(cmd),
            ):
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors="backslashreplace",
                )
                stdout_text, stderr_text = self.process.communicate()
                returncode = self.process.returncode
        except Exception:
            logger.exception(f"Exception for {subprocess.list2cmdline(cmd)}")
            raise

        self.returncode = returncode

        stdout_split = stdout_text.split("\n")
        # remove trailing newlines from stdout
        while stdout_split and stdout_split[-1] == "":
            stdout_split.pop()

        stderr_split = stderr_text.split("\n")
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
                " does not meet the minimum tmux version requirement."
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
        version number, e.g. '3.2a'

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
        tmux version, e.g. '3.2a'

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
        tmux version, e.g. '3.2a'

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
        tmux version, e.g. '3.2a'

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
        tmux version, e.g. '3.2a'

    Returns
    -------
    bool
        True if version below max_version
    """
    return get_version() < LooseVersion(max_version)


def has_minimum_version(raises: bool = True) -> bool:
    """Return True if tmux meets version requirement. Version >= 3.2a.

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
    .. versionchanged:: 0.49.0
        Minimum version bumped to 3.2a. For older tmux, use libtmux v0.48.x.

    .. versionchanged:: 0.7.0
        No longer returns version, returns True or False

    .. versionchanged:: 0.1.7
        Versions will now remove trailing letters per
        `Issue 55 <https://github.com/tmux-python/tmuxp/issues/55>`_.
    """
    if get_version() < LooseVersion(TMUX_MIN_VERSION):
        if raises:
            msg = (
                f"libtmux only supports tmux {TMUX_MIN_VERSION} and greater. This "
                f"system has {get_version()} installed. Upgrade your tmux to use "
                "libtmux, or use libtmux v0.48.x for older tmux versions."
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
