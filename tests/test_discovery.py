"""Discovery scans explicit directories and reports bounded non-starting probes."""

from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import time
import typing as t

import pytest

from libtmux import Server


def test_explicit_roots_find_servers_and_report_skipped_paths(
    server: Server,
    tmp_path: pathlib.Path,
) -> None:
    """A responding socket, ordinary file and missing directory stay distinguishable."""
    server.cmd("new-session", "-d", "-s", "keeper")
    root = pathlib.Path(server.socket_path).parent
    regular = root / "ordinary"
    regular.write_text("not a socket")
    before = server.cmd("show-options", "-s").stdout
    result = server.discover([root, tmp_path / "absent"], include_configured=False)
    assert [item.server.socket_path for item in result.servers] == [server.socket_path]
    identity = (
        server.cmd("display-message", "-p", "#{pid}\t#{start_time}")
        .stdout[0]
        .split("\t")
    )
    assert result.servers[0].server_pid == int(identity[0])
    assert result.servers[0].start_time == int(identity[1])
    assert result.probes == 1 and not result.truncated
    assert any(
        item.path == str(regular) and item.reason == "not-socket"
        for item in result.diagnostics
    )
    assert any(
        item.reason == "root-error" and isinstance(item.error, FileNotFoundError)
        for item in result.diagnostics
    )
    assert server.cmd("show-options", "-s").stdout == before


def test_captured_configured_roots_ignore_later_host_environment(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery derives configured paths from the handle's captured environment."""
    server.new_session("keeper")
    monkeypatch.setenv("TMUX_TMPDIR", "/missing/changed-after-construction")
    monkeypatch.setenv("LIBTMUX_SOCKET_PATH", "/missing/changed-endpoint")
    # Replace only the platform /tmp scan: no test probes an ambient daemon.
    scan = os.scandir
    default_root = f"/tmp/tmux-{os.getuid()}"

    def private_scan(path: str) -> t.Any:
        if path == default_root:
            raise FileNotFoundError(path)
        return scan(path)

    monkeypatch.setattr(os, "scandir", private_scan)
    result = server.discover()
    assert len(result.servers) == 1
    assert result.servers[0].server.socket_path == server.socket_path
    assert result.servers[0].server.child_environment == server.child_environment
    assert not any("changed-after" in item.path for item in result.diagnostics)


def test_probe_does_not_create_uid_directory_or_start_daemon(
    tmp_path: pathlib.Path,
) -> None:
    """A fresh selected root stays empty when discovery has nothing to inspect."""
    server = Server(
        socket_name="missing", child_environment={"TMUX_TMPDIR": str(tmp_path)}
    )
    result = server.discover([tmp_path], include_configured=False)
    assert not result.servers and result.probes == 0
    assert list(tmp_path.iterdir()) == []


def test_non_tmux_socket_probe_times_out_and_reaps_client(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A listening Unix socket exercises real tmux client timeout cleanup."""
    endpoint = str(tmp_path / "listener")
    server = Server(socket_path=endpoint)
    launch = subprocess.Popen
    clients: list[subprocess.Popen[str]] = []

    def observe(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[str]:
        process = launch(*args, **kwargs)
        clients.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", observe)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(endpoint)
        listener.listen()
        started = time.monotonic()
        result = server.discover(
            [tmp_path], include_configured=False, timeout=0.03, probe_timeout=1.0
        )
        elapsed = time.monotonic() - started
    assert result.probes == 1 and not result.servers
    failure = next(item for item in result.diagnostics if item.reason == "probe-error")
    assert isinstance(failure.error, subprocess.TimeoutExpired)
    assert elapsed < 1.0
    assert result.truncated
    assert any(item.reason == "deadline" for item in result.diagnostics)
    assert len(clients) == 1 and clients[0].poll() is not None


def test_entry_and_probe_budgets_report_truncation(server: Server) -> None:
    """The report distinguishes exhausted scanning and client budgets."""
    server.new_session("keeper")
    root = pathlib.Path(server.socket_path).parent
    result = server.discover([root], include_configured=False, max_entries=1)
    assert result.entries == 1 and result.probes == 0 and result.truncated
    assert any(item.reason == "entry-limit" for item in result.diagnostics)
    result = server.discover([root], include_configured=False, max_probes=1)
    assert len(result.servers) == 1 and result.probes == 1 and result.truncated
    assert any(item.reason == "probe-limit" for item in result.diagnostics)


def test_symlink_parent_semantics_and_missing_components_are_preserved(
    server: Server,
    tmp_path: pathlib.Path,
) -> None:
    """A link/.. path resolves through the filesystem; missing/.. must not disappear."""
    server.new_session("keeper")
    real = pathlib.Path(server.socket_path).parent
    nested = real / "child"
    nested.mkdir()
    link = tmp_path / "link"
    link.symlink_to(nested, target_is_directory=True)
    linked_root = str(link) + "/.."
    missing_root = str(real / "missing") + "/.."
    result = server.discover([missing_root, linked_root], include_configured=False)
    assert len(result.servers) == 1
    assert (
        result.servers[0].server.socket_path
        == linked_root + "/" + pathlib.Path(server.socket_path).name
    )
    assert any(
        item.path == missing_root and item.reason == "root-error"
        for item in result.diagnostics
    )


def test_duplicate_socket_aliases_probe_once(server: Server) -> None:
    """Filesystem identity deduplicates aliases without rewriting returned paths."""
    server.new_session("keeper")
    root = pathlib.Path(server.socket_path).parent
    alias = root / "alias"
    alias.symlink_to(server.socket_path)
    try:
        result = server.discover([root, root], include_configured=False)
        assert len(result.servers) == 1 and result.probes == 1
    finally:
        alias.unlink()


@pytest.mark.parametrize(
    "options",
    [
        {"max_entries": 0},
        {"max_probes": True},
        {"timeout": float("inf")},
        {"probe_timeout": 0},
    ],
)
def test_invalid_budgets_fail_before_probing(
    server: Server, options: dict[str, t.Any]
) -> None:
    """Invalid work limits cannot start an unbounded scan."""
    with pytest.raises(ValueError):
        server.discover([], include_configured=False, **options)


def test_infinite_root_iterable_stops_at_entry_budget(server: Server) -> None:
    """Root enumeration consumes the same bounded work budget as directory entries."""

    def roots() -> t.Iterator[str]:
        while True:
            yield "/missing/libtmux-discovery-root"

    result = server.discover(roots(), include_configured=False, max_entries=3)
    assert result.entries == 3 and result.truncated and not result.servers
    assert (
        len([item for item in result.diagnostics if item.reason == "root-error"]) == 3
    )


def test_discovery_propagates_interruption(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synchronous cancellation is not converted into a skipped-path diagnostic."""
    server.new_session("keeper")

    def interrupt(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(Server, "cmd", interrupt)
        with pytest.raises(KeyboardInterrupt):
            server.discover(
                [pathlib.Path(server.socket_path).parent], include_configured=False
            )
    assert server.has_session("keeper")
