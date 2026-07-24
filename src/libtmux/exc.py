"""libtmux exceptions.

libtmux.exc
~~~~~~~~~~~

"""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
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
            return super().__init__("Not inside a tmux pane", *args)
        return super().__init__(
            f"Not inside a tmux pane: ${variable} is {reason}",
            *args,
        )


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
            return super().__init__(
                f"Could not find {obj_key}={obj_id} for {list_cmd} "
                f"{list_extra_args if list_extra_args is not None else ''}",
            )
        return super().__init__("Could not find object")


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
        return super().__init__(msg)


class OptionError(LibTmuxException):
    """Root error for any error involving invalid, ambiguous or bad options."""


class UnknownOption(OptionError):
    """Option unknown to tmux show-option(s) or show-window-option(s)."""


class UnknownColorOption(UnknownOption):
    """Unknown color option."""

    def __init__(self, *args: object) -> None:
        return super().__init__("Server.colors must equal 88 or 256")


class InvalidOption(OptionError):
    """Option invalid to tmux."""


class AmbiguousOption(OptionError):
    """Option that could potentially match more than one."""


class WaitTimeout(LibTmuxException):
    """Function timed out without meeting condition."""


class VariableUnpackingError(LibTmuxException):
    """Error unpacking variable."""

    def __init__(self, variable: object | None = None, *args: object) -> None:
        return super().__init__(f"Unexpected variable: {variable!s}")


class PaneError(LibTmuxException):
    """Any type of pane related error."""


class PaneNotFound(PaneError):
    """Pane not found."""

    def __init__(self, pane_id: str | None = None, *args: object) -> None:
        if pane_id is not None:
            return super().__init__(f"Pane not found: {pane_id}")
        return super().__init__("Pane not found")


class WindowError(LibTmuxException):
    """Any type of window related error."""


class MultipleActiveWindows(WindowError):
    """Multiple active windows."""

    def __init__(self, count: int, *args: object) -> None:
        return super().__init__(f"Multiple active windows: {count} found")


class NoActiveWindow(WindowError):
    """No active window found."""

    def __init__(self, *args: object) -> None:
        return super().__init__("No active windows found")


class NoWindowsExist(WindowError):
    """No windows exist for object."""

    def __init__(self, *args: object) -> None:
        return super().__init__("No windows exist for object")


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
