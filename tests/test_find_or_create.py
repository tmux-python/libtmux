"""Created scopes retain ownership; exact reused matches remain borrowed."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import pathlib
import subprocess
import sys
import typing as t

import pytest

import libtmux.lifecycle as lifecycle_module
from libtmux import AmbiguousMatch, FoundOrCreated, Pane, Server, Session, Window, exc
from libtmux._compat import BaseExceptionGroup
from libtmux.lifecycle import CreationCleanupError, UnknownCreation

if t.TYPE_CHECKING:
    from libtmux.common import tmux_cmd


def _scope(server: Server, kind: str, key: str = "worker") -> FoundOrCreated[t.Any]:
    if kind == "server":
        return server.find_or_create()
    if kind == "session":
        return server.find_or_create_session(key, window_command="/bin/sh")
    session = server.sessions.get(session_name="keeper")
    assert session is not None
    if kind == "window":
        return session.find_or_create_window(key, window_shell="/bin/sh")
    return session.active_window.find_or_create_pane(key, shell="/bin/sh")


@pytest.mark.parametrize("kind", ["server", "session", "window", "pane"])
def test_created_scope_and_reused_scope_keep_distinct_responsibilities(
    server: Server,
    kind: str,
) -> None:
    """Borrowed scope exit and body failure leave the created owner's object alive."""
    if kind != "server":
        server.new_session("keeper")
    created = _scope(server, kind)
    assert created.created and created.owner is not None
    borrowed = _scope(server, kind)
    assert not borrowed.created and borrowed.owner is None
    with pytest.raises(RuntimeError, match="body failure"), borrowed:
        msg = "body failure"
        raise RuntimeError(msg)
    borrowed.close()
    assert not _scope(server, kind).created
    with created as value:
        assert value is created.value
    assert created.owner.closed
    created.close()
    if kind == "server":
        assert not server.is_alive()
    else:
        assert server.has_session("keeper")
        replacement = _scope(server, kind)
        assert replacement.created
        replacement.close()


def test_first_session_works_when_no_daemon_is_running(server: Server) -> None:
    """The normal endpoint can start its first session without owning the server."""
    with server.find_or_create_session("first") as session:
        assert session.session_name == "first"
        assert server.is_alive()
    assert not server.is_alive()


@pytest.mark.parametrize(
    ("kind", "key"),
    [
        (kind, key)
        for kind in ("session", "window", "pane")
        for key in ("worker spaces", "#{pid},[x]'$HOME", "worker-λ")
    ]
    + [("pane", "worker\nend\n")],
)
def test_names_and_keys_use_exact_literal_matching(
    server: Server, kind: str, key: str
) -> None:
    """Tmux format syntax, punctuation and newlines remain literal identity data."""
    server.new_session("keeper")
    if kind == "session" and "$HOME" in key and not server._supports_version("3.7"):
        before = server.cmd("list-sessions", "-F", "#{session_id}").stdout
        with pytest.raises(ValueError, match="normalized the requested session name"):
            _scope(server, kind, key)
        assert server.cmd("list-sessions", "-F", "#{session_id}").stdout == before
        return
    with _scope(server, kind, key) as created:
        reused = _scope(server, kind, key)
        assert not reused.created
        assert reused.value.id == created.id
        distinct = _scope(server, kind, key + " suffix")
        assert distinct.created
        distinct.close()


@pytest.mark.parametrize("kind", ["window", "pane"])
def test_ambiguous_matches_raise_without_destroying_resources(
    server: Server, kind: str
) -> None:
    """Window names and application pane keys can collide within a parent."""
    session = server.new_session("keeper")
    first: Window | Pane
    second: Window | Pane
    if kind == "window":
        first = session.new_window(window_name="duplicate")
        second = session.new_window(window_name="duplicate")
    else:
        first = session.active_window.split(shell="/bin/sh")
        second = session.active_window.split(shell="/bin/sh")
        for pane in (first, second):
            server.cmd(
                "set-option", "-p", "-t", pane.id, "@libtmux_pane_key", "duplicate"
            )
    before = server.cmd(f"list-{kind}s", "-a", "-F", f"#{{{kind}_id}}").stdout
    with pytest.raises(AmbiguousMatch):
        _scope(server, kind, "duplicate")
    assert server.cmd(f"list-{kind}s", "-a", "-F", f"#{{{kind}_id}}").stdout == before


