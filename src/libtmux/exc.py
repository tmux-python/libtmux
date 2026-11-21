"""libtmux exceptions.

libtmux.exc
~~~~~~~~~~~

"""

from __future__ import annotations

import os
import typing as t

if t.TYPE_CHECKING:
    from libtmux._internal.types import StrPath
    from libtmux.neo import ListExtraArgs


def _format_query(query: t.Mapping[str, t.Any]) -> str:
    """Render a :meth:`QueryList.get` lookup back as ``key=value`` text.

    Examples
    --------
    >>> from libtmux.exc import _format_query
    >>> _format_query({"pane_id": "%0"})
    "pane_id='%0'"

    >>> _format_query({"window_name": "shared", "window_index": "1"})
    "window_name='shared', window_index='1'"

    >>> _format_query({})
    ''
    """
    return ", ".join(f"{key}={value!r}" for key, value in query.items())


class LibTmuxException(Exception):
    """Base Exception for libtmux Errors.

    Parameters
    ----------
    *args : object
        Forwarded to :class:`Exception`.
    subcommand : str, optional
        The tmux subcommand that produced this error (e.g. ``"last-window"``).
        When set, :meth:`__str__` formats as ``"<subcommand>: <stderr>"`` so
        downstream consumers see which tmux command failed.

        .. versionadded:: 0.57
    """

    def __init__(
        self,
        *args: object,
        subcommand: str | None = None,
    ) -> None:
        super().__init__(*args)
        self.subcommand = subcommand

    def __str__(self) -> str:
        """Render with optional ``"<subcommand>: …"`` prefix."""
        base = super().__str__()
        if self.subcommand is None:
            return base
        return f"{self.subcommand}: {base}"


class DeprecatedError(LibTmuxException):
    """Raised when a deprecated function, method, or parameter is used.

    This exception provides clear guidance on what to use instead.

    Parameters
    ----------
    deprecated : str
        The name of the deprecated API (e.g., "Pane.resize_pane()")
    replacement : str
        The recommended replacement API to use instead
    version : str
        The version when the API was deprecated (e.g., "0.28.0")
    """

    def __init__(
        self,
        *,
        deprecated: str,
        replacement: str,
        version: str,
    ) -> None:
        msg = (
            f"{deprecated} was deprecated in {version} and has been removed. "
            f"Use {replacement} instead."
        )
        super().__init__(msg)


class TmuxSessionExists(LibTmuxException):
    """Session does not exist in the server."""


class TmuxCommandNotFound(LibTmuxException):
    """Application binary for tmux not found."""


class TmuxTransportError(LibTmuxException):
    """Transport failed to communicate with the tmux client or server."""


class TmuxCommandTooLong(TmuxTransportError):
    """Packed command arguments exceed tmux's client message limits.

    tmux packs command arguments into a single ``MSG_COMMAND`` ``imsg`` buffer
    capped at ``16,364`` payload bytes and ``1,000`` arguments. Large payloads
    must travel over ``stdin`` instead of ``argv``.

    Parameters
    ----------
    packed_bytes : int
        Total NUL-terminated UTF-8 byte length of the packed arguments.
    argc : int
        Number of packed arguments.
    max_bytes : int
        Maximum byte payload accepted by ``MSG_COMMAND``.
    max_argc : int
        Maximum argument count accepted by ``cmd_unpack_argv``.

    Examples
    --------
    >>> from libtmux import exc
    >>> err = exc.TmuxCommandTooLong(packed_bytes=20000, argc=3)
    >>> "command too long" in str(err)
    True
    >>> issubclass(exc.TmuxCommandTooLong, exc.LibTmuxException)
    True
    """

    def __init__(
        self,
        *,
        packed_bytes: int,
        argc: int,
        max_bytes: int = 16_364,
        max_argc: int = 1_000,
    ) -> None:
        self.packed_bytes = packed_bytes
        self.argc = argc
        self.max_bytes = max_bytes
        self.max_argc = max_argc
        if argc > max_argc:
            detail = f"{argc} arguments exceeds ceiling of {max_argc}"
        else:
            detail = f"{packed_bytes} packed bytes exceeds ceiling of {max_bytes}"
        super().__init__(
            f"command too long: {detail}; pass large payloads via stdin",
        )


