"""Discover tmux through real sockets and the existing isolated server fixtures."""

from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import typing as t

import pytest

from libtmux import exc, neo
from libtmux._internal.query_list import QueryList
from libtmux.contrib.lobby import TmuxLobby, TmuxLobbyServer
from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux.session import Session


@pytest.fixture
def lobby_socket(session: Session) -> pathlib.Path:
    """Return the socket created and cleaned up by the session fixture."""
    return pathlib.Path(
        session.server.cmd("display-message", "-p", "#{socket_path}").stdout[0]
    )


def test_lobby_live_server(lobby_socket: pathlib.Path, session: Session) -> None:
    """Discover metadata and traverse sessions, windows, and panes."""
    window = session.new_window(window_name="lobby-window")
    pane = window.split()
    results = TmuxLobby(paths=[lobby_socket], include_defaults=False).servers

    assert isinstance(results, QueryList)
    assert len(results) == 1
    result = results.get(alive=True)
    assert isinstance(result, TmuxLobbyServer)
    assert isinstance(result.server, Server)
    assert result.socket_path == str(lobby_socket.resolve())
    assert result.socket_name == lobby_socket.name
    assert result.server.socket_path == result.socket_path
    assert result.uid == os.getuid()
    metadata = session.server.cmd("display-message", "-p", "#{pid}\t#{version}").stdout[
        0
    ]
    assert metadata == f"{result.pid}\t{result.version}"
    assert result.error is None
    found_session = result.sessions.get(session_id=session.session_id)
    found_window = result.windows.get(window_id=window.window_id)
    found_pane = result.panes.get(pane_id=pane.pane_id)
    assert found_session is not None
    assert found_window is not None
    assert found_pane is not None
    assert found_session.session_name == session.session_name
    assert found_window.window_name == "lobby-window"
    assert found_pane.window_id == window.window_id
    assert found_session.server is result.server


