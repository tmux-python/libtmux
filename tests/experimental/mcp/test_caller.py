"""Caller context: environment parsing, strict socket scoping, and surfacing.

Pure tests cover :class:`CallerContext.from_env` and the strict ``is_caller``
comparator over literal env mappings; in-process FastMCP ``Client`` tests cover
the ``get_caller_context`` tool, the ``is_caller`` instruction sentence, and (live)
the ``is_caller`` row flag against a real tmux server. No pytest-asyncio.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import ConcreteEngine, SubprocessEngine
from libtmux.experimental.mcp.vocabulary import create_session, kill_session, list_panes
from libtmux.experimental.mcp.vocabulary._bridge import SyncToAsyncEngine
from libtmux.experimental.mcp.vocabulary._caller import (
    CallerContext,
    engine_socket,
    is_strict_caller,
)
from libtmux.experimental.mcp.vocabulary._resolve import resolve_origin

fastmcp = pytest.importorskip("fastmcp")
from fastmcp.exceptions import ToolError  # noqa: E402 - after importorskip

if t.TYPE_CHECKING:
    from libtmux.session import Session


# --------------------------------------------------------------------------- #
# CallerContext.from_env (pure)
# --------------------------------------------------------------------------- #
def test_from_env_inside_tmux() -> None:
    """A full TMUX/TMUX_PANE pair parses into a populated context."""
    ctx = CallerContext.from_env(
        {"TMUX_PANE": "%3", "TMUX": "/tmp/tmux-1000/default,42,2"},
    )
    assert ctx.in_tmux
    assert ctx.pane_id == "%3"
    assert ctx.socket_path == "/tmp/tmux-1000/default"
    assert ctx.server_pid == "42"
    assert ctx.session_id == "2"


def test_from_env_outside_tmux() -> None:
    """No TMUX/TMUX_PANE yields a context with in_tmux False."""
    assert CallerContext.from_env({}).in_tmux is False


def test_from_env_malformed_tmux() -> None:
    """A malformed TMUX keeps the pane but leaves socket/pid/session None."""
    ctx = CallerContext.from_env({"TMUX_PANE": "%5", "TMUX": "garbage"})
    assert ctx.pane_id == "%5"
    assert ctx.in_tmux is True
    assert ctx.socket_path is None


# --------------------------------------------------------------------------- #
# Strict caller / engine socket (pure)
# --------------------------------------------------------------------------- #
def test_is_strict_caller_socket_scoped() -> None:
    """is_caller requires pane equality and a socket match."""
    caller = CallerContext.from_env({"TMUX_PANE": "%3", "TMUX": "/tmp/a,1,2"})
    assert is_strict_caller("%3", None, caller) is True  # default engine, same server
    assert is_strict_caller("%3", "/tmp/a", caller) is True  # same socket path
    assert is_strict_caller("%3", "/tmp/b", caller) is False  # cross-socket
    assert is_strict_caller("%9", None, caller) is False  # different pane


def test_is_strict_caller_outside_tmux() -> None:
    """Nothing is the caller when the server is not inside tmux."""
    assert is_strict_caller("%1", None, CallerContext.from_env({})) is False


def test_engine_socket_parses_server_args() -> None:
    """engine_socket reads -L name / -S path, else None for the default socket."""

    class Named:
        server_args = ("-Lwork",)

    class Pathed:
        server_args = ("-S/tmp/x",)

    class Default:
        server_args = ()

    assert engine_socket(Named()) == "work"
    assert engine_socket(Pathed()) == "/tmp/x"
    assert engine_socket(Default()) is None


# --------------------------------------------------------------------------- #
# Surfacing via the server (in-process client)
# --------------------------------------------------------------------------- #
def test_get_caller_context_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_caller_context returns the context read from the server's env."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/sock,1,3")
    server = build_async_server(SyncToAsyncEngine(ConcreteEngine()), events="off")

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return (await client.call_tool("get_caller_context", {})).data

    data = asyncio.run(main())
    assert data.pane_id == "%7"
    assert data.in_tmux is True


def test_instructions_include_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """The instructions name the caller pane when the server is inside tmux."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/sock,1,3")
    server = build_async_server(SyncToAsyncEngine(ConcreteEngine()), events="off")
    assert "%7" in (server.instructions or "")
    assert "is_caller" in (server.instructions or "")


def test_instructions_outside_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    """The instructions say so when the server is not inside tmux."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    server = build_async_server(SyncToAsyncEngine(ConcreteEngine()), events="off")
    assert "not running inside a tmux pane" in (server.instructions or "")


def test_is_caller_row_flag_live(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_panes flags the caller's own pane when env points at it."""
    engine = SubprocessEngine.for_server(session.server)
    created = create_session(engine, name="callerlive")
    try:
        pane = created.first_pane_id
        assert pane is not None
        socket = engine_socket(engine) or ""
        monkeypatch.setenv("TMUX_PANE", pane)
        monkeypatch.setenv("TMUX", f"{socket},0,0")
        flagged = [
            row["pane_id"]
            for row in list_panes(engine).rows
            if row.get("is_caller") == "1"
        ]
        assert pane in flagged
    finally:
        kill_session(engine, created.session_id)


# --------------------------------------------------------------------------- #
# resolve_origin caller-default is socket-scoped (the behavioural path)
# --------------------------------------------------------------------------- #
def test_resolve_origin_same_server_uses_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_origin trusts the caller pane when the engine shares its server."""
    monkeypatch.setenv("TMUX_PANE", "%3")
    monkeypatch.setenv("TMUX", "/tmp/a,1,2")
    engine = SyncToAsyncEngine(ConcreteEngine())  # default socket -> ambient server

    async def main() -> str:
        return await resolve_origin(engine, None, None)

    assert asyncio.run(main()) == "%3"


def test_resolve_origin_cross_server_requires_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_origin requires an explicit origin for a cross-server caller."""
    monkeypatch.setenv("TMUX_PANE", "%3")
    monkeypatch.setenv("TMUX", "/tmp/a,1,2")

    class CrossServer(SyncToAsyncEngine):
        server_args = ("-S", "/tmp/b")  # a different socket than the caller's

    engine = CrossServer(ConcreteEngine())

    async def main() -> str:
        return await resolve_origin(engine, None, None)

    # Cross-server: the env %3 is refused; the caller must name an origin.
    with pytest.raises(ToolError, match="explicit origin"):
        asyncio.run(main())
