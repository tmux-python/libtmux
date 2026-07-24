"""Tests for the top-level ``python -m libtmux.agents`` console."""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
import typing as t

import pytest

import libtmux
from libtmux.agents import cli
from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.state import Agent, AgentState
from libtmux.experimental.agents.store import AgentStore, JsonFile
from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine
from libtmux.test.random import namer

if t.TYPE_CHECKING:
    from pathlib import Path

    from libtmux.session import Session


def test_module_help_smoke() -> None:
    """``python -m libtmux.agents --help`` exposes the console verbs."""
    process = subprocess.run(
        [sys.executable, "-m", "libtmux.agents", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 0
    assert "start" in process.stdout
    assert "attach" in process.stdout
    assert "monitor" in process.stdout


def test_parse_no_args_defaults_to_start() -> None:
    """No subcommand behaves like tmux: create or attach the console."""
    args = cli.parse_args([])

    assert args.command == "start"
    assert args.session_name == cli.DEFAULT_SESSION_NAME


def test_parse_attach_alias() -> None:
    """``att`` is a short alias for attaching to the running console."""
    args = cli.parse_args(["att", "--detached"])

    assert args.command == "attach"
    assert args.detached is True


def test_default_state_path_honors_xdg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The default store path lives under XDG state with a filesystem-safe slug."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    path = cli.default_state_path("libtmux agents / demo")

    assert path == tmp_path / "libtmux" / "agents" / "libtmux-agents-demo.json"


def test_status_reads_store_without_tmux(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``status`` reads persisted JSON directly, with no live tmux call."""
    state_path = tmp_path / "agents.json"
    store = AgentStore(
        agents={
            "%1": Agent(
                pane_id="%1",
                key="%1",
                name="claude",
                state=AgentState.RUNNING,
                since=1.5,
                source="option",
                pid=123,
                alive=True,
            )
        },
    )
    JsonFile(state_path).save(store.to_dict())

    def fail_server(config: cli.AgentConsoleConfig) -> libtmux.Server:
        pytest.fail("status must not contact tmux")

    monkeypatch.setattr(cli, "_server", fail_server)

    assert cli.main(["--state-path", str(state_path), "status"]) == 0

    out = capsys.readouterr().out
    assert "%1" in out
    assert "claude" in out
    assert "running" in out


def test_status_json_reads_store_alias(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``list --json`` is a machine-readable alias over the same store."""
    state_path = tmp_path / "agents.json"
    store = AgentStore(
        agents={
            "%2": Agent(
                pane_id="%2",
                key="%2",
                name=None,
                state=AgentState.DONE,
                since=2.0,
                source="option",
                pid=None,
                alive=True,
            )
        },
    )
    JsonFile(state_path).save(store.to_dict())

    assert cli.main(["--state-path", str(state_path), "list", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "pane_id": "%2",
            "key": "%2",
            "name": None,
            "state": "done",
            "since": 2.0,
            "source": "option",
            "pid": None,
            "alive": True,
        }
    ]


def test_hooks_status_and_install_use_registry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Hook commands are a thin layer over the existing hook registry."""
    installed: list[str] = []

    class FakeHook:
        name = "fake"

        def detect(self) -> bool:
            return True

        def install(self) -> None:
            installed.append(self.name)

        def uninstall(self) -> None:
            pytest.fail("uninstall should not be called")

        def status(self) -> str:
            return "installed"

    monkeypatch.setattr(
        "libtmux.agents.cli.hook_registry.registry",
        lambda: [FakeHook()],
    )

    assert cli.main(["hooks", "status"]) == 0
    status_out = capsys.readouterr().out
    assert "fake" in status_out
    assert "installed" in status_out
    assert "yes" in status_out

    assert cli.main(["hooks", "install", "fake"]) == 0
    assert installed == ["fake"]


def test_start_detached_builds_and_reattaches(tmp_path: Path) -> None:
    """``start`` builds the console once and reuses it on the second call."""
    socket = f"libtmux_agents_cli_{next(namer)}"
    session_name = f"agents_{next(namer)}"
    state_path = tmp_path / "agents.json"
    server = libtmux.Server(socket_name=socket)
    config = cli.AgentConsoleConfig(
        socket_name=socket,
        session_name=session_name,
        state_path=state_path,
        detached=True,
    )

    try:
        first = cli.start(config)
        assert first.returncode == 0
        assert first.created is True
        assert first.attached is False
        assert first.state_path == state_path
        assert server.has_session(session_name)

        session = server.sessions.get(session_name=session_name)
        assert session is not None
        assert [window.window_name for window in session.windows] == ["agents"]
        assert len(session.windows[0].panes) == 2

        second = cli.start(config)
        assert second.returncode == 0
        assert second.created is False
        assert server.has_session(session_name)
    finally:
        with contextlib.suppress(Exception):
            server.kill()


def test_attach_detached_requires_existing_session(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``attach`` only attaches an already-running console."""
    socket = f"libtmux_agents_attach_{next(namer)}"
    session_name = f"agents_{next(namer)}"
    server = libtmux.Server(socket_name=socket)
    config = cli.AgentConsoleConfig(
        socket_name=socket,
        session_name=session_name,
        detached=True,
    )

    try:
        missing = cli.attach(config)
        assert missing.returncode == 1
        assert "start" in capsys.readouterr().err

        server.new_session(session_name=session_name, detach=True)
        present = cli.attach(config)
        assert present.returncode == 0
    finally:
        with contextlib.suppress(Exception):
            server.kill()


def test_monitor_persists_live_state(session: Session, tmp_path: Path) -> None:
    """A monitor sink writes the same JSON store that the CLI status reads."""
    state_path = tmp_path / "agents.json"

    async def main() -> str:
        engine = AsyncControlModeEngine.for_server(session.server)
        monitor = AgentMonitor(engine, sink=JsonFile(state_path))
        await monitor.start()
        active = session.active_window.active_pane
        assert active is not None
        pane_id = active.pane_id
        assert pane_id is not None

        session.cmd("set-option", "-p", "-t", pane_id, "@agent_state", "running")
        observed = "missing"
        for _ in range(40):
            await asyncio.sleep(0.1)
            match = {a.pane_id: a for a in monitor.agents}.get(pane_id)
            if match is not None:
                observed = match.state.value
                if observed == "running":
                    break
        await monitor.stop()
        await engine.aclose()
        return observed

    assert asyncio.run(main()) == "running"
    data = JsonFile(state_path).load()
    assert data is not None
    store = AgentStore.from_dict(data)
    assert [agent.state for agent in store.agents.values()] == [AgentState.RUNNING]


def test_run_monitor_observes_option_after_start(
    session: Session,
    tmp_path: Path,
) -> None:
    """The CLI monitor installs subscriptions before the first connection."""
    state_path = tmp_path / "agents.json"

    async def main() -> bool:
        session_name = session.session_name
        assert session_name is not None
        task = asyncio.create_task(
            cli.run_monitor(
                cli.AgentConsoleConfig(
                    socket_name=session.server.socket_name,
                    session_name=session_name,
                    state_path=state_path,
                    status_line=False,
                )
            )
        )
        try:
            for _ in range(30):
                await asyncio.sleep(0.1)
                clients = session.server.cmd(
                    "list-clients",
                    "-F",
                    "#{client_control_mode} #{session_name}",
                ).stdout
                if any(line == f"1 {session_name}" for line in clients):
                    break

            pane = session.active_window.active_pane
            assert pane is not None
            pane_id = pane.pane_id
            assert pane_id is not None
            session.cmd("set-option", "-p", "-t", pane_id, "@agent_state", "running")

            for _ in range(40):
                await asyncio.sleep(0.1)
                data = JsonFile(state_path).load()
                if not data:
                    continue
                store = AgentStore.from_dict(data)
                agent = store.agents.get(pane_id)
                if agent is not None and agent.state is AgentState.RUNNING:
                    return True
            return False
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    assert asyncio.run(main()) is True
