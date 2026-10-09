"""Explicit ownership retains remote identity through teardown and failure."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import subprocess
import sys
import threading
import time
import typing as t

import pytest

from libtmux import Pane, Server, Session, Window, exc

if t.TYPE_CHECKING:
    from libtmux.common import tmux_cmd


def _resource(server: Server, kind: str) -> Server | Session | Window | Pane:
    session = server.new_session(session_name="owned")
    if kind == "server":
        return server
    if kind == "session":
        return session
    window = session.new_window(window_name="owned_window")
    if kind == "window":
        return window
    return window.split(shell="/bin/sh")


def test_server_context_leaves_remote_daemon_alive(server: Server) -> None:
    """Client scope exit does not accept responsibility for remote destruction."""
    server.new_session(session_name="keeper")
    with server:
        assert server.is_alive()
    assert server.is_alive()
    assert server.has_session("keeper")


@pytest.mark.parametrize("kind", ["server", "session", "window", "pane"])
def test_explicit_owner_destroys_only_accepted_resource(
    server: Server, kind: str
) -> None:
    """Adoption accepts an existing object, while plain lookup leaves it alive."""
    server.new_session(session_name="keeper")
    resource = _resource(server, kind)
    owner = resource.own()
    identity = owner.identity
    assert not owner.closed
    assert owner.value is resource
    assert server.is_alive()
    with owner as accepted:
        assert accepted is resource
    assert owner.closed
    owner.close()
    if kind == "server":
        assert not server.is_alive()
    else:
        result = server.cmd(
            f"list-{kind}s",
            *(("-a",) if kind != "session" else ()),
            "-F",
            f"#{{{kind}_id}}",
        )
        assert identity.object_id not in result.stdout
        assert server.has_session("keeper")


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_owner_ignores_mutated_handle_fields(server: Server, kind: str) -> None:
    """The object and its parent are mutable; the accepted cleanup identity is not."""
    resource = _resource(server, kind)
    assert not isinstance(resource, Server)
    alternate_session = server.new_session(session_name="alternate")
    alternate = (
        alternate_session
        if kind == "session"
        else alternate_session.active_window
        if kind == "window"
        else alternate_session.active_pane
    )
    assert alternate is not None
    owner = resource.own()
    original_id = owner.identity.object_id
    alternate_id = getattr(alternate, f"{kind}_id")
    setattr(resource, f"{kind}_id", alternate_id)
    resource.server = Server(socket_path="/nonexistent/libtmux-owner-socket")
    owner.close()
    result = server.cmd(
        f"list-{kind}s",
        *(("-a",) if kind != "session" else ()),
        "-F",
        f"#{{{kind}_id}}",
    )
    assert original_id not in result.stdout
    assert alternate_id in result.stdout


@pytest.mark.parametrize("kind", ["server", "session", "window", "pane"])
def test_stale_owner_refuses_replacement_daemon(server: Server, kind: str) -> None:
    """A replacement can reuse IDs, but the prior owner must not destroy it."""
    resource = _resource(server, kind)
    owner = resource.own()
    server.kill()
    replacement = _resource(server, kind)
    replacement_id = None if kind == "server" else getattr(replacement, f"{kind}_id")
    with pytest.raises(exc.StaleTmuxOwner):
        owner.close()
    assert not owner.closed
    assert server.is_alive()
    if kind != "server":
        result = server.cmd(
            f"list-{kind}s",
            *(("-a",) if kind != "session" else ()),
            "-F",
            f"#{{{kind}_id}}",
        )
        assert replacement_id in result.stdout


@pytest.mark.parametrize("body_error", [RuntimeError("body"), KeyboardInterrupt()])
def test_owner_preserves_both_failures_then_retries(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    body_error: BaseException,
) -> None:
    """Failed teardown retains its error and identity until a successful retry."""
    resource = _resource(server, "session")
    owner = resource.own()
    cleanup_error = PermissionError("cleanup denied")

    def denied(*args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        raise cleanup_error

    with monkeypatch.context() as patch:
        patch.setattr(owner._client, "cmd", denied)
        with pytest.raises(BaseExceptionGroup) as caught, owner:
            raise body_error
    assert caught.value.exceptions == (body_error, cleanup_error)
    assert owner.cleanup_error is cleanup_error
    assert not owner.closed
    assert server.has_session("owned")
    owner.close()
    assert owner.closed
    assert owner.cleanup_error is None


def test_unlinked_live_daemon_is_not_reported_as_cleaned(
    server: Server,
) -> None:
    """A missing socket does not prove that the accepted process has exited."""
    server.new_session(session_name="keeper")
    owner = server.own()
    path = pathlib.Path(server.socket_path)
    alias = path.with_name(path.name + "-rescue")
    alias.hardlink_to(path)
    try:
        path.unlink()
        with pytest.raises(exc.LibTmuxException, match="unreachable"):
            owner.close()
        assert not owner.closed
    finally:
        if not path.exists():
            path.hardlink_to(alias)
        alias.unlink()
        owner.close()


@pytest.mark.parametrize("kind", ["server", "session", "window", "pane"])
def test_generation_token_rejects_numeric_identity_collision(
    server: Server, kind: str
) -> None:
    """Model PID/start-second reuse while a real replacement owns the same IDs."""
    owner = _resource(server, kind).own()
    server.kill()
    replacement_owner = _resource(server, kind).own()
    owner._identity = dataclasses.replace(
        owner.identity,
        server_pid=replacement_owner.identity.server_pid,
        start_time=replacement_owner.identity.start_time,
    )
    assert (
        owner.identity.generation_token != replacement_owner.identity.generation_token
    )
    try:
        with pytest.raises(exc.StaleTmuxOwner):
            owner.close()
        assert server.is_alive()
        assert not owner.closed
    finally:
        replacement_owner.close()


@pytest.mark.parametrize("token", ["", "malformed", "f" * 31, "g" * 32])
def test_adoption_preserves_malformed_reserved_metadata(
    server: Server, token: str
) -> None:
    """A reserved-key collision fails acceptance without replacing the value."""
    session = server.new_session(session_name="keeper")
    result = server.cmd("set-option", "-s", "@libtmux_owner_generation", token)
    assert result.returncode == 0
    with pytest.raises(exc.LibTmuxException, match="generation token"):
        session.own()
    result = server.cmd("show-options", "-sv", "@libtmux_owner_generation")
    assert "\n".join(result.stdout) == token
    assert server.has_session("keeper")


def test_cleanup_deadline_includes_waiting_for_another_close(server: Server) -> None:
    """A competing close cannot make the public timeout wait without a bound."""
    session = server.new_session(session_name="keeper")
    owner = session.own(timeout=0.1)
    locked = threading.Event()
    release = threading.Event()

    def competing_close() -> None:
        with owner._lock:
            locked.set()
            release.wait(2)

    worker = threading.Thread(target=competing_close)
    worker.start()
    assert locked.wait(1)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="another cleanup") as caught:
            owner.close()
        assert time.monotonic() - started < 0.8
        assert owner.cleanup_error is caught.value
        assert not owner.closed
        assert server.has_session("keeper")
    finally:
        release.set()
        worker.join(3)
        owner.close()
    assert owner.closed


def test_hung_cleanup_client_is_reaped_and_owner_can_retry(
    server: Server, tmp_path: pathlib.Path
) -> None:
    """Timeout kills the client without claiming that remote destruction succeeded."""
    blocker = tmp_path / "block-cleanup"
    blocker.write_text("block")
    pid_file = tmp_path / "client-pid"
    wrapper = tmp_path / "tmux-wrapper"
    binary = server._require_tmux_bin()
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys, time\n"
        "if any(arg.startswith('kill-') for arg in sys.argv) "
        f"and pathlib.Path({str(blocker)!r}).exists():\n"
        f"    pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "    time.sleep(30)\n"
        f"os.execv({binary!r}, [{binary!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o700)
    client = Server(socket_path=server.socket_path, tmux_bin=wrapper)
    session = client.new_session(session_name="timeout-owned")
    owner = session.own(timeout=1.0)
    with pytest.raises(subprocess.TimeoutExpired):
        owner.close()
    assert not owner.closed
    assert isinstance(owner.cleanup_error, subprocess.TimeoutExpired)
    with pytest.raises(ChildProcessError):
        os.waitpid(int(pid_file.read_text()), os.WNOHANG)
    assert server.has_session("timeout-owned")
    blocker.unlink()
    owner.close()
    assert owner.closed
    assert not server.has_session("timeout-owned")
