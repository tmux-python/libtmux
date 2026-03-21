"""MCP tools for tmux environment variable management."""

from __future__ import annotations

import json
import typing as t

from libtmux.mcp._utils import (
    ANNOTATIONS_MUTATING,
    ANNOTATIONS_RO,
    TAG_MUTATING,
    TAG_READONLY,
    _get_server,
    _resolve_session,
    handle_tool_errors,
)
from libtmux.mcp.models import EnvironmentSetResult

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


@handle_tool_errors
def show_environment(
    session_name: str | None = None,
    session_id: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Show tmux environment variables.

    Parameters
    ----------
    session_name : str, optional
        Session name to query environment for.
    session_id : str, optional
        Session ID to query environment for.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        JSON dict of environment variables.
    """
    server = _get_server(socket_name=socket_name)

    if session_name is not None or session_id is not None:
        session = _resolve_session(
            server,
            session_name=session_name,
            session_id=session_id,
        )
        env_dict = session.show_environment()
    else:
        env_dict = server.show_environment()

    return json.dumps(env_dict)


@handle_tool_errors
def set_environment(
    name: str,
    value: str,
    session_name: str | None = None,
    session_id: str | None = None,
    socket_name: str | None = None,
) -> EnvironmentSetResult:
    """Set a tmux environment variable.

    Parameters
    ----------
    name : str
        Environment variable name.
    value : str
        Environment variable value.
    session_name : str, optional
        Session name to set environment for.
    session_id : str, optional
        Session ID to set environment for.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    EnvironmentSetResult
        Confirmation with variable name, value, and status.
    """
    server = _get_server(socket_name=socket_name)

    if session_name is not None or session_id is not None:
        session = _resolve_session(
            server,
            session_name=session_name,
            session_id=session_id,
        )
        session.set_environment(name, value)
    else:
        server.set_environment(name, value)

    return EnvironmentSetResult(name=name, value=value, status="set")


def register(mcp: FastMCP) -> None:
    """Register environment tools with the MCP instance."""
    mcp.tool(title="Show Environment", annotations=ANNOTATIONS_RO, tags={TAG_READONLY})(
        show_environment
    )
    mcp.tool(
        title="Set Environment", annotations=ANNOTATIONS_MUTATING, tags={TAG_MUTATING}
    )(set_environment)