def test_pane_matching_uses_only_local_options_and_selected_window(
    server: Server,
) -> None:
    """An inherited key and a key in another window are not this window's pane."""
    session = server.new_session("keeper")
    window = session.active_window
    server.cmd("set-option", "-g", "@libtmux_pane_key", "worker")
    elsewhere = session.new_window(window_name="elsewhere")
    with elsewhere.find_or_create_pane("worker"):
        result = window.find_or_create_pane("worker")
        assert result.created
        with result as pane:
            assert pane.window_id == window.window_id
            assert not window.find_or_create_pane("worker").created


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_lookup_failure_does_not_fall_through_to_creation(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """An injected list failure proves that lenient list accessors are not used."""
    server.new_session("keeper")
    original = Server.cmd
    created: list[str] = []

    def fail_lookup(
        client: Server, command: str, *args: t.Any, **kwargs: t.Any
    ) -> tmux_cmd:
        if any(f"list-{kind}s " in str(arg) for arg in args):
            msg = "lookup denied"
            raise PermissionError(msg)
        if any(
            f"new-{kind} " in str(arg) or "split-window " in str(arg) for arg in args
        ):
            created.append(command)
        return original(client, command, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Server, "cmd", fail_lookup)
        with pytest.raises(PermissionError, match="lookup denied"):
            _scope(server, kind)
    assert created == []


@pytest.mark.parametrize("kind", ["server", "session", "window", "pane"])
def test_created_body_and_cleanup_failures_retain_owner_for_retry(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """A created scope exposes both failures and a later successful cleanup."""
    if kind != "server":
        server.new_session("keeper")
    result = _scope(server, kind)
    assert result.owner is not None
    error = PermissionError("cleanup denied")

    def deny(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(result.owner._client, "cmd", deny)
        with pytest.raises(BaseExceptionGroup) as failure, result:
            msg = "body failed"
            raise RuntimeError(msg)
    assert failure.value.exceptions[1] is error
    assert not result.owner.closed
    result.close()
    assert result.owner.closed


def test_server_reuse_does_not_change_exit_empty_or_generation(server: Server) -> None:
    """Borrowing a daemon leaves its startup settings and ownership metadata alone."""
    server.cmd("new-session", "-d", "-s", "existing")
    before = server.cmd("show-options", "-s").stdout
    result = server.find_or_create()
    assert not result.created
    assert server.cmd("show-options", "-s").stdout == before
    assert not server.cmd("show-options", "-sqv", "@libtmux_owner_generation").stdout
    result.close()
    assert server.has_session("existing")


def test_concurrent_server_startup_has_one_owner(server: Server) -> None:
    """Tmux serializes startup; the nonce identifies only the winning caller."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: server.find_or_create(), range(2)))
    assert sum(result.created for result in results) == 1
    borrowed = next(result for result in results if not result.created)
    borrowed.close()
    assert server.cmd("display-message", "-p", "#{pid}").returncode == 0
    next(result for result in results if result.created).close()


def test_server_owner_rejects_numeric_identity_collision(server: Server) -> None:
    """A replacement with simulated PID/start-time reuse keeps its different token."""
    result = server.find_or_create()
    assert result.owner is not None
    original = result.owner.identity
    result.close()
    replacement = server.find_or_create()
    assert replacement.owner is not None
    identity = replacement.owner.identity
    assert identity.generation_token != original.generation_token
    result.owner._closed = False
    result.owner._identity = dataclasses.replace(
        original,
        server_pid=identity.server_pid,
        start_time=identity.start_time,
    )
    try:
        with pytest.raises(exc.StaleTmuxOwner):
            result.close()
        assert server.cmd("display-message", "-p", "#{pid}").returncode == 0
    finally:
        replacement.close()


@pytest.mark.parametrize("kind", ["server", "pane"])
def test_failure_after_creation_rolls_back_known_receipt(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """Failed acceptance or pane-key assignment rolls back the exact created object."""
    if kind == "pane":
        server.new_session("keeper")
    original = Server.cmd

    def fail_after_create(
        client: Server, command: str, *args: t.Any, **kwargs: t.Any
    ) -> tmux_cmd:
        if kind == "server" and command == "set-option":
            msg = "acceptance failed"
            raise RuntimeError(msg)
        if kind == "pane" and any("set-option -p " in str(arg) for arg in args):
            msg = "pane key failed"
            raise RuntimeError(msg)
        return original(client, command, *args, **kwargs)

    before = (
        server.cmd("list-panes", "-a", "-F", "#{pane_id}").stdout
        if kind == "pane"
        else []
    )
    with monkeypatch.context() as patch:
        patch.setattr(Server, "cmd", fail_after_create)
        with pytest.raises(RuntimeError):
            _scope(server, kind)
    if kind == "server":
        assert not server.is_alive()
    else:
        assert server.cmd("list-panes", "-a", "-F", "#{pane_id}").stdout == before


def test_server_rollback_failure_retains_retryable_owner(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed server acceptance and rollback retain both errors and identity."""
    original = Server.cmd

    def fail(client: Server, command: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        if command == "set-option":
            msg = "acceptance failed"
            raise ValueError(msg)
        if "kill-server" in args:
            msg = "rollback denied"
            raise PermissionError(msg)
        return original(client, command, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Server, "cmd", fail)
        with pytest.raises(BaseExceptionGroup) as failure:
            server.find_or_create()
    operation, recovery = failure.value.exceptions
    assert isinstance(operation, ValueError)
    assert isinstance(recovery, CreationCleanupError)
    assert isinstance(recovery.__cause__, PermissionError)
    recovery.owner.close()
    assert recovery.owner.closed


@pytest.mark.parametrize("interrupt", [False, True])
def test_server_startup_recovers_receipt_after_client_timeout_or_interrupt(
    server: Server,
    tmp_path: pathlib.Path,
    interrupt: bool,
) -> None:
    """A real startup finishes before a wrapper delays its client completion."""
    wrapper = tmp_path / "client"
    binary = server._require_tmux_bin()
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os, signal, subprocess, sys, time\n"
        "if 'start-server' in sys.argv:\n"
        f"    result = subprocess.run([{binary!r}, *sys.argv[1:]], "
        "capture_output=True)\n"
        "    os.write(1, result.stdout)\n"
        "    os.write(2, result.stderr)\n"
        f"    if {interrupt!r}: os.kill(os.getppid(), signal.SIGINT)\n"
        "    time.sleep(30)\n"
        f"os.execv({binary!r}, [{binary!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o700)
    client = Server(
        socket_path=server.socket_path, tmux_bin=wrapper, config_file="/dev/null"
    )
    server._prepare_socket_directory()
    with pytest.raises(KeyboardInterrupt if interrupt else subprocess.TimeoutExpired):
        client.find_or_create(timeout=0.5)
    assert not server.is_alive()


@pytest.mark.parametrize("kind", ["window", "pane"])
def test_stale_parent_does_not_create_in_replacement(server: Server, kind: str) -> None:
    """An original parent receipt must not become authority over a replacement."""
    session = server.new_session("keeper")
    window = session.new_window(window_name="original")
    server.kill()
    server.new_session("replacement")
    if kind == "window":
        with pytest.raises(exc.StaleTmuxOwner):
            session.find_or_create_window("worker")
    else:
        with pytest.raises((exc.StaleTmuxOwner, exc.LibTmuxException)):
            window.find_or_create_pane("worker")
    assert not server.has_session("worker")


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_nonzero_list_result_is_not_an_empty_match(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """A failed subprocess result must stop acquisition before any create command."""
    server.new_session("keeper")
    original = Server.cmd
    attempted: list[str] = []

    def fail(client: Server, command: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        if any(f"list-{kind}s " in str(arg) for arg in args):
            return original(client, "libtmux-nonexistent-command", timeout=1.0)
        if any(
            "new-session " in str(arg)
            or "new-window " in str(arg)
            or "split-window " in str(arg)
            for arg in args
        ):
            attempted.append(command)
        return original(client, command, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Server, "cmd", fail)
        with pytest.raises(exc.LibTmuxException, match="unknown command"):
            _scope(server, kind)
    assert not attempted


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_concurrent_child_creation_never_owns_the_other_callers_object(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """An external creation between lookup and create exercises the stated race."""
    keeper = server.new_session("keeper")
    original = lifecycle_module._matching_ids
    external: list[Session | Window | Pane] = []

    def race(*args: t.Any, **kwargs: t.Any) -> list[str]:
        matches = original(*args, **kwargs)
        assert not matches
        if kind == "session":
            value: Session | Window | Pane = server.new_session("worker")
        elif kind == "window":
            value = keeper.new_window(window_name="worker")
        else:
            value = keeper.active_window.split(shell="/bin/sh")
            server.cmd(
                "set-option", "-p", "-t", value.id, "@libtmux_pane_key", "worker"
            )
        external.append(value)
        return matches

    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_module, "_matching_ids", race)
        if kind == "session":
            with pytest.raises(exc.LibTmuxException, match="duplicate session"):
                _scope(server, kind)
        else:
            result = _scope(server, kind)
            assert result.created and result.value.id != external[0].id
            result.close()
    assert (
        external[0].id
        in server.cmd(
            f"list-{kind}s",
            *([] if kind == "session" else ["-a"]),
            "-F",
            f"#{{{kind}_id}}",
        ).stdout
    )


@pytest.mark.parametrize("kind", ["session", "window"])
def test_control_characters_in_names_fail_before_creation(
    server: Server, kind: str
) -> None:
    """Name validation reports tmux's constraint before requesting a new object."""
    server.new_session("keeper")
    with pytest.raises(ValueError, match="control characters"):
        _scope(server, kind, "worker\nend")


def test_failed_borrowed_server_command_never_rolls_back_the_daemon(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client error after a borrowed reply leaves the existing server alive."""
    server.new_session("keeper")
    original = Server.cmd

    def fail(client: Server, command: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        result = original(client, command, *args, **kwargs)
        if command == "start-server":
            result.returncode = 1
            result.stderr = ["client failed after existing-server reply"]
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Server, "cmd", fail)
        with pytest.raises(exc.LibTmuxException, match="client failed"):
            server.find_or_create()
    assert server.has_session("keeper")


def test_missing_startup_receipt_reports_uncertainty_and_leaves_daemon_for_inspection(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing output cannot justify destroying a daemon at the selected endpoint."""
    original = Server.cmd

    def lose(client: Server, command: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        result = original(client, command, *args, **kwargs)
        if command == "start-server":
            result.stdout = []
        return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(Server, "cmd", lose)
            with pytest.raises(UnknownCreation, match="inspect the endpoint"):
                server.find_or_create()
        assert server.cmd("display-message", "-p", "#{pid}").returncode == 0
    finally:
        # This fixture alone created the private daemon; its test owns final teardown.
        server.own().close()


@pytest.mark.parametrize("interrupt", [False, True])
def test_startup_failure_before_a_receipt_preserves_cause_or_interruption(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    interrupt: bool,
) -> None:
    """An injected client-start failure preserves the error and accepts no owner."""
    failure = KeyboardInterrupt() if interrupt else PermissionError("client refused")

    def fail(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(Server, "cmd", fail)
        if interrupt:
            with pytest.raises(KeyboardInterrupt) as caught:
                server.find_or_create()
            assert caught.value is failure
            assert "inspect the endpoint" in " ".join(getattr(failure, "__notes__", []))
        else:
            with pytest.raises(UnknownCreation) as unknown:
                server.find_or_create()
            assert unknown.value.__cause__ is failure


def test_server_acquisition_failure_keeps_the_requested_rollback_timeout(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rollback owner receives the caller's timeout."""
    original = lifecycle_module.Owned._destroy
    cleanup_timeouts: list[float] = []
    failure = RuntimeError("acceptance failed")

    def reject(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise failure

    def observe(owner: lifecycle_module.Owned[t.Any], deadline: float) -> None:
        cleanup_timeouts.append(owner._timeout)
        original(owner, deadline)

    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_module, "_verify_identity", reject)
        patch.setattr(lifecycle_module.Owned, "_destroy", observe)
        with pytest.raises(RuntimeError) as caught:
            server.find_or_create(timeout=0.5)
    assert caught.value is failure
    assert cleanup_timeouts == [0.5]
    assert not server.is_alive()
