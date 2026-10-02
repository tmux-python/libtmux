"""libtmux exceptions.

libtmux.exc
~~~~~~~~~~~

"""

from __future__ import annotations

import os
import subprocess
import typing as t

from libtmux._internal.redaction import _loggable_cmd

if t.TYPE_CHECKING:
    from collections.abc import Sequence

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


class TmuxError(Exception):
    """Root of every exception libtmux defines.

    One ``except TmuxError`` catches anything libtmux raises on purpose. It has
    two children: :exc:`LibTmuxException`, for a tmux operation that failed or
    gave up, and :exc:`DeprecatedError`, for calling an API that no longer
    exists.

    The split matters to broad handlers. Code that falls back on
    ``except LibTmuxException`` ("tmux said no, try something else") must not
    also swallow :exc:`DeprecatedError`, which reports a bug in the caller, so
    that one is a sibling of :exc:`LibTmuxException`, not a child.

    Examples
    --------
    >>> from libtmux import exc
    >>> issubclass(exc.LibTmuxException, exc.TmuxError)
    True
    >>> issubclass(exc.DeprecatedError, exc.TmuxError)
    True
    >>> issubclass(exc.DeprecatedError, exc.LibTmuxException)
    False

    .. versionadded:: 0.63
    """


class LibTmuxException(TmuxError):
    """A tmux operation failed or gave up: the base of every tmux-side error.

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


class DeprecatedError(TmuxError, AttributeError):
    """Raised when a removed function, method, or parameter is used.

    This exception provides clear guidance on what to use instead.

    It is a :exc:`TmuxError` but deliberately not a :class:`LibTmuxException`.
    It reports a caller bug (code written against an API that no longer
    exists), not a tmux failure, so a broad ``except LibTmuxException``
    fallback must not swallow it.

    It is also an :class:`AttributeError`, as Python's own removed-name errors
    are (numpy's ``np.float``, a module ``__getattr__`` per :pep:`562`). That
    keeps feature detection working: ``hasattr(obj, "old")`` is ``False`` and
    ``getattr(obj, "old", default)`` returns the default, so a ladder that tries
    the new name and then the old one still runs. Reading the name directly
    raises, with the message naming the replacement.

    Examples
    --------
    >>> from libtmux.exc import DeprecatedError, LibTmuxException
    >>> issubclass(DeprecatedError, LibTmuxException)
    False
    >>> issubclass(DeprecatedError, AttributeError)
    True
    >>> str(DeprecatedError(deprecated="A.old()", replacement="A.new()", version="1.0"))
    'A.old() was deprecated in 1.0 and has been removed. Use A.new() instead.'

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


class TmuxCommandFailed(LibTmuxException):
    """tmux ran a command and did not give a usable answer.

    Raised when tmux writes to stderr (``no server running``, ``can't find
    pane``) or returns output libtmux cannot parse. This is the failure the
    lenient list accessors (:attr:`Server.sessions`, :attr:`Server.clients`)
    read as "nothing to list". They catch this class and its unreachable-server
    neighbours, not :exc:`LibTmuxException`, so a timeout or any future
    subclass of :exc:`LibTmuxException` is never mistaken for an empty server.

    Examples
    --------
    >>> from libtmux import exc
    >>> issubclass(exc.TmuxCommandFailed, exc.LibTmuxException)
    True

    .. versionadded:: 0.63
    """


class ListCommandFailed(TmuxCommandFailed):
    """A strict listing could not ask tmux for its rows.

    Raised by :meth:`Server.fetch_sessions() <libtmux.Server.fetch_sessions>`,
    :meth:`~libtmux.Server.fetch_windows` and :meth:`~libtmux.Server.fetch_panes`
    when the underlying ``list-*`` command fails: no running daemon, a missing
    socket, a permission error. The lenient accessors (``Server.sessions``)
    return an empty list in these cases; the strict methods raise so a caller
    can tell "no rows" from "tmux unreachable".

    The original error is chained as ``__cause__``.

    Parameters
    ----------
    *args : object
        Forwarded to :class:`LibTmuxException`.
    list_cmd : str, optional
        The tmux list command that failed, e.g. ``"list-sessions"``.

    Examples
    --------
    >>> from libtmux import exc
    >>> err = exc.ListCommandFailed("no server running", list_cmd="list-sessions")
    >>> err.list_cmd
    'list-sessions'
    >>> issubclass(exc.ListCommandFailed, exc.TmuxCommandFailed)
    True
    """

    def __init__(
        self,
        *args: object,
        list_cmd: str | None = None,
    ) -> None:
        super().__init__(*args, subcommand=list_cmd)
        self.list_cmd = list_cmd


class TmuxSessionExists(LibTmuxException):
    """Session does not exist in the server."""


class TmuxCommandNotFound(LibTmuxException):
    """Application binary for tmux not found."""


class TmuxCommandError(LibTmuxException):
    """tmux rejected a command that an engine ran successfully.

    Raised by :meth:`libtmux.engines.base.CommandResult.raise_for_status`. An
    engine reports a tmux-side failure as data; this is that data as an
    exception, for callers who would rather not check ``returncode``.

    Parameters
    ----------
    cmd : sequence of str
        The argv that ran.
    returncode : int
        tmux exit code.
    stderr : sequence of str
        tmux's error lines.

    Examples
    --------
    >>> from libtmux import exc
    >>> error = exc.TmuxCommandError(("tmux", "kill-window"), 1, ("no window",))
    >>> str(error), error.returncode
    ('no window', 1)
    >>> issubclass(exc.TmuxCommandError, exc.LibTmuxException)
    True
    """

    def __init__(
        self,
        cmd: Sequence[str],
        returncode: int,
        stderr: Sequence[str] = (),
    ) -> None:
        self.cmd = tuple(cmd)
        self.returncode = returncode
        self.stderr = tuple(stderr)
        super().__init__(" ".join(self.stderr) or f"tmux exited {returncode}")


class ControlModeError(LibTmuxException):
    """A control-mode connection failed."""


class EngineError(LibTmuxException):
    """An engine could not run a command: the transport failed, not tmux."""


class EngineClosed(EngineError):
    """A command reached an engine after :meth:`close` ran."""


class ControlConnectionLost(ControlModeError, EngineError):
    """The ``tmux -C`` client exited while a command was waiting for its reply.

    tmux may or may not have run the command. The message carries the tail of
    the client's stderr, where tmux reports ``server exited unexpectedly``.
    """


class ControlProtocolError(ControlModeError):
    """tmux's control-mode output is malformed or out of sequence.

    A parser never resynchronises by guessing, so a driver that sees this
    discards the connection and starts a new one.
    """


class AsyncEngineMismatch(LibTmuxException):
    """A synchronous dispatch path received an engine call that returned an awaitable.

    :class:`~libtmux.engines.base.TmuxEngine` and
    :class:`~libtmux.engines.base.SupportsCommandLine` are
    :func:`typing.runtime_checkable` :class:`typing.Protocol` classes, which
    check attribute *names* only -- never signatures or async-ness. An engine
    declared with ``async def run`` (or ``async def command_line``) still
    satisfies ``isinstance(engine, TmuxEngine)`` and reaches
    :class:`~libtmux.common.tmux_cmd`, whose dispatch is synchronous and
    cannot await it.

    Raised from what the call actually returned, not from inspecting the
    method beforehand, so it also catches a method that is not itself
    declared ``async`` but still hands back an awaitable -- an engine that
    wraps its coroutine in an :class:`asyncio.Task` or :class:`asyncio.Future`
    before returning it.

    Parameters
    ----------
    engine : object
        The engine instance whose method returned an awaitable.
    method : str
        Name of the method that returned it -- ``"run"`` or
        ``"command_line"``.
    *args : object
        Forwarded to :class:`LibTmuxException`.

    Examples
    --------
    >>> from libtmux import exc
    >>> class AsyncEngine:
    ...     async def run(self, request): ...
    ...     async def run_batch(self, requests): ...
    >>> print(  # doctest: +NORMALIZE_WHITESPACE
    ...     exc.AsyncEngineMismatch(AsyncEngine(), "run")
    ... )
    AsyncEngine.run() returned an awaitable: libtmux dispatches tmux commands
    synchronously and cannot await it. Await this engine directly from your
    own async code, or pass a synchronous engine.

    It is part of the :exc:`LibTmuxException` hierarchy:

    >>> issubclass(exc.AsyncEngineMismatch, exc.LibTmuxException)
    True

    .. versionadded:: 0.63
    """

    def __init__(self, engine: object, method: str, *args: object) -> None:
        self.engine = engine
        self.method = method
        msg = (
            f"{type(engine).__name__}.{method}() returned an awaitable: "
            "libtmux dispatches tmux commands synchronously and cannot "
            "await it. Await this engine directly from your own async "
            "code, or pass a synchronous engine."
        )
        super().__init__(msg, *args)


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
        query: t.Mapping[str, t.Any] | None = None,
    ) -> None:
        self.query: t.Mapping[str, t.Any] | None = query
        if args:
            super().__init__(*args)
            return
        msg = "No objects found"
        if query:
            msg += f": {_format_query(query)}"
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
        count: int | None = None,
        query: t.Mapping[str, t.Any] | None = None,
    ) -> None:
        self.count: int | None = count
        self.query: t.Mapping[str, t.Any] | None = query
        if args:
            super().__init__(*args)
            return
        msg = "Multiple objects returned"
        if count is not None:
            msg += f" ({count})"
        if query:
            msg += f": {_format_query(query)}"
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
    """A wait gave up: the condition it polls for was not met in time.

    Raised by :meth:`Pane.wait() <libtmux.Pane.wait>`,
    :meth:`Pane.wait_for_text() <libtmux.Pane.wait_for_text>`,
    :meth:`Pane.run() <libtmux.Pane.run>` (as :exc:`PaneRunTimeout`) and the
    ``retry_until`` test helpers. Nothing was killed: the thing being waited
    on, such as a process or a line of output, is still free to happen. Compare
    :exc:`TmuxTimeout`, where a tmux client was cut off mid-call.

    Examples
    --------
    >>> from libtmux import exc
    >>> issubclass(exc.WaitTimeout, exc.LibTmuxException)
    True
    """


