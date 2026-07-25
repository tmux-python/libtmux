"""Synchronous control-mode lifecycle tests against isolated tmux servers."""

from __future__ import annotations

import concurrent.futures
import secrets
import shlex
import typing as t

import pytest

from libtmux._internal.control_mode import ControlMode
from libtmux.experimental.engines.base import CommandRequest
from libtmux.experimental.engines.connection import ServerConnection
from libtmux.experimental.engines.control_mode import ControlModeEngine

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def _wait_hook(server: Server, ready: str, release: str) -> str:
    """Build a hook that exposes when tmux's global queue is waiting."""
    connection = ServerConnection.from_server(server)
    signal = shlex.join(connection.argv("wait-for", "-S", ready))
    block = shlex.join(connection.argv("wait-for", release))
    return f"run-shell {shlex.quote(f'{signal}; {block}')}"


def _signal_hook(server: Server, channel: str) -> str:
    """Build a hook that signals *channel* from a fresh tmux client."""
    connection = ServerConnection.from_server(server)
    signal = shlex.join(connection.argv("wait-for", "-S", channel))
    return f"run-shell {shlex.quote(signal)}"


def test_sync_control_reuses_existing_session(session: Session) -> None:
    """Starting and closing control mode creates no extra session."""
    server = session.server
    session_id = session.session_id
    assert session_id is not None
    before = {item.session_id for item in server.sessions}

    with ControlModeEngine.for_server(server) as engine:
        current = engine.run(
            CommandRequest.from_args("display-message", "-p", "#{session_id}"),
        )
        during = {item.session_id for item in server.sessions}

    assert current.stdout == (session_id,)
    assert during == before
    assert {item.session_id for item in server.sessions} == before
    assert server.is_alive()


def test_sync_empty_server_does_not_gain_a_phantom(server: Server) -> None:
    """A read against an empty server stays a subprocess read with no side effect."""
    engine = ControlModeEngine.for_server(server)

    result = engine.run(CommandRequest.from_args("list-sessions"))
    engine.close()

    assert result.returncode != 0
    assert not server.is_alive()


def test_sync_attach_preserves_session_environment(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The initial ``attach-session -E`` leaves session environment untouched."""
    server = session.server
    session_id = session.session_id
    assert session_id is not None
    name = f"LIBTMUX_ATTACH_ENV_{secrets.token_hex(8).upper()}"
    server.cmd("set-option", "-t", session_id, "update-environment", name)
    server.cmd("set-environment", "-t", session_id, name, "before")
    monkeypatch.setenv(name, "after")

    with ControlModeEngine.for_server(server) as engine:
        result = engine.run(CommandRequest.from_args("list-sessions"))

    environment = server.cmd("show-environment", "-t", session_id, name)
    assert result.returncode == 0
    assert environment.stdout == [f"{name}=before"]


def test_sync_unsafe_session_uses_subprocess(session: Session) -> None:
    """An effective ``destroy-unattached=on`` target is not auto-attached."""
    server = session.server
    session_id = session.session_id
    assert session_id is not None
    engine = ControlModeEngine.for_server(server)
    session_ids = [
        item.session_id for item in server.sessions if item.session_id is not None
    ]
    assert session_ids

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
            result = engine.run(CommandRequest.from_args("list-sessions"))
            assert result.returncode == 0
            assert engine._proc is None
        finally:
            for target in session_ids:
                server.cmd(
                    "set-option",
                    "-t",
                    target,
                    "destroy-unattached",
                    "off",
                )
            engine.close()

    assert server.sessions.get(session_id=session_id) is not None


def test_sync_close_admits_signal_for_active_fallback(session: Session) -> None:
    """Close lets a fallback signal release the active cohort it is draining."""
    server = session.server
    session_ids = [
        item.session_id for item in server.sessions if item.session_id is not None
    ]
    assert session_ids
    ready = f"libtmux-ready-{secrets.token_hex(8)}"
    release = f"libtmux-release-{secrets.token_hex(8)}"
    engine = ControlModeEngine.for_server(server)

    with ControlMode(server=server, session=session):
        for target in session_ids:
            server.cmd(
                "set-option",
                "-t",
                target,
                "destroy-unattached",
                "on",
            )
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        try:
            waiter = pool.submit(
                engine.run,
                CommandRequest.from_args(
                    "wait-for",
                    "-S",
                    ready,
                    ";",
                    "wait-for",
                    release,
                ),
            )
            assert server.cmd("wait-for", ready).returncode == 0
            close = pool.submit(engine.close)
            with engine._lifecycle:
                if not engine._closing:
                    engine._lifecycle.wait(timeout=2)
                assert engine._closing
            signal = pool.submit(
                engine.run,
                CommandRequest.from_args("wait-for", "-S", release),
            )
            assert signal.result(timeout=2).returncode == 0
            assert waiter.result(timeout=2).returncode == 0
            close.result(timeout=2)
        finally:
            server.cmd("wait-for", "-S", release)
            pool.shutdown(wait=True, cancel_futures=True)
            for target in session_ids:
                server.cmd(
                    "set-option",
                    "-t",
                    target,
                    "destroy-unattached",
                    "off",
                )
            engine.close()


def test_sync_dead_control_process_reconnects(session: Session) -> None:
    """A later batch cleans and replaces an exited control client."""
    engine = ControlModeEngine.for_server(session.server)
    first = engine.run(CommandRequest.from_args("list-sessions"))
    proc = engine._proc
    assert proc is not None
    proc.terminate()
    proc.wait(timeout=2)

    second = engine.run(CommandRequest.from_args("list-sessions"))
    replacement = engine._proc
    engine.close()

    assert first.returncode == 0
    assert second.returncode == 0
    assert replacement is not None
    assert replacement is not proc


def test_sync_close_survives_a_waiting_global_hook(session: Session) -> None:
    """Close never deletes a session referenced by tmux's deferred callbacks."""
    server = session.server
    session_id = session.session_id
    assert session_id is not None
    ready = f"libtmux-ready-{secrets.token_hex(8)}"
    release = f"libtmux-release-{secrets.token_hex(8)}"
    observed = f"libtmux-observed-{secrets.token_hex(8)}"
    renamed = f"{session.name}-deferred"

    server.cmd("set-hook", "-g", "session-renamed", _wait_hook(server, ready, release))
    server.cmd(
        "set-hook",
        "-g",
        "session-window-changed",
        _signal_hook(server, observed),
    )
    try:
        with ControlMode(server=server, session=session):
            server.cmd("rename-session", "-t", session_id, renamed)
            assert server.cmd("wait-for", ready).returncode == 0

            engine = ControlModeEngine.for_server(server)
            engine.run(CommandRequest.from_args("new-window"))
            engine.run(CommandRequest.from_args("select-window", "-t", ":0"))
            engine.close()

            assert server.cmd("wait-for", "-S", release).returncode == 0
            server.cmd("wait-for", observed)
            assert server.is_alive()
            assert server.sessions.get(session_id=session_id) is not None
    finally:
        if server.is_alive():
            server.cmd("set-hook", "-gu", "session-renamed")
            server.cmd("set-hook", "-gu", "session-window-changed")