class TmuxCommandTimeout(TmuxTransportError):
    """A tmux client invocation exceeded its wall-clock deadline.

    Parameters
    ----------
    argv : tuple[str, ...]
        Dispatched command vector that timed out.
    timeout : float
        Configured deadline in seconds.

    Examples
    --------
    >>> from libtmux import exc
    >>> err = exc.TmuxCommandTimeout(("tmux", "wait-for", "ch"), 0.5)
    >>> err.timeout
    0.5
    """

    def __init__(self, argv: tuple[str, ...], timeout: float) -> None:
        self.argv = argv
        self.timeout = timeout
        super().__init__(
            f"tmux command timed out after {timeout}s: {' '.join(argv[:3])}",
        )


class TmuxServerRestarted(TmuxTransportError):
    """Target tmux server generation changed before a guarded request ran.

    Parameters
    ----------
    expected_pid : int
        Expected ``#{pid}`` of the target server.
    expected_start_time : int
        Expected ``#{start_time}`` of the target server.

    Examples
    --------
    >>> from libtmux import exc
    >>> err = exc.TmuxServerRestarted(1234, 1700000000)
    >>> err.expected_pid
    1234
    """

    def __init__(self, expected_pid: int, expected_start_time: int) -> None:
        self.expected_pid = expected_pid
        self.expected_start_time = expected_start_time
        super().__init__(
            f"tmux server generation changed (expected pid={expected_pid}, "
            f"start_time={expected_start_time})",
        )


class AsyncEngineMismatch(LibTmuxException):
    """Synchronous dispatch received an awaitable from an injected engine.

    :class:`~libtmux.engine.TmuxEngine` is a :func:`typing.runtime_checkable`
    :class:`typing.Protocol`, which checks attribute names rather than
    coroutine signatures. Synchronous callers cannot await an asynchronous
    ``execute()`` implementation and raise this error instead.

    Parameters
    ----------
    engine : object
        Engine instance whose method returned an awaitable.
    method : str
        Name of the method that returned an awaitable.
    *args : object
        Forwarded to :class:`LibTmuxException`.

    Examples
    --------
    >>> from libtmux import exc
    >>> class AsyncEngine:
    ...     endpoint = None
    ...     async def execute(self, request): ...
    >>> err = exc.AsyncEngineMismatch(AsyncEngine(), "execute")
    >>> "returned an awaitable" in str(err)
    True
    """

    def __init__(self, engine: object, method: str, *args: object) -> None:
        self.engine = engine
        self.method = method
        msg = (
            f"{type(engine).__name__}.{method}() returned an awaitable: "
            "libtmux dispatches tmux commands synchronously and cannot "
            "await it. Await this engine directly from async code, or pass "
            "a synchronous engine."
        )
        super().__init__(msg, *args)


class EngineConfigurationMismatch(LibTmuxException, ValueError):
    """Injected engine connection conflicts with explicit :class:`~libtmux.Server` args.

    Parameters
    ----------
    engine : object
        Injected engine whose connection cannot satisfy the server.
    reason : str
        Conflicting or unbindable configuration detail.
    server_connection : object, optional
        Connection constraints derived from the server.
    engine_connection : object, optional
        Connection reported by the injected engine.
    *args : object
        Forwarded to :class:`LibTmuxException`.

    Examples
    --------
    >>> from libtmux import exc
    >>> print(exc.EngineConfigurationMismatch(object(), "socket conflict"))
    object configuration does not satisfy Server: socket conflict
    """

    def __init__(
        self,
        engine: object,
        reason: str,
        *args: object,
        server_connection: object | None = None,
        engine_connection: object | None = None,
    ) -> None:
        self.engine = engine
        self.reason = reason
        self.server_connection = server_connection
        self.engine_connection = engine_connection
        super().__init__(
            f"{type(engine).__name__} configuration does not satisfy Server: {reason}",
            *args,
        )


class UnscriptedCommand(LibTmuxException):
    """Replay engine encountered a command absent from its recorded tape.

    Parameters
    ----------
    commands : tuple[tuple[str, ...], ...]
        Unmatched command tuple sequence.
    hint : str, optional
        Diagnostic detail (such as recorded tmux version or exhaustion count).
    *args : object
        Forwarded to :class:`LibTmuxException`.
    """

    def __init__(
        self,
        commands: tuple[tuple[str, ...], ...],
        hint: str | None = None,
        *args: object,
    ) -> None:
        self.commands = commands
        self.hint = hint
        rendered = " ; ".join(" ".join(cmd) for cmd in commands)
        detail = f" ({hint})" if hint else ""
        super().__init__(f"unscripted command: {rendered}{detail}", *args)