class TmuxTimeout(LibTmuxException):
    """A tmux command outlived its ``timeout`` and its client was killed.

    Raised when a ``timeout`` is given, whether on
    :class:`~libtmux.engines.base.CommandRequest`, on
    :class:`~libtmux.common.tmux_cmd`, or on
    :meth:`Server.cmd() <libtmux.Server.cmd>`,
    :meth:`Session.cmd() <libtmux.Session.cmd>`,
    :meth:`Window.cmd() <libtmux.Window.cmd>` and
    :meth:`Pane.cmd() <libtmux.Pane.cmd>`, and tmux does not return within it.
    A subprocess engine kills and reaps the tmux client it spawned before this
    is raised; a control-mode engine abandons the reply and keeps its
    connection.

    A :exc:`LibTmuxException`, so one ``except TmuxError`` or
    ``except LibTmuxException`` covers it. The list accessors
    (:attr:`Server.sessions`, :attr:`Server.clients`) catch
    :exc:`TmuxCommandFailed` and its unreachable-server neighbours, not
    :exc:`LibTmuxException`: a server that has stopped answering is not an
    empty server, so a timeout passes through them.
    It is not a :exc:`WaitTimeout`, which means a helper gave up on a
    condition: here the command may or may not have taken effect.

    Only the client dies. Work the command started, such as a pane's
    foreground process or the tmux server, keeps running.

    Parameters
    ----------
    cmd : list[str]
        Full tmux command line that timed out, argv-style.
    timeout : float
        Bound, in seconds, that the command exceeded.

    Attributes
    ----------
    cmd : list[str]
        Full tmux command line that timed out, argv-style.
    timeout : float
        Bound, in seconds, that the command exceeded.

    Examples
    --------
    >>> from libtmux import exc
    >>> err = exc.TmuxTimeout(cmd=["tmux", "wait-for", "build-done"], timeout=1.5)
    >>> str(err)
    'tmux command timed out after 1.5s: tmux wait-for build-done'

    >>> err.timeout
    1.5

    >>> isinstance(err, exc.LibTmuxException)
    True

    .. versionadded:: 0.63
    """

    def __init__(self, cmd: list[str], timeout: float) -> None:
        self.cmd = cmd
        self.timeout = timeout
        super().__init__(
            f"tmux command timed out after {timeout}s: {_loggable_cmd(cmd)}"
        )


