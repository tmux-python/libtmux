"""Constant variables for libtmux."""
import enum
import typing as t


class _DefaultScope:
    # Sentinel value for default scope
    ...


DEFAULT_SCOPE: _DefaultScope = _DefaultScope()


class OptionScope(enum.Enum):
    """Scope used with ``set-option`` and ``show-option(s)`` commands."""

    Server = "SERVER"
    Session = "SESSION"
    Window = "WINDOW"
    Pane = "PANE"


OPTION_SCOPE_FLAG_MAP: t.Dict[OptionScope, str] = {
    OptionScope.Server: "-s",
    OptionScope.Session: "",
    OptionScope.Window: "-w",
    OptionScope.Pane: "-p",
}
