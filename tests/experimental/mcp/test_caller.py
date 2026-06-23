"""Caller context: environment parsing, strict socket scoping, and surfacing.

Pure tests cover :class:`CallerContext.from_env` and the strict ``is_caller``
comparator over literal env mappings; in-process FastMCP ``Client`` tests cover
the ``get_caller_context`` tool, the ``is_caller`` instruction sentence, and (live)
the ``is_caller`` row flag against a real tmux server. No pytest-asyncio.
"""

from __future__ import annotations

import asyncio
import dataclasses
import typing as t

import pytest

from libtmux.experimental.engines import ConcreteEngine, SubprocessEngine
from libtmux.experimental.mcp.vocabulary import (
    create_session,
    kill_pane,
    kill_session,
    kill_window,
    list_panes,
    respawn_pane,
)
from libtmux.experimental.mcp.vocabulary._bridge import SyncToAsyncEngine
from libtmux.experimental.mcp.vocabulary._caller import (
    CallerContext,
    caller_server_args,
    engine_socket,
    is_strict_caller,
    socket_could_match,
    socket_matches,
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
    # Disable the /proc parent walk so a test runner inside tmux is not discovered.
    monkeypatch.setenv("LIBTMUX_MCP_DISCOVER", "0")
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
        real_socket = session.server.cmd(
            "display-message", "-p", "#{socket_path}"
        ).stdout[0]
        monkeypatch.setenv("TMUX_PANE", pane)
        monkeypatch.setenv("TMUX", f"{real_socket},0,0")
        flagged = [
            row["pane_id"]
            for row in list_panes(engine).rows
            if row.get("is_caller") == "1"
        ]
        assert pane in flagged
    finally:
        # Clear the simulated caller env so the self-kill guard does not refuse
        # to tear down the session we pointed it at.
        monkeypatch.delenv("TMUX_PANE", raising=False)
        monkeypatch.delenv("TMUX", raising=False)
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


# --------------------------------------------------------------------------- #
# CallerContext.discover -- precedence + injectable /proc parent walk
# --------------------------------------------------------------------------- #
def test_discover_process_env_wins() -> None:
    """The server's own env beats every other source."""
    ctx = CallerContext.discover(
        environ={"TMUX_PANE": "%1", "TMUX": "/s,1,2"}, is_linux=True
    )
    assert ctx.source == "process-env"
    assert ctx.pane_id == "%1"


def test_discover_override_beats_walk() -> None:
    """LIBTMUX_MCP_CALLER_PANE is the trusted override (no /proc walk)."""
    ctx = CallerContext.discover(
        environ={"LIBTMUX_MCP_CALLER_PANE": "%5", "LIBTMUX_MCP_CALLER_TMUX": "/s,1,2"},
        is_linux=True,
    )
    assert ctx.source == "explicit-override"
    assert (ctx.pane_id, ctx.socket_path) == ("%5", "/s")


def test_discover_parent_walk_recovers_stripped_env() -> None:
    """A stripped child recovers TMUX from a same-uid ancestor."""
    fake_env = {10: {}, 20: {"TMUX_PANE": "%9", "TMUX": "/tmp/sock,7,3"}}
    fake_ppid = {10: 20, 20: 1}
    ctx = CallerContext.discover(
        environ={},
        read_env=fake_env.get,
        read_ppid=fake_ppid.get,
        read_uid=lambda _pid: 1000,
        self_pid=10,
        self_uid=1000,
        is_linux=True,
    )
    assert ctx.source == "parent-walk"
    assert (ctx.pane_id, ctx.socket_path) == ("%9", "/tmp/sock")


def test_discover_refuses_foreign_uid() -> None:
    """The walk stops at a differently-owned ancestor (no env read)."""
    fake_env = {10: {}, 20: {"TMUX_PANE": "%9", "TMUX": "/s,1,2"}}
    fake_ppid = {10: 20, 20: 1}
    ctx = CallerContext.discover(
        environ={},
        read_env=fake_env.get,
        read_ppid=fake_ppid.get,
        read_uid=lambda _pid: 99999,
        self_pid=10,
        self_uid=1000,
        is_linux=True,
    )
    assert ctx.source == "none"


def test_discover_off_linux() -> None:
    """No /proc means no walk (fail closed to source='none')."""
    assert CallerContext.discover(environ={}, is_linux=False).source == "none"


def test_discover_disabled_by_env() -> None:
    """LIBTMUX_MCP_DISCOVER=0 disables the parent walk."""
    ctx = CallerContext.discover(environ={"LIBTMUX_MCP_DISCOVER": "0"}, is_linux=True)
    assert ctx.source == "none"


def test_discover_fails_closed_on_reader_failure() -> None:
    """A reader returning None mid-walk degrades to source='none'."""
    ctx = CallerContext.discover(
        environ={},
        read_env=lambda _pid: None,
        read_ppid=lambda _pid: 2,
        read_uid=lambda _pid: 1000,
        self_pid=1,
        self_uid=1000,
        is_linux=True,
    )
    assert ctx.source == "none"


def test_caller_server_args_binds_caller_socket() -> None:
    """The binding decision yields -S only for a discovered, non-overridden socket."""
    ctx = CallerContext.from_env({"TMUX_PANE": "%1", "TMUX": "/sock,1,2"})
    assert caller_server_args(ctx, explicit=False) == ("-S", "/sock")
    assert caller_server_args(ctx, explicit=True) == ()
    assert caller_server_args(CallerContext.from_env({}), explicit=False) == ()


# --------------------------------------------------------------------------- #
# Self-kill guards
# --------------------------------------------------------------------------- #
def test_kill_pane_refuses_caller_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    """kill_pane refuses the pane running this MCP server."""
    monkeypatch.setenv("TMUX_PANE", "%9")
    monkeypatch.setenv("TMUX", "/s,1,2")
    with pytest.raises(ToolError, match="this MCP server"):
        kill_pane(ConcreteEngine(), "%9")


def test_respawn_pane_refuses_caller_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    """respawn_pane (which destroys the process) refuses the caller's pane."""
    monkeypatch.setenv("TMUX_PANE", "%9")
    monkeypatch.setenv("TMUX", "/s,1,2")
    with pytest.raises(ToolError, match="this MCP server"):
        respawn_pane(ConcreteEngine(), "%9")


def test_kill_pane_allows_other_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    """A different pane is not the caller, so it is not refused."""
    monkeypatch.setenv("TMUX_PANE", "%9")
    monkeypatch.setenv("TMUX", "/s,1,2")
    assert kill_pane(ConcreteEngine(), "%1") is None


def test_self_kill_refusals_live(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Killing the caller's own pane/window/session is refused on a real server."""
    engine = SubprocessEngine.for_server(session.server)
    real_socket = session.server.cmd("display-message", "-p", "#{socket_path}").stdout[
        0
    ]
    created = create_session(engine, name="selfkill")
    try:
        pane = created.first_pane_id
        assert pane is not None
        monkeypatch.setenv("TMUX_PANE", pane)
        monkeypatch.setenv("TMUX", f"{real_socket},0,0")
        with pytest.raises(ToolError, match="this MCP server"):
            kill_pane(engine, pane)
        with pytest.raises(ToolError, match="this MCP server"):
            kill_window(engine, created.first_window_id or "")
        with pytest.raises(ToolError, match="this MCP server"):
            kill_session(engine, created.session_id)
    finally:
        monkeypatch.delenv("TMUX_PANE", raising=False)
        monkeypatch.delenv("TMUX", raising=False)
        kill_session(engine, created.session_id)


# --------------------------------------------------------------------------- #
# Review fixes: ambient-engine scoping (S1) + per-op guard (S2)
# --------------------------------------------------------------------------- #
def test_ambient_engine_matches_only_process_env_caller() -> None:
    """An unbound engine is the caller's server only for a process-env caller."""
    proc = CallerContext.from_env({"TMUX_PANE": "%1", "TMUX": "/s,1,2"})
    walked = dataclasses.replace(proc, source="parent-walk")
    assert socket_could_match(None, proc) is True
    assert socket_could_match(None, walked) is False
    assert socket_matches(None, proc) is True
    assert socket_matches(None, walked) is False


def test_op_kill_pane_is_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-op kill surface is self-kill-guarded too (no bypass)."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    monkeypatch.setenv("TMUX_PANE", "%9")
    monkeypatch.setenv("TMUX", "/s,1,2")
    server = build_async_server(
        SyncToAsyncEngine(ConcreteEngine()), events="off", expose_operations=True
    )

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool("op_kill_pane", {"target": "%9"})

    with pytest.raises(ToolError, match="this MCP server"):
        asyncio.run(main())