class PaneRunTimeout(WaitTimeout, TmuxTimeout):
    """:meth:`Pane.run() <libtmux.Pane.run>` outlived its ``timeout``.

    Both kinds of timeout, because :meth:`Pane.run() <libtmux.Pane.run>` is
    both: a wait for a condition (the command finishing), so it is a
    :exc:`WaitTimeout`; carried out by a bounded tmux ``wait-for`` client, so
    it is a :exc:`TmuxTimeout`, and ``except TmuxTimeout`` covers it as it
    covers :meth:`Server.cmd() <libtmux.Server.cmd>` and
    :meth:`Server.wait_for() <libtmux.Server.wait_for>`. The command itself is
    never killed. It is a subclass, not a bare timeout, because the caller
    needs two facts the bases cannot carry: the output the command had
    printed (an agent must see where a hung command stopped) and whether the
    pane's shell ever started the command.

    The command is not interrupted; it keeps running in the pane.

    Parameters
    ----------
    command : str
        The command that was sent.
    timeout : float
        The bound that expired, in seconds.
    stdout : list of str
        Lines the command had printed when the bound expired.
    cmd : list[str]
        The tmux ``wait-for`` command line that expired.
    started : bool
        False when the pane's shell never acknowledged the line.

    Attributes
    ----------
    command : str
        The command that was sent.
    stdout : list of str
        Lines the command had printed when the bound expired.
    started : bool
        False when the pane's shell never acknowledged the line: the pane is
        not at a shell prompt, or its shell cannot reach this tmux server
        (``ssh``, ``docker exec``), so it can never report back.

    Examples
    --------
    >>> from libtmux import exc
    >>> err = exc.PaneRunTimeout(
    ...     "sleep 30", 1.0, ["partial"], cmd=["tmux", "wait-for", "c"]
    ... )
    >>> str(err)
    'pane command timed out after 1.0s: sleep 30'

    >>> err.stdout, err.started
    (['partial'], True)

    >>> isinstance(err, exc.TmuxTimeout), isinstance(err, exc.WaitTimeout)
    (True, True)

    .. versionadded:: 0.63
    """

    def __init__(
        self,
        command: str,
        timeout: float,
        stdout: list[str],
        *,
        cmd: list[str],
        started: bool = True,
    ) -> None:
        self.cmd = cmd
        self.timeout = timeout
        self.command = command
        self.stdout = stdout
        self.started = started
        if started:
            msg = f"pane command timed out after {timeout}s: {command}"
        else:
            msg = (
                f"pane did not start the command within {timeout}s: it is not "
                "at a shell prompt, or its shell cannot reach this tmux server "
                f"(ssh, docker exec): {command}"
            )
        LibTmuxException.__init__(self, msg)


