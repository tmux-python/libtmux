"""MCP tools for tmux option management."""

from __future__ import annotations

import json
import typing as t

from libtmux.constants import OptionScope
from libtmux.mcp._utils import (
    _get_server,
    _resolve_pane,
    _resolve_session,
    _resolve_window,
    handle_tool_errors,
)

if t.TYPE_CHECKING:
    from fastmcp import FastMCP

    from libtmux.options import OptionsMixin

_SCOPE_MAP: dict[str, OptionScope] = {
    "server": OptionScope.Server,
    "session": OptionScope.Session,
    "window": OptionScope.Window,
    "pane": OptionScope.Pane,
}


def _resolve_option_target(
    socket_name: str | None,
    scope: t.Literal["server", "session", "window", "pane"] | None,
    target: str | None,
) -> tuple[OptionsMixin, OptionScope | None]:
    """Resolve the target object and scope for option operations."""
    server = _get_server(socket_name=socket_name)
    opt_scope = _SCOPE_MAP.get(scope) if scope is not None else None

    if scope is not None and opt_scope is None:
        from fastmcp.exceptions import ToolError

        valid = ", ".join(sorted(_SCOPE_MAP))
        msg = f"Invalid scope: {scope!r}. Valid: {valid}"
        raise ToolError(msg)

    if target is not None and opt_scope is None:
        from fastmcp.exceptions import ToolError

        msg = "scope is required when target is specified"
        raise ToolError(msg)

    if target is not None and opt_scope is not None:
        if opt_scope == OptionScope.Session:
            return _resolve_session(server, session_name=target), opt_scope
        if opt_scope == OptionScope.Window:
            return _resolve_window(server, window_id=target), opt_scope
        if opt_scope == OptionScope.Pane:
            return _resolve_pane(server, pane_id=target), opt_scope
    return server, opt_scope


@handle_tool_errors
def show_option(
    option: str,
    scope: t.Literal["server", "session", "window", "pane"] | None = None,
    target: str | None = None,
    global_: bool = False,
    socket_name: str | None = None,
) -> str:
    """Show a tmux option value.

    Parameters
    ----------
    option : str
        The tmux option name to query.
    scope : str, optional
        Option scope.
    target : str, optional
        Target identifier. For session scope: session name
        (e.g. 'mysession'). For window scope: window ID (e.g. '@1').
        For pane scope: pane ID (e.g. '%1'). Requires scope.
    global_ : bool
        Whether to query the global option.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        JSON with the option name and its value.
    """
    obj, opt_scope = _resolve_option_target(socket_name, scope, target)
    value = obj.show_option(option, global_=global_, scope=opt_scope)
    return json.dumps({"option": option, "value": value})


@handle_tool_errors
def set_option(
    option: str,
    value: str,
    scope: t.Literal["server", "session", "window", "pane"] | None = None,
    target: str | None = None,
    global_: bool = False,
    socket_name: str | None = None,
) -> str:
    """Set a tmux option value.

    Parameters
    ----------
    option : str
        The tmux option name to set.
    value : str
        The value to set.
    scope : str, optional
        Option scope.
    target : str, optional
        Target identifier. For session scope: session name
        (e.g. 'mysession'). For window scope: window ID (e.g. '@1').
        For pane scope: pane ID (e.g. '%1'). Requires scope.
    global_ : bool
        Whether to set the global option.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        JSON confirming the option was set.
    """
    obj, opt_scope = _resolve_option_target(socket_name, scope, target)
    obj.set_option(option, value, global_=global_, scope=opt_scope)
    return json.dumps({"option": option, "value": value, "status": "set"})


def register(mcp: FastMCP) -> None:
    """Register option tools with the MCP instance."""
    _RO = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    mcp.tool(title="Show Option", annotations=_RO)(show_option)
    mcp.tool(
        title="Set Option",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )(set_option)