class NotInsideTmux(LibTmuxException):
    """Raised when the process is not running inside a tmux pane.

    tmux exports ``$TMUX`` and ``$TMUX_PANE`` into the environment of every
    pane it spawns. The ``from_env()`` family raises this when one of them is
    missing or malformed -- i.e. the caller is not (or is no longer)
    recognizable as a tmux pane's child process.

    Parameters
    ----------
    variable : str, optional
        Name of the offending environment variable, e.g. ``"TMUX"``.
    reason : str
        Why it is unusable. Defaults to ``"unset or empty"``.
    *args : object
        Forwarded to :class:`LibTmuxException`.

    Examples
    --------
    >>> from libtmux import exc
    >>> str(exc.NotInsideTmux("TMUX"))
    'Not inside a tmux pane: $TMUX is unset or empty'

    >>> str(exc.NotInsideTmux("TMUX_PANE", reason="not a pane id"))
    'Not inside a tmux pane: $TMUX_PANE is not a pane id'

    >>> str(exc.NotInsideTmux())
    'Not inside a tmux pane'

    It is part of the :exc:`LibTmuxException` hierarchy:

    >>> issubclass(exc.NotInsideTmux, exc.LibTmuxException)
    True

    .. versionadded:: 0.62
    """

    def __init__(
        self,
        variable: str | None = None,
        *args: object,
        reason: str = "unset or empty",
    ) -> None:
        if variable is None:
            super().__init__("Not inside a tmux pane", *args)
            return
        super().__init__(
            f"Not inside a tmux pane: ${variable} is {reason}",
            *args,
        )


class SocketPathTooLong(LibTmuxException):
    """A tmux socket path is longer than a UNIX socket address can hold.

    ``sun_path`` in ``struct sockaddr_un`` is a fixed-size buffer, so a path
    over the platform's limit can never be connected to, whatever the
    filesystem allows. tmux says ``error connecting to <path> (File name too
    long)``, which names the path but not how far over it is, nor which
    variable made it that long.

    The overrun is usually inherited rather than typed: a deep pytest
    ``tmp_path``, an XDG runtime dir, a nested worktree, a long
    ``$TMUX_TMPDIR``. So the message adds the numbers tmux leaves out -- how
    many bytes over the limit, and where the length came from.

    Parameters
    ----------
    socket_path : str or :class:`os.PathLike`
        The path that does not fit. Measured in bytes, as the kernel does.
    limit : int
        Bytes available for a socket path on this platform.
    *args : object
        Forwarded to :class:`LibTmuxException`.
    socket_name : str, optional
        Set when the path was *resolved* from a socket name rather than passed
        in, in which case the length came from ``$TMUX_TMPDIR``.
    env_var : str, optional
        Environment variable the directory came from, when one did.
    env_value : str, optional
        What that variable held, so the caller can see what to shorten.

    Attributes
    ----------
    socket_path : str or :class:`os.PathLike`
        The path that does not fit.
    length : int
        Length of *socket_path* in bytes.
    limit : int
        Bytes available for a socket path on this platform.
    over : int
        Bytes to cut before the path fits.
    socket_name : str or None
        Socket name the path was resolved from, if any.
    env_var : str or None
        Environment variable the directory came from, if any.
    env_value : str or None
        Value that variable held, if any.

    Examples
    --------
    >>> from libtmux import exc
    >>> print(exc.SocketPathTooLong("/tmp/" + "d" * 120 + "/sock", 107))
    Socket path is 130 bytes, 23 over the 107 byte limit: /tmp/ddd...

    A path nobody typed says where it came from, and what to shorten:

    >>> print(
    ...     exc.SocketPathTooLong(
    ...         "/tmp/" + "d" * 120 + "/tmux-1000/dev",
    ...         107,
    ...         socket_name="dev",
    ...         env_var="TMUX_TMPDIR",
    ...         env_value="/tmp/" + "d" * 120,
    ...     )
    ... )
    Socket path for socket_name='dev' is 139 bytes, 32 over the 107 byte
    limit: /tmp/ddd... Inherited from $TMUX_TMPDIR: shorten it, or pass a
    socket_path under a shorter directory.

    The numbers and the provenance are readable, for a caller that would
    rather format its own message:

    >>> e = exc.SocketPathTooLong("/tmp/" + "d" * 120 + "/sock", 107)
    >>> e.length, e.over, e.limit, e.env_var
    (130, 23, 107, None)

    It is part of the :exc:`LibTmuxException` hierarchy, so
    ``except LibTmuxException`` catches it:

    >>> issubclass(exc.SocketPathTooLong, exc.LibTmuxException)
    True

    .. versionadded:: 0.63
    """

    def __init__(
        self,
        socket_path: StrPath,
        limit: int,
        *args: object,
        socket_name: str | None = None,
        env_var: str | None = None,
        env_value: str | None = None,
    ) -> None:
        self.socket_path: StrPath = socket_path
        self.length: int = len(os.fsencode(socket_path))
        self.limit: int = limit
        self.over: int = self.length - limit
        self.socket_name: str | None = socket_name
        self.env_var: str | None = env_var
        self.env_value: str | None = env_value

        subject = "Socket path"
        if socket_name is not None:
            subject += f" for socket_name={socket_name!r}"
        message = (
            f"{subject} is {self.length} bytes, {self.over} over the "
            f"{limit} byte limit: {socket_path}"
        )
        if env_var is not None:
            message += (
                f" Inherited from ${env_var}: shorten it, or pass a "
                f"socket_path under a shorter directory."
            )
        super().__init__(message, *args)