class PaneRunCancelled(LibTmuxException):
    """:meth:`Pane.run() <libtmux.Pane.run>` was cancelled by its caller.

    Raised when the :class:`~libtmux.run.PaneRunCancel` passed as ``cancel``
    is cancelled, from any thread, before or while the call waits. The call
    has released its tmux waiter, removed its hooks and let go of the pane's
    lock by the time this is raised.

    The command is not interrupted. If it had been typed, it keeps running in
    the pane; send ``C-c`` to stop it. Nothing was typed when ``started`` is
    False.

    Parameters
    ----------
    command : str
        The command that was sent, or would have been.
    stdout : list of str
        Lines the command had printed when the call was cancelled.
    started : bool
        False when the call was cancelled before it typed anything or before
        the pane's shell acknowledged the line.

    Examples
    --------
    >>> from libtmux import exc
    >>> err = exc.PaneRunCancelled("sleep 30", ["partial"])
    >>> str(err)
    'pane command cancelled: sleep 30'

    >>> err.stdout, err.started
    (['partial'], True)

    .. versionadded:: 0.63
    """

    def __init__(
        self,
        command: str,
        stdout: list[str],
        *,
        started: bool = True,
    ) -> None:
        self.command = command
        self.stdout = stdout
        self.started = started
        super().__init__(f"pane command cancelled: {command}")


