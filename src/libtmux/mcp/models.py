"""Pydantic models for MCP tool inputs and outputs."""

from __future__ import annotations

import typing as t

from pydantic import BaseModel, Field


class SessionInfo(BaseModel):
    """Serialized tmux session."""

    session_id: str = Field(description="Session ID (e.g. '$1')")
    session_name: str | None = Field(default=None, description="Session name")
    window_count: int = Field(description="Number of windows")
    session_attached: str | None = Field(
        default=None, description="Attached client count"
    )
    session_created: str | None = Field(default=None, description="Creation timestamp")


class WindowInfo(BaseModel):
    """Serialized tmux window."""

    window_id: str = Field(description="Window ID (e.g. '@1')")
    window_name: str | None = Field(default=None, description="Window name")
    window_index: str | None = Field(default=None, description="Window index")
    session_id: str | None = Field(default=None, description="Parent session ID")
    session_name: str | None = Field(default=None, description="Parent session name")
    pane_count: int = Field(description="Number of panes")
    window_layout: str | None = Field(default=None, description="Layout string")
    window_active: str | None = Field(
        default=None, description="Active flag ('1' or '0')"
    )
    window_width: str | None = Field(default=None, description="Width in columns")
    window_height: str | None = Field(default=None, description="Height in rows")


class PaneInfo(BaseModel):
    """Serialized tmux pane."""

    pane_id: str = Field(description="Pane ID (e.g. '%1')")
    pane_index: str | None = Field(default=None, description="Pane index")
    pane_width: str | None = Field(default=None, description="Width in columns")
    pane_height: str | None = Field(default=None, description="Height in rows")
    pane_current_command: str | None = Field(
        default=None, description="Running command"
    )
    pane_current_path: str | None = Field(
        default=None, description="Current working directory"
    )
    pane_pid: str | None = Field(default=None, description="Process ID")
    pane_title: str | None = Field(default=None, description="Pane title")
    pane_active: str | None = Field(
        default=None, description="Active flag ('1' or '0')"
    )
    window_id: str | None = Field(default=None, description="Parent window ID")
    session_id: str | None = Field(default=None, description="Parent session ID")
    is_caller: bool | None = Field(
        default=None,
        description=(
            "True if this pane is the MCP caller's own pane "
            "(detected via TMUX_PANE env var)"
        ),
    )


class PaneContentMatch(BaseModel):
    """A pane whose captured content matched a search pattern."""

    pane_id: str = Field(description="Pane ID (e.g. '%1')")
    pane_current_command: str | None = Field(
        default=None, description="Running command"
    )
    pane_current_path: str | None = Field(
        default=None, description="Current working directory"
    )
    window_id: str | None = Field(default=None, description="Parent window ID")
    window_name: str | None = Field(default=None, description="Parent window name")
    session_id: str | None = Field(default=None, description="Parent session ID")
    session_name: str | None = Field(default=None, description="Parent session name")
    matched_lines: list[str] = Field(description="Lines containing the match")
    is_caller: bool | None = Field(
        default=None,
        description=(
            "True if this pane is the MCP caller's own pane "
            "(detected via TMUX_PANE env var)"
        ),
    )


class ServerInfo(BaseModel):
    """Serialized tmux server info."""

    is_alive: bool = Field(description="Whether the server is running")
    socket_name: str | None = Field(default=None, description="Socket name")
    socket_path: str | None = Field(default=None, description="Socket path")
    session_count: int = Field(description="Number of sessions")
    version: str | None = Field(default=None, description="tmux version")


class OptionResult(BaseModel):
    """Result of a show_option call."""

    option: str = Field(description="Option name")
    value: t.Any = Field(description="Option value")


class OptionSetResult(BaseModel):
    """Result of a set_option call."""

    option: str = Field(description="Option name")
    value: str = Field(description="Value that was set")
    status: str = Field(description="Operation status")


class EnvironmentSetResult(BaseModel):
    """Result of a set_environment call."""

    name: str = Field(description="Variable name")
    value: str = Field(description="Value that was set")
    status: str = Field(description="Operation status")