def test_lobby_class_and_instance_access(
    lobby_socket: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both access forms scan; replace defaults to avoid unrelated user sockets."""
    monkeypatch.setattr(
        TmuxLobby, "_default_paths", staticmethod(lambda: [lobby_socket])
    )
    class_result = TmuxLobby.servers.get(socket_name=lobby_socket.name)
    instance_result = TmuxLobby().servers.get(socket_name=lobby_socket.name)
    assert class_result is not None and class_result.alive
    assert instance_result is not None and instance_result.alive


def test_lobby_multiple_servers(TestServer: type[Server]) -> None:
    """Keep overlapping session IDs on separate sockets bound to their servers."""
    first, second = TestServer(), TestServer()
    first.new_session(session_name="first")
    second.new_session(session_name="second")
    paths = [
        server.cmd("display-message", "-p", "#{socket_path}").stdout[0]
        for server in (first, second)
    ]
    results = TmuxLobby(paths=paths, include_defaults=False).servers
    assert len(results) == 2
    assert {result.sessions[0].session_name for result in results} == {
        "first",
        "second",
    }
    for result in results:
        assert result.alive
        assert result.sessions[0].server.socket_path == result.socket_path


def test_lobby_server_without_sessions(
    lobby_socket: pathlib.Path, session: Session
) -> None:
    """Recognize a live server kept running with exit-empty disabled."""
    session.server.cmd("set-option", "-s", "exit-empty", "off")
    try:
        for found_session in session.server.sessions:
            found_session.kill()
        result = TmuxLobby(paths=lobby_socket, include_defaults=False).servers[0]
        assert result.alive
        assert result.pid is not None
        assert result.sessions == result.windows == result.panes == []
    finally:
        session.server.kill()


@pytest.mark.parametrize("tmux_env", [None, "", "malformed", "/tmp/a,b,123,0"])
@pytest.mark.parametrize("tmpdir", [None, "", "/run/user/tmux"])
def test_lobby_default_paths(
    tmux_env: str | None, tmpdir: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defaults follow tmux's directories and the current pane's socket."""
    for key, value in (("TMUX", tmux_env), ("TMUX_TMPDIR", tmpdir)):
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    expected = [pathlib.Path("/tmp") / f"tmux-{os.getuid()}"]
    if tmpdir:
        expected.append(pathlib.Path(tmpdir) / f"tmux-{os.getuid()}")
    if tmux_env and "," in tmux_env:
        expected.append(pathlib.Path("/tmp/a,b"))
    assert TmuxLobby._default_paths() == expected


def test_lobby_defaults_extend_custom_paths(
    lobby_socket: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Custom paths extend defaults; stub defaults to keep discovery isolated."""
    monkeypatch.setattr(
        TmuxLobby, "_default_paths", staticmethod(lambda: [lobby_socket])
    )
    path = tmp_path / "stale"
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
    lobby = TmuxLobby(paths=[path])
    results = lobby.servers
    assert len(results) == 2
    live = results.get(socket_name=lobby_socket.name)
    stale = results.get(socket_name="stale")
    assert live is not None and live.alive
    assert stale is not None and not stale.alive
    assert len(TmuxLobby(paths=[path], include_defaults=False).servers) == 1
    assert TmuxLobby(include_defaults=False).servers == []


def test_lobby_paths_patterns_and_duplicates(
    lobby_socket: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolve literal paths, home paths, recursive patterns, and socket aliases."""
    directory = tmp_path / "nested"
    directory.mkdir()
    alias = directory / "live.socket"
    alias.symlink_to(lobby_socket)
    (directory / "ordinary.socket").write_text("not a socket", encoding="utf-8")
    (directory / "broken.socket").symlink_to(tmp_path / "absent")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    results = TmuxLobby(
        paths=[lobby_socket, "nested", "~/nested/live.socket", "missing"],
        patterns=["~/**/*.socket", "nested"],
        include_defaults=False,
    ).servers
    assert len(results) == 1
    assert results[0].socket_path == str(lobby_socket.resolve())
    assert results[0].alive
    assert (
        TmuxLobby(patterns=["~/**/*.socket"], include_defaults=False).servers[0].alive
    )


def test_lobby_literal_paths_and_shallow_directories(tmp_path: pathlib.Path) -> None:
    """Directories are shallow and literal filenames retain glob metacharacters."""
    directory = tmp_path / "nested"
    directory.mkdir()
    path = directory / "[socket]"
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
    assert TmuxLobby(paths=[tmp_path], include_defaults=False).servers == []
    assert (
        TmuxLobby(paths=[path], include_defaults=False).servers[0].socket_name
        == "[socket]"
    )


def test_lobby_single_path_or_pattern(lobby_socket: pathlib.Path) -> None:
    """Accept a path or pattern directly without iterating its characters."""
    for path in (str(lobby_socket), lobby_socket):
        assert TmuxLobby(paths=path, include_defaults=False).servers[0].alive
    assert (
        TmuxLobby(patterns=str(lobby_socket), include_defaults=False).servers[0].alive
    )


def test_lobby_querylist_and_stale_sockets(tmp_path: pathlib.Path) -> None:
    """Keep failed probes and apply QueryList lookups to socket metadata."""
    for name in ("zeta", "alpha"):
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(tmp_path / name))
    results = TmuxLobby(paths=[tmp_path], include_defaults=False).servers
    assert [result.socket_name for result in results] == ["alpha", "zeta"]
    assert results.filter(alive=True) == []
    assert len(results.filter(alive=False)) == 2
    result = results.filter(socket_name__startswith="al").get()
    assert result is not None
    assert result.socket_name == "alpha"
    assert results.get(socket_path=result.socket_path) is result
    assert results.filter(lambda item: item.uid == os.getuid()) == results
    assert result.error
    assert result.pid is None
    assert result.version is None
    assert result.sessions == result.windows == result.panes == []
    assert pathlib.Path(result.socket_path).is_socket()
    with pytest.raises(exc.MultipleObjectsReturned):
        results.get(alive=False)
    with pytest.raises(exc.ObjectDoesNotExist):
        results.get(socket_name="missing")


def test_lobby_rescans(lobby_socket: pathlib.Path, session: Session) -> None:
    """Each access probes again while an earlier result keeps its metadata."""
    lobby = TmuxLobby(paths=[lobby_socket], include_defaults=False)
    previous = lobby.servers.get()
    assert previous is not None
    assert previous.alive
    session.server.kill()
    assert not lobby.servers.filter(alive=True)
    assert previous.alive
    assert previous.sessions == previous.windows == previous.panes == []


def test_lobby_unresponsive_socket(tmp_path: pathlib.Path) -> None:
    """A Unix listener that does not speak tmux times out and remains visible."""
    path = tmp_path / "listener"
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        listener.listen()
        result = TmuxLobby(
            paths=[path], include_defaults=False, timeout=0.05
        ).servers.get()
    assert result is not None
    assert not result.alive
    assert result.error and "timed out" in result.error
    assert result.sessions == result.windows == result.panes == []


def test_lobby_missing_binary(
    lobby_socket: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """An unavailable tmux executable is a per-socket failure."""
    result = TmuxLobby(
        paths=[lobby_socket], include_defaults=False, tmux_bin=tmp_path / "no-tmux"
    ).servers.get()
    assert result is not None
    assert not result.alive
    assert result.error
    assert result.server.tmux_bin == str(tmp_path / "no-tmux")


@pytest.mark.parametrize("output", ["", "not-tmux", "0\t3.2a", "123\t"])
def test_lobby_requires_server_metadata(
    lobby_socket: pathlib.Path, tmp_path: pathlib.Path, output: str
) -> None:
    """A client exiting successfully without tmux metadata does not prove liveness."""
    client = tmp_path / "client"
    client.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n", encoding="utf-8")
    client.chmod(0o700)
    result = TmuxLobby(
        paths=lobby_socket, include_defaults=False, tmux_bin=client
    ).servers[0]
    assert not result.alive
    assert result.error == "tmux returned no server metadata"


def test_lobby_child_query_failure(
    lobby_socket: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Child access is lenient; inject permissions changing after discovery."""
    result = TmuxLobby(paths=lobby_socket, include_defaults=False).servers[0]

    def denied(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise PermissionError(result.socket_path)

    monkeypatch.setattr(neo, "tmux_cmd", denied)
    assert result.sessions == result.windows == result.panes == []


def test_lobby_disappearing_socket(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep a failed probe if a socket disappears; inject the scan/probe race."""
    path = tmp_path / "vanishing"
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
    original = TmuxLobby._probe

    def remove_before_probe(
        lobby: TmuxLobby, path: pathlib.Path, info: os.stat_result
    ) -> TmuxLobbyServer:
        path.unlink()
        return original(lobby, path, info)

    monkeypatch.setattr(TmuxLobby, "_probe", remove_before_probe)
    result = TmuxLobby(paths=[path], include_defaults=False).servers.get()
    assert result is not None
    assert not result.alive
    assert result.error
    assert not path.exists()


def test_lobby_unreadable_directory(
    lobby_socket: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Continue past unreadable directories; inject denial even when run as root."""
    original = pathlib.Path.iterdir

    def denied(path: pathlib.Path) -> t.Iterator[pathlib.Path]:
        if path == tmp_path:
            raise PermissionError(str(path))
        return original(path)

    monkeypatch.setattr(pathlib.Path, "iterdir", denied)
    results = TmuxLobby(paths=[tmp_path, lobby_socket], include_defaults=False).servers
    result = results.get()
    assert result is not None and result.alive


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_lobby_invalid_timeout(timeout: float) -> None:
    """Require a bound for every probe."""
    with pytest.raises(ValueError, match="positive and finite"):
        TmuxLobby(timeout=timeout)


def test_server_cmd_timeout_reaps_client(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bound a real wait-for; record Popen only to verify child cleanup."""
    clients: list[subprocess.Popen[str]] = []
    original = subprocess.Popen

    def record(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[str]:
        process = original(*args, **kwargs)
        clients.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", record)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            session.server.cmd("wait-for", "lobby-timeout", timeout=0.05)
        assert len(clients) == 1
        client = clients[0]
        assert client.returncode is not None
        assert client.stdout is not None and client.stdout.closed
        assert client.stderr is not None and client.stderr.closed
    finally:
        for client in clients:
            if client.poll() is None:
                client.kill()
                client.wait()
    assert session.server.cmd("list-sessions", timeout=1).returncode == 0