class TmuxServerGone(LibTmuxException):
    """The tmux server was not running when a wait ended.

    Raised by :meth:`Server.wait_for() <libtmux.Server.wait_for>` when the
    server it was waiting on is gone. tmux releases every waiter when its
    server exits, exactly as if the channel had been signalled, so a wake
    alone cannot tell "the work finished" from "the server died". libtmux
    asks the server again after the wake and raises this when nobody answers.

    A channel signalled in the instant before the server exited is reported
    the same way: the server went away, whatever it had been told.

    Examples
    --------
    >>> from libtmux import exc
    >>> str(exc.TmuxServerGone("build-done"))
    'tmux server is gone; channel build-done was released by its exit'

    >>> isinstance(exc.TmuxServerGone("build-done"), exc.LibTmuxException)
    True

    .. versionadded:: 0.63
    """

    def __init__(self, channel: str) -> None:
        self.channel = channel
        super().__init__(
            f"tmux server is gone; channel {channel} was released by its exit",
        )


class TmuxServerNotRunning(TmuxServerGone, subprocess.CalledProcessError):
    """No tmux server answered :meth:`Server.raise_if_dead`.

    A :exc:`TmuxServerGone`, so it sits under :exc:`LibTmuxException` and
    ``except TmuxError`` catches it. It is also a
    :class:`subprocess.CalledProcessError`, the type
    :meth:`Server.raise_if_dead() <libtmux.Server.raise_if_dead>` raised
    before it joined this tree, so existing ``except CalledProcessError``
    handlers keep working. ``returncode`` and ``cmd`` are the failed
    ``list-sessions`` probe's.

    Parameters
    ----------
    returncode : int
        Exit status of the ``list-sessions`` probe.
    cmd : list[str]
        The probe's argv.
    output : str, optional
        The probe's standard output.
    stderr : str, optional
        tmux's own message, as :attr:`subprocess.CalledProcessError.stderr`.

    Examples
    --------
    >>> from libtmux import exc
    >>> err = exc.TmuxServerNotRunning(1, ["tmux", "list-sessions"])
    >>> str(err)
    'tmux server is not running (list-sessions exited 1)'

    >>> isinstance(err, exc.TmuxServerGone), isinstance(err, OSError)
    (True, False)

    .. versionadded:: 0.63
    """

    def __init__(
        self,
        returncode: int,
        cmd: t.Sequence[str],
        output: str | None = None,
        stderr: str | None = None,
    ) -> None:
        subprocess.CalledProcessError.__init__(
            self, returncode, list(cmd), output, stderr
        )
        self.subcommand = None
        self.channel = ""

    def __str__(self) -> str:
        """Render the probe's exit status."""
        return f"tmux server is not running (list-sessions exited {self.returncode})"


class VariableUnpackingError(LibTmuxException):
    """Error unpacking variable."""

    def __init__(self, variable: t.Any | None = None, *args: object) -> None:
        super().__init__(f"Unexpected variable: {variable!s}")


class PaneError(LibTmuxException):
    """Any type of pane related error."""


class NoActivePane(PaneError):
    """A window listed no active pane.

    tmux gives every live window one active pane, so this reports a listing
    that came back inconsistent, not a window that is merely empty.
    """

    def __init__(self, *args: object) -> None:
        super().__init__("No active pane found")


class FieldNotReported(LibTmuxException):
    """A typed field was read from an object whose listing never carried it.

    The object was built by hand, or listed before tmux knew the field.
    Calling ``refresh()`` on an object that exists reads it again.
    """

    def __init__(self, field: str, *args: object) -> None:
        self.field = field
        super().__init__(f"{field} was not reported for this object")


class PaneNotFound(PaneError):
    """Pane not found."""

    def __init__(self, pane_id: str | None = None, *args: object) -> None:
        if pane_id is not None:
            super().__init__(f"Pane not found: {pane_id}")
            return
        super().__init__("Pane not found")


class CaptureCursorError(LibTmuxException):
    """Any reason a :class:`~libtmux.capture.CaptureCursor` stopped being usable.

    Catch this to handle every cursor invalidation in one place, rather
    than enumerating malformed payloads, cross-pane replays, and pane
    lifecycle changes separately.
    """


class InvalidCaptureCursor(CaptureCursorError, ValueError):
    """Capture cursor is malformed, unreadable, or from a different pane."""


class PaneLifecycleChanged(CaptureCursorError, PaneError):
    """Pane died or was respawned, so a capture cursor no longer applies.

    The ``pane_id`` outlives the process it pointed at, so continuing
    would read a different program's output as if it were the original's.
    """


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
