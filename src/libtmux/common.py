"""Helper methods and mixins for libtmux.

libtmux.common
~~~~~~~~~~~~~~

"""

from __future__ import annotations

import functools
import logging
import pathlib
import re
import shlex
import sys
import typing as t

from . import exc
from ._compat import LooseVersion
from .engines import (
    CommandRequest,
    CommandResult,
    EngineKind,
    EngineLike,
    EngineSpec,
    ImsgEngineName,
    ImsgProtocolHint,
    SubprocessEngineName,
    TmuxEngine,
    create_engine,
)
from .engines.imsg import ImsgEngine
from .engines.subprocess import SubprocessEngine

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


_default_engine: TmuxEngine = SubprocessEngine()


def _apply_result(target: tmux_cmd | None, result: CommandResult) -> tmux_cmd:
    cmd_obj: tmux_cmd = object.__new__(tmux_cmd) if target is None else target

    cmd_obj.cmd = list(result.cmd)
    cmd_obj.stdout = result.stdout
    cmd_obj.stderr = result.stderr
    cmd_obj.returncode = result.returncode
    cmd_obj.process = result.process

    return cmd_obj


class tmux_cmd:
    """Run any :term:`tmux(1)` command through the configured engine.

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

    cmd: list[str]
    stdout: list[str]
    stderr: list[str]
    returncode: int
    process: object | None

    @t.overload
    def __init__(
        self,
        *args: t.Any,
        tmux_bin: str | pathlib.Path | None = None,
        engine: None = None,
        protocol_version: None = None,
    ) -> None: ...

    @t.overload
    def __init__(
        self,
        *args: t.Any,
        tmux_bin: str | pathlib.Path | None = None,
        engine: SubprocessEngineName,
        protocol_version: None = None,
    ) -> None: ...

    @t.overload
    def __init__(
        self,
        *args: t.Any,
        tmux_bin: str | pathlib.Path | None = None,
        engine: ImsgEngineName,
        protocol_version: ImsgProtocolHint | None = None,
    ) -> None: ...

    @t.overload
    def __init__(
        self,
        *args: t.Any,
        tmux_bin: str | pathlib.Path | None = None,
        engine: EngineSpec | TmuxEngine,
        protocol_version: None = None,
    ) -> None: ...

    def __init__(
        self,
        *args: t.Any,
        tmux_bin: str | pathlib.Path | None = None,
        engine: EngineLike = None,
        protocol_version: ImsgProtocolHint | None = None,
    ) -> None:
        resolved_engine = _resolve_engine_impl(
            engine,
            protocol_version=protocol_version,
        )
        request = CommandRequest.from_args(*args, tmux_bin=tmux_bin)
        cmd_preview = [request.tmux_bin or "tmux", *request.args]

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "tmux command dispatched",
                extra={"tmux_cmd": shlex.join(cmd_preview)},
            )

        result = resolved_engine.run(request)
        _apply_result(self, result)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "tmux command completed",
                extra={
                    "tmux_cmd": shlex.join(self.cmd),
                    "tmux_exit_code": self.returncode,
                    "tmux_stdout": self.stdout[:100],
                    "tmux_stderr": self.stderr[:100],
                    "tmux_stdout_len": len(self.stdout),
                    "tmux_stderr_len": len(self.stderr),
                },
            )

    @classmethod
    def from_result(cls, result: CommandResult) -> tmux_cmd:
        """Create a :class:`tmux_cmd` from a raw engine result."""
        return _apply_result(None, result)

    @classmethod
    @t.overload
    def from_request(
        cls,
        request: CommandRequest,
        *,
        engine: None = None,
        protocol_version: None = None,
    ) -> tmux_cmd: ...

    @classmethod
    @t.overload
    def from_request(
        cls,
        request: CommandRequest,
        *,
        engine: SubprocessEngineName,
        protocol_version: None = None,
    ) -> tmux_cmd: ...

    @classmethod
    @t.overload
    def from_request(
        cls,
        request: CommandRequest,
        *,
        engine: ImsgEngineName,
        protocol_version: ImsgProtocolHint | None = None,
    ) -> tmux_cmd: ...

    @classmethod
    @t.overload
    def from_request(
        cls,
        request: CommandRequest,
        *,
        engine: EngineSpec | TmuxEngine,
        protocol_version: None = None,
    ) -> tmux_cmd: ...

    @classmethod
    def from_request(
        cls,
        request: CommandRequest,
        *,
        engine: EngineLike = None,
        protocol_version: ImsgProtocolHint | None = None,
    ) -> tmux_cmd:
        """Create a :class:`tmux_cmd` by executing a prepared request."""
        resolved_engine = _resolve_engine_impl(
            engine,
            protocol_version=protocol_version,
        )
        return cls.from_result(resolved_engine.run(request))


def get_default_engine() -> TmuxEngine:
    """Return the global default engine."""
    return _default_engine


def set_default_engine(engine: TmuxEngine) -> None:
    """Override the global default engine."""
    global _default_engine
    _default_engine = engine


def _normalize_protocol_version(
    protocol_version: ImsgProtocolHint | None,
) -> int | None:
    """Return a numeric protocol version when one was provided."""
    return int(protocol_version) if protocol_version is not None else None


def _spec_from_engine_instance(engine: TmuxEngine) -> EngineSpec | None:
    """Infer a typed engine spec from a concrete engine instance."""
    if isinstance(engine, SubprocessEngine):
        return EngineSpec.subprocess()
    if isinstance(engine, ImsgEngine):
        protocol = _normalize_protocol_version(engine.protocol_version)
        return EngineSpec.imsg(protocol)
    return None


@t.overload
def resolve_engine_spec(
    engine: None = None,
    *,
    protocol_version: None = None,
) -> EngineSpec | None: ...


@t.overload
def resolve_engine_spec(
    engine: SubprocessEngineName,
    *,
    protocol_version: None = None,
) -> EngineSpec: ...


@t.overload
def resolve_engine_spec(
    engine: ImsgEngineName,
    *,
    protocol_version: ImsgProtocolHint | None = None,
) -> EngineSpec: ...


@t.overload
def resolve_engine_spec(
    engine: EngineSpec,
    *,
    protocol_version: None = None,
) -> EngineSpec: ...


@t.overload
def resolve_engine_spec(
    engine: TmuxEngine,
    *,
    protocol_version: None = None,
) -> EngineSpec | None: ...


def resolve_engine_spec(
    engine: EngineLike = None,
    *,
    protocol_version: ImsgProtocolHint | None = None,
) -> EngineSpec | None:
    """Normalize a public engine selection into an :class:`EngineSpec`."""
    return _resolve_engine_spec_impl(engine, protocol_version=protocol_version)


def _resolve_engine_spec_impl(
    engine: EngineLike = None,
    *,
    protocol_version: ImsgProtocolHint | None = None,
) -> EngineSpec | None:
    """Normalize a public engine selection into an :class:`EngineSpec`."""
    if isinstance(engine, EngineSpec):
        if protocol_version is not None:
            msg = "protocol_version cannot be combined with EngineSpec"
            raise ValueError(msg)
        return engine
    if engine is None:
        if protocol_version is not None:
            msg = "protocol_version requires an explicit imsg engine selection"
            raise ValueError(msg)
        return _spec_from_engine_instance(_default_engine)
    if isinstance(engine, str):
        try:
            kind = EngineKind(engine)
        except ValueError as error:
            msg = f"Unknown tmux engine: {engine}"
            raise exc.LibTmuxException(msg) from error
        if kind is not EngineKind.IMSG and protocol_version is not None:
            msg = "protocol_version is only valid for the imsg engine"
            raise ValueError(msg)
        resolved_protocol = _normalize_protocol_version(protocol_version)
        return EngineSpec(kind=kind, protocol_version=resolved_protocol)
    if protocol_version is not None:
        msg = "protocol_version cannot be combined with a concrete engine instance"
        raise ValueError(msg)
    return _spec_from_engine_instance(engine)


@t.overload
def resolve_engine(
    engine: None = None,
    *,
    protocol_version: None = None,
) -> TmuxEngine: ...


@t.overload
def resolve_engine(
    engine: SubprocessEngineName,
    *,
    protocol_version: None = None,
) -> SubprocessEngine: ...


@t.overload
def resolve_engine(
    engine: ImsgEngineName,
    *,
    protocol_version: ImsgProtocolHint | None = None,
) -> ImsgEngine: ...


@t.overload
def resolve_engine(
    engine: EngineSpec,
    *,
    protocol_version: None = None,
) -> TmuxEngine: ...


@t.overload
def resolve_engine(
    engine: TmuxEngine,
    *,
    protocol_version: None = None,
) -> TmuxEngine: ...


def resolve_engine(
    engine: EngineLike = None,
    *,
    protocol_version: ImsgProtocolHint | None = None,
) -> TmuxEngine:
    """Resolve a concrete engine instance from a public spec."""
    return _resolve_engine_impl(engine, protocol_version=protocol_version)


def _resolve_engine_impl(
    engine: EngineLike = None,
    *,
    protocol_version: ImsgProtocolHint | None = None,
) -> TmuxEngine:
    """Resolve a concrete engine instance from a public spec."""
    engine_spec = _resolve_engine_spec_impl(engine, protocol_version=protocol_version)
    if engine is None:
        return _default_engine
    if isinstance(engine, EngineSpec):
        assert engine_spec is not None
        return create_engine(
            engine_spec.kind,
            protocol_version=engine_spec.protocol_version,
        )
    if isinstance(engine, str):
        assert engine_spec is not None
        return create_engine(
            engine_spec.kind,
            protocol_version=engine_spec.protocol_version,
        )
    return engine


@functools.lru_cache(maxsize=8)
def get_version(tmux_bin: str | None = None) -> LooseVersion:
    """Return tmux version.

    If tmux is built from git master, the version returned will be the latest
    version appended with -master, e.g. ``2.4-master``.

    If using OpenBSD's base system tmux, the version will have ``-openbsd``
    appended to the latest version, e.g. ``2.4-openbsd``.

    The version is memoized per ``tmux_bin`` value: ``tmux -V`` runs once per
    distinct binary path within a process. Use ``get_version.cache_clear()``
    when test fixtures swap the tmux binary or stub :func:`tmux_cmd`. Errors
    are not cached, so a transient failure does not poison the lookup.

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
    """
    proc = tmux_cmd("-V", tmux_bin=tmux_bin)
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
