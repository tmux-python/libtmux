"""Asynchronous control-mode lifecycle tests against isolated tmux servers."""

from __future__ import annotations

import asyncio
import secrets
import typing as t

import pytest

from libtmux._internal.control_mode import ControlMode
from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine
from libtmux.experimental.engines.base import CommandRequest, CommandSeparator

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_async_control_reuses_existing_session(session: Session) -> None:
    """Starting and closing async control mode creates no extra session."""
    server = session.server
    session_id = session.session_id
    assert session_id is not None
    before = {item.session_id for item in server.sessions}

    async def main() -> tuple[str, ...]:
        engine = AsyncControlModeEngine.for_server(server)
        try:
            return (
                await engine.run(
                    CommandRequest.from_args(
                        "display-message",
                        "-p",
                        "#{session_id}",
                    ),
                )
            ).stdout
        finally:
            await engine.aclose()

    assert asyncio.run(main()) == (session_id,)
    assert {item.session_id for item in server.sessions} == before
    assert server.is_alive()


def test_async_control_preserves_newline_in_argument(session: Session) -> None:
    """A newline stays inside one argument instead of starting a command."""

    async def main() -> tuple[str, ...]:
        engine = AsyncControlModeEngine.for_server(session.server)
        try:
            result = await engine.run(
                CommandRequest.from_args("display-message", "-p", "first\nsecond"),
            )
            return result.stdout
        finally:
            await engine.aclose()

    assert asyncio.run(main()) == ("first", "second")


def test_async_empty_server_does_not_gain_a_phantom(server: Server) -> None:
    """A read against an empty server uses async subprocess without side effects."""

    async def main() -> int:
        engine = AsyncControlModeEngine.for_server(server)
        try:
            result = await engine.run(CommandRequest.from_args("list-sessions"))
            return result.returncode
        finally:
            await engine.aclose()

    assert asyncio.run(main()) != 0
    assert not server.is_alive()


def test_async_context_starts_when_a_safe_session_exists(session: Session) -> None:
    """Context entry starts notification delivery when attachment is safe."""

    async def main() -> tuple[bool, bool]:
        engine = AsyncControlModeEngine.for_server(session.server)
        async with engine:
            started = engine._started
            connected = engine._proc is not None
        return started, connected

    assert asyncio.run(main()) == (True, True)


def test_async_attach_preserves_session_environment(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The initial ``attach-session -E`` leaves session environment untouched."""
    server = session.server
    session_id = session.session_id
    assert session_id is not None
    name = f"LIBTMUX_ASYNC_ATTACH_ENV_{secrets.token_hex(8).upper()}"
    server.cmd("set-option", "-t", session_id, "update-environment", name)
    server.cmd("set-environment", "-t", session_id, name, "before")
    monkeypatch.setenv(name, "after")

    async def main() -> int:
        engine = AsyncControlModeEngine.for_server(server)
        try:
            result = await engine.run(CommandRequest.from_args("list-sessions"))
            return result.returncode
        finally:
            await engine.aclose()

    assert asyncio.run(main()) == 0
    environment = server.cmd("show-environment", "-t", session_id, name)
    assert environment.stdout == [f"{name}=before"]


def test_async_unsafe_session_uses_subprocess(session: Session) -> None:
    """An effective ``destroy-unattached=on`` target is not auto-attached."""
    server = session.server
    session_id = session.session_id
    assert session_id is not None
    session_ids = [
        item.session_id for item in server.sessions if item.session_id is not None
    ]
    assert session_ids

    async def main() -> tuple[int, bool]:
        engine = AsyncControlModeEngine.for_server(server)
        try:
            result = await engine.run(CommandRequest.from_args("list-sessions"))
            return result.returncode, engine._proc is None
        finally:
            await engine.aclose()

    with ControlMode(server=server, session=session):
        for target in session_ids:
            server.cmd(
                "set-option",
                "-t",
                target,
                "destroy-unattached",
                "on",
            )
        try:
            assert asyncio.run(main()) == (0, True)
        finally:
            for target in session_ids:
                server.cmd(
                    "set-option",
                    "-t",
                    target,
                    "destroy-unattached",
                    "off",
                )

    assert server.sessions.get(session_id=session_id) is not None


def test_async_unsafe_fallback_commands_run_concurrently(session: Session) -> None:
    """A fallback signal can release another fallback command on this engine."""
    server = session.server
    session_ids = [
        item.session_id for item in server.sessions if item.session_id is not None
    ]
    assert session_ids
    ready = f"libtmux-ready-{secrets.token_hex(8)}"
    release = f"libtmux-release-{secrets.token_hex(8)}"

    async def main() -> tuple[int, int]:
        engine = AsyncControlModeEngine.for_server(server)
        waiter = asyncio.create_task(
            engine.run(
                CommandRequest.from_args(
                    "wait-for",
                    "-S",
                    ready,
                    CommandSeparator(";"),
                    "wait-for",
                    release,
                ),
            ),
        )
        try:
            ready_result = await asyncio.to_thread(server.cmd, "wait-for", ready)
            assert ready_result.returncode == 0
            signal = asyncio.create_task(
                engine.run(CommandRequest.from_args("wait-for", "-S", release)),
            )
            signal_result, waiter_result = await asyncio.wait_for(
                asyncio.gather(signal, waiter),
                timeout=2,
            )
            return signal_result.returncode, waiter_result.returncode
        finally:
            await asyncio.to_thread(server.cmd, "wait-for", "-S", release)
            await engine.aclose()

    with ControlMode(server=server, session=session):
        for target in session_ids:
            server.cmd(
                "set-option",
                "-t",
                target,
                "destroy-unattached",
                "on",
            )
        try:
            assert asyncio.run(main()) == (0, 0)
        finally:
            for target in session_ids:
                server.cmd(
                    "set-option",
                    "-t",
                    target,
                    "destroy-unattached",
                    "off",
                )