class ObjectDoesNotExist(LibTmuxException):
    """A lookup expected one object and matched none.

    Raised by :meth:`~libtmux._internal.query_list.QueryList.get` when nothing
    matches and no ``default`` was passed.

    Parameters
    ----------
    *args : object
        A ready-made message, forwarded to :class:`LibTmuxException`. When
        omitted, the message is built from *query*.
    query : :class:`~collections.abc.Mapping`, optional
        The lookup that matched nothing, e.g. ``{"pane_id": "%99"}``.
        Annotated ``object`` so a subclass can forward ``**kwargs``.

    Examples
    --------
    >>> from libtmux import exc
    >>> str(exc.ObjectDoesNotExist())
    'No objects found'

    A lookup that named what it wanted says so:

    >>> str(exc.ObjectDoesNotExist(query={"pane_id": "%99"}))
    "No objects found: pane_id='%99'"

    It is part of the :exc:`LibTmuxException` hierarchy, so
    ``except LibTmuxException`` catches it:

    >>> issubclass(exc.ObjectDoesNotExist, exc.LibTmuxException)
    True

    .. versionchanged:: 0.62

        Re-based on :exc:`LibTmuxException` and given a message.
    """

    def __init__(
        self,
        *args: object,
        query: object = None,
    ) -> None:
        self.query = t.cast("t.Mapping[str, t.Any] | None", query)
        if args:
            super().__init__(*args)
            return
        msg = "No objects found"
        if self.query:
            msg += f": {_format_query(self.query)}"
        super().__init__(msg)


class MultipleObjectsReturned(LibTmuxException):
    """A lookup expected one object and matched several.

    Raised by :meth:`~libtmux._internal.query_list.QueryList.get`. Unlike
    :exc:`ObjectDoesNotExist`, a ``default`` does **not** suppress it: a
    ``default`` is a stand-in for an object that is *absent*, and an ambiguous
    lookup is not an absent one. Silently answering with one of several equally
    valid matches is how you end up driving the wrong pane.

    On a server-wide collection, several matches for a single id is ordinary
    and means the window is linked into more than one session. See
    :ref:`winlinks` for what to do about it.

    Parameters
    ----------
    *args : object
        A ready-made message, forwarded to :class:`LibTmuxException`. When
        omitted, the message is built from *count* and *query*.
    count : int, optional
        How many objects the lookup matched.
    query : :class:`~collections.abc.Mapping`, optional
        The lookup that matched them, e.g. ``{"pane_id": "%0"}``.
        Both are annotated ``object`` so a subclass can forward ``**kwargs``.

    Examples
    --------
    >>> from libtmux import exc
    >>> str(exc.MultipleObjectsReturned())
    'Multiple objects returned'

    A lookup that matched too much reports how much, and for what:

    >>> str(exc.MultipleObjectsReturned(count=2, query={"pane_id": "%0"}))
    "Multiple objects returned (2): pane_id='%0'"

    It is part of the :exc:`LibTmuxException` hierarchy, so
    ``except LibTmuxException`` catches it:

    >>> issubclass(exc.MultipleObjectsReturned, exc.LibTmuxException)
    True

    .. versionadded:: 0.62

        Added to :mod:`libtmux.exc` as a :exc:`LibTmuxException` subclass with
        a message.
    """

    def __init__(
        self,
        *args: object,
        count: object = None,
        query: object = None,
    ) -> None:
        self.count = t.cast("int | None", count)
        self.query = t.cast("t.Mapping[str, t.Any] | None", query)
        if args:
            super().__init__(*args)
            return
        msg = "Multiple objects returned"
        if self.count is not None:
            msg += f" ({self.count})"
        if self.query:
            msg += f": {_format_query(self.query)}"
        super().__init__(msg)


class TmuxObjectDoesNotExist(ObjectDoesNotExist):
    """tmux has no object with the id that was asked for.

    Examples
    --------
    >>> from libtmux import exc
    >>> str(exc.TmuxObjectDoesNotExist())
    'Could not find object'

    >>> str(
    ...     exc.TmuxObjectDoesNotExist(
    ...         obj_key="pane_id",
    ...         obj_id="%99",
    ...         list_cmd="list-panes",
    ...         list_extra_args=("-t", "%99"),
    ...     )
    ... )
    "Could not find pane_id=%99 for list-panes ('-t', '%99')"
    """

    def __init__(
        self,
        obj_key: str | None = None,
        obj_id: str | None = None,
        list_cmd: str | None = None,
        list_extra_args: ListExtraArgs | None = None,
        *args: object,
    ) -> None:
        if all(arg is not None for arg in [obj_key, obj_id, list_cmd, list_extra_args]):
            super().__init__(
                f"Could not find {obj_key}={obj_id} for {list_cmd} "
                f"{list_extra_args if list_extra_args is not None else ''}",
            )
            return
        super().__init__("Could not find object")

    @classmethod
    def _from_stderr(cls, stderr: str, subcommand: str) -> TmuxObjectDoesNotExist:
        """Build the error from tmux's own ``can't find ...`` message.

        Examples
        --------
        >>> str(TmuxObjectDoesNotExist._from_stderr("can't find pane: %9", "kill-pane"))
        "kill-pane: can't find pane: %9"
        """
        error = cls()
        error.args = (stderr,)
        error.subcommand = subcommand
        return error


class VersionTooLow(LibTmuxException):
    """Raised if tmux below the minimum version to use libtmux."""


class BadSessionName(LibTmuxException):
    """Disallowed session name for tmux (empty, contains periods or colons)."""

    def __init__(
        self,
        reason: str,
        session_name: str | None = None,
        *args: object,
    ) -> None:
        msg = f"Bad session name: {reason}"
        if session_name is not None:
            msg += f" (session name: {session_name})"
        super().__init__(msg)


class OptionError(LibTmuxException):
    """Root error for any error involving invalid, ambiguous or bad options."""


class UnknownOption(OptionError):
    """Option unknown to tmux show-option(s) or show-window-option(s)."""


class UnknownColorOption(UnknownOption):
    """Unknown color option."""

    def __init__(self, *args: object) -> None:
        super().__init__("Server.colors must equal 88 or 256")


class InvalidOption(OptionError):
    """Option invalid to tmux."""


class AmbiguousOption(OptionError):
    """Option that could potentially match more than one."""


class WaitTimeout(LibTmuxException):
    """Function timed out without meeting condition."""


class VariableUnpackingError(LibTmuxException):
    """Error unpacking variable."""

    def __init__(self, variable: t.Any | None = None, *args: object) -> None:
        super().__init__(f"Unexpected variable: {variable!s}")


class PaneError(LibTmuxException):
    """Any type of pane related error."""


class PaneNotFound(PaneError):
    """Pane not found."""

    def __init__(self, pane_id: str | None = None, *args: object) -> None:
        if pane_id is not None:
            super().__init__(f"Pane not found: {pane_id}")
            return
        super().__init__("Pane not found")


class WindowError(LibTmuxException):
    """Any type of window related error."""


class MultipleActiveWindows(WindowError):
    """Multiple active windows."""

    def __init__(self, count: int, *args: object) -> None:
        super().__init__(f"Multiple active windows: {count} found")


class NoActiveWindow(WindowError):
    """No active window found."""

    def __init__(self, *args: object) -> None:
        super().__init__("No active windows found")


class NoWindowsExist(WindowError):
    """No windows exist for object."""

    def __init__(self, *args: object) -> None:
        super().__init__("No windows exist for object")


class AdjustmentDirectionRequiresAdjustment(LibTmuxException, ValueError):
    """If *adjustment_direction* is set, *adjustment* must be set."""

    def __init__(self) -> None:
        super().__init__("adjustment_direction requires adjustment")


class WindowAdjustmentDirectionRequiresAdjustment(
    WindowError,
    AdjustmentDirectionRequiresAdjustment,
):
    """ValueError for :meth:`libtmux.Window.resize_window`."""


class PaneAdjustmentDirectionRequiresAdjustment(
    WindowError,
    AdjustmentDirectionRequiresAdjustment,
):
    """ValueError for :meth:`libtmux.Pane.resize_pane`."""


class RequiresDigitOrPercentage(LibTmuxException, ValueError):
    """Requires digit (int or str digit) or a percentage."""

    def __init__(self) -> None:
        super().__init__("Requires digit (int or str digit) or a percentage.")
