"""Session acquisition preserves borrowed resources and receipt-based ownership."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import os
import pathlib
import subprocess
import tempfile
import threading
import typing as t

import pytest

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux import Server, Session


@pytest.mark.parametrize("warm", [False, True])
def test_session_create_reuse_disposition(
    server: Server,
    tmp_path: pathlib.Path,
    warm: bool,
) -> None:
    """Reusing a session neither reapplies creation settings nor acquires cleanup."""
    server.config_file = os.devnull
    if warm:
        server.new_session(session_name="keeper", window_command="cat")
    with pytest.raises(exc.ObjectDoesNotExist):
        server.reuse_session("build")
    assert server.is_alive() is warm
    created = server.create_session(
        "build",
        window_command="cat",
        window_name="original",
        start_directory=tmp_path,
        environment={"ORIGINAL": "kept"},
    )
    assert created.created
    assert created.identity.session_id == created.value.session_id
    assert created.identity.creation_token
    pane = created.value.active_pane
    assert pane is not None and pane.pane_pid is not None
    pid = pane.pane_pid
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(created.identity, "session_id", "$999")  # noqa: B010
    with pytest.raises(exc.TmuxSessionExists) as duplicate:
        server.create_session("build", window_command="exit 99")
    assert isinstance(duplicate.value.__cause__, subprocess.CalledProcessError)
    reused = server.find_or_create_session(
        "build",
        window_command="exit 99",
        window_name="replacement",
        start_directory=tmp_path / "does-not-exist",
        environment={"ORIGINAL": "changed"},
    )
    assert not reused.created
    assert reused.identity.creation_token is None
    assert reused.identity.incarnation_verified is None
    assert reused.value.session_id == created.value.session_id
    failure = RuntimeError("body failed")
    with pytest.raises(RuntimeError) as raised, reused as session:
        assert session.session_id == created.value.session_id
        raise failure
    assert raised.value is failure
    reused.close()
    with server.reuse_session("build") as session:
        assert session.show_environment()["ORIGINAL"] == "kept"
        assert session.active_window is not None
        assert session.active_window.window_name == "original"
    assert created.value.active_pane is not None
    assert created.value.active_pane.pane_pid == pid
    os.kill(int(pid), 0)
    created.close()
    created.close()
    assert not server.has_session("build")
    assert server.is_alive() is warm


@pytest.mark.parametrize("name", ["literal#{pid}", "name with spaces", "ending;"])
def test_session_creation_matches_literal_names(server: Server, name: str) -> None:
    """Format expansion and command separators must not change a requested name."""
    server.config_file = os.devnull
    created = server.find_or_create_session(name, window_command="cat")
    assert created.created and created.value.session_name == name
    borrowed = server.reuse_session(name)
    assert not borrowed.created
    assert borrowed.value.session_id == created.value.session_id
    assert created.preserve() is created.value
    created.close()
    assert server.is_alive()
    retained = server.sessions.get(session_name=name)
    assert retained is not None and retained.session_id == created.value.session_id


def test_session_cleanup_keeps_captured_endpoint(
    server: Server,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Later facade/environment changes cannot redirect the accepted cleanup."""
    server.config_file = os.devnull
    server.new_session(session_name="keeper", window_command="cat")
    result = server.create_session("owned", window_command="cat")
    original = result.value.server
    monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path / "other-root"))
    monkeypatch.setattr(server, "socket_name", "other-endpoint")
    result.close()
    assert not original.has_session("owned")
    assert original.has_session("keeper")


@pytest.mark.parametrize("replacement", ["session", "daemon", "token"])
def test_session_cleanup_refuses_replacement(server: Server, replacement: str) -> None:
    """A reused ID or altered ownership token cannot authorize destruction."""
    server.config_file = os.devnull
    result = server.create_session("owned", window_command="cat")
    server.new_session(session_name="keeper", window_command="cat")
    if replacement == "daemon":
        server.kill()
        other = server.new_session(session_name="replacement", window_command="cat")
        assert other.session_id == result.identity.session_id
    elif replacement == "session":
        result.value.kill()
        other = server.new_session(session_name="owned", window_command="cat")
        assert other.session_id != result.identity.session_id
    else:
        other = result.value
        server.cmd(
            "set-environment",
            "-t",
            result.identity.session_id,
            "LIBTMUX_SESSION_OWNER",
            "changed",
        )
    pane = other.active_pane
    assert pane is not None and pane.pane_pid is not None
    if replacement == "session":
        result.close()
    else:
        with pytest.raises(exc.LibTmuxException, match="identity"):
            result.close()
    assert server.has_session(other.session_name or "")
    os.kill(int(pane.pane_pid), 0)


@pytest.mark.parametrize("warm", [False, True])
def test_session_concurrent_creators(
    server: Server, monkeypatch: pytest.MonkeyPatch, warm: bool
) -> None:
    """Two native creators reconcile only the duplicate-session loser."""
    from libtmux import session_creation

    server.config_file = os.devnull
    if warm:
        server.new_session(session_name="keeper", window_command="cat")
    barrier = threading.Barrier(2)
    local = threading.local()
    original = session_creation._Connection.list_sessions

    def synchronized(
        connection: session_creation._Connection,
    ) -> list[session_creation._Record]:
        records = original(connection)
        if not getattr(local, "observed", False):
            local.observed = True
            barrier.wait(timeout=0.5)
        return records

    monkeypatch.setattr(session_creation._Connection, "list_sessions", synchronized)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(server.find_or_create_session, "build", window_command="cat")
            for _ in range(2)
        ]
        results = [future.result(timeout=0.5) for future in futures]
    assert sorted(result.created for result in results) == [False, True]
    assert results[0].identity.session_id == results[1].identity.session_id
    winner = next(result for result in results if result.created)
    borrowed = next(result for result in results if not result.created)
    borrowed.close()
    assert server.has_session("build")
    winner.close()
    assert server.is_alive() is warm


def test_session_readback_failure_compensates_only_creation(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure after a receipt must clean that session and preserve the cause."""
    from libtmux import session_creation

    server.config_file = os.devnull
    server.new_session(session_name="keeper", window_command="cat")
    failure = RuntimeError("readback failed")

    def failed(*args: object) -> t.NoReturn:
        raise failure

    monkeypatch.setattr(session_creation, "_materialize", failed)
    with pytest.raises(RuntimeError) as raised:
        server.create_session("owned", window_command="cat")
    assert raised.value is failure
    assert not server.has_session("owned")
    assert server.has_session("keeper")
    with pytest.raises(RuntimeError) as reused:
        server.reuse_session("keeper")
    assert reused.value is failure
    assert server.has_session("keeper")


def test_session_scope_retains_body_and_cleanup_errors(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cleanup failure must not replace the original body failure."""
    server.config_file = os.devnull
    server.new_session(session_name="keeper", window_command="cat")
    result = server.create_session("owned", window_command="cat")
    operation_failure = RuntimeError("body failed")
    cleanup_failure = OSError("cleanup failed")
    close = result.close

    def failed() -> t.NoReturn:
        raise cleanup_failure

    monkeypatch.setattr(result, "close", failed)
    with pytest.raises(exc.LibTmuxException) as raised, result as session:
        session.new_window(window_name="child", window_shell="cat")
        raise operation_failure
    error = t.cast("t.Any", raised.value)
    assert error.operation_error is operation_failure
    assert error.cleanup_error is cleanup_failure
    assert error.owner is result
    assert server.has_session("owned") and server.has_session("keeper")
    close()
    assert not server.has_session("owned") and server.has_session("keeper")


def test_session_uncertain_submission_is_not_retried_or_cleaned(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lost creation reply conveys no ownership through a matching name."""
    from libtmux import session_creation

    server.config_file = os.devnull
    server.new_session(session_name="keeper", window_command="cat")
    execute = session_creation._Connection.execute
    failure = subprocess.TimeoutExpired(["tmux", "new-session"], 0.1)
    calls = []

    def lost(
        connection: session_creation._Connection, *args: str
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(args[0])
        result = execute(connection, *args)
        if args[0] == "new-session":
            raise failure
        return result

    monkeypatch.setattr(session_creation._Connection, "execute", lost)
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        server.create_session("uncertain", window_command="cat")
    assert raised.value is failure
    assert calls == ["new-session"]
    assert server.has_session("uncertain") and server.has_session("keeper")


def test_session_creation_refuses_replaced_daemon(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A replacement between lookup and creation must receive no mutation."""
    from libtmux import session_creation

    server.config_file = os.devnull
    server.new_session(session_name="keeper", window_command="cat")
    original = session_creation._Connection.list_sessions

    def replaced(
        connection: session_creation._Connection,
    ) -> list[session_creation._Record]:
        records = original(connection)
        server.kill()
        server.new_session(session_name="replacement", window_command="cat")
        return records

    monkeypatch.setattr(session_creation._Connection, "list_sessions", replaced)
    with pytest.raises(exc.LibTmuxException, match="identity"):
        server.find_or_create_session("build", window_command="cat")
    assert not server.has_session("build")
    assert server.has_session("replacement")


@pytest.mark.parametrize("dispatch", ["class", "instance", "engine", "_engine"])
def test_session_acquisition_refuses_custom_dispatch(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    dispatch: str,
) -> None:
    """Unsupported routing cannot silently create on the facade endpoint."""
    from libtmux import Server

    def unexpected(*args: object, **kwargs: object) -> t.NoReturn:
        pytest.fail("the unsupported dispatcher was called")

    with monkeypatch.context() as patch:
        if dispatch == "class":
            patch.setattr(Server, "cmd", unexpected)
        elif dispatch == "instance":
            patch.setattr(server, "cmd", unexpected)
        else:
            patch.setattr(server, dispatch, object(), raising=False)
        with pytest.raises(NotImplementedError):
            server.create_session("wrong-endpoint", window_command="cat")
    assert not server.is_alive()


@pytest.mark.parametrize("phase", ["lookup", "creation"])
def test_session_native_failures_are_not_absence(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    """A non-conflict native error must preserve its raw cause and stop mutation."""
    from libtmux import session_creation

    server.config_file = os.devnull
    server.new_session(session_name="keeper", window_command="cat")
    execute = session_creation._Connection.execute

    def denied(
        connection: session_creation._Connection, *args: str
    ) -> subprocess.CompletedProcess[bytes]:
        target = "list-sessions" if phase == "lookup" else "new-session"
        if args[0] == target:
            return subprocess.CompletedProcess(
                args, 1, b"unrelated diagnostic\n", b"permission denied\n"
            )
        return execute(connection, *args)

    monkeypatch.setattr(session_creation._Connection, "execute", denied)
    with pytest.raises(exc.LibTmuxException, match="permission denied") as raised:
        if phase == "lookup":
            server.find_or_create_session("build", window_command="cat")
        else:
            server.create_session("build", window_command="cat")
    assert isinstance(raised.value.__cause__, subprocess.CalledProcessError)
    assert raised.value.__cause__.stdout == b"unrelated diagnostic\n"
    assert not server.has_session("build") and server.has_session("keeper")


def test_session_missing_creation_receipt_is_unknown(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Native success without its receipt cannot grant cleanup or trigger retry."""
    from libtmux import session_creation

    server.config_file = os.devnull
    execute = session_creation._Connection.execute

    def lost(
        connection: session_creation._Connection, *args: str
    ) -> subprocess.CompletedProcess[bytes]:
        result = execute(connection, *args)
        if args[0] == "new-session":
            result.stdout = b""
        return result

    monkeypatch.setattr(session_creation._Connection, "execute", lost)
    with pytest.raises(exc.LibTmuxException, match="unknown"):
        server.create_session("uncertain", window_command="cat")
    assert server.has_session("uncertain")


def test_session_deleted_between_lookup_and_creation(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient competing session supplies neither identity nor ownership."""
    from libtmux import session_creation

    server.config_file = os.devnull
    server.new_session(session_name="keeper", window_command="cat")
    original = session_creation._Connection.list_sessions
    transient_ids = []

    def deleted(
        connection: session_creation._Connection,
    ) -> list[session_creation._Record]:
        records = original(connection)
        transient = server.new_session(session_name="build", window_command="cat")
        transient_ids.append(transient.session_id)
        transient.kill()
        return records

    monkeypatch.setattr(session_creation._Connection, "list_sessions", deleted)
    result = server.find_or_create_session("build", window_command="cat")
    assert result.created and result.identity.session_id not in transient_ids
    result.close()
    assert server.has_session("keeper") and not server.has_session("build")


def test_session_conflict_reconciliation_stops_after_one_read(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disappeared winner must not trigger another creation attempt."""
    from libtmux import session_creation

    server.config_file = os.devnull
    server.new_session(session_name="keeper", window_command="cat")
    original = session_creation._Connection.list_sessions
    competitors: list[Session] = []
    reads = 0

    def disappearing(
        connection: session_creation._Connection,
    ) -> list[session_creation._Record]:
        nonlocal reads
        reads += 1
        if reads == 2:
            competitors[0].kill()
        records = original(connection)
        if reads == 1:
            competitors.append(
                server.new_session(session_name="build", window_command="cat")
            )
        return records

    monkeypatch.setattr(session_creation._Connection, "list_sessions", disappearing)
    with pytest.raises(exc.TmuxSessionExists):
        server.find_or_create_session("build", window_command="cat")
    assert reads == 2
    assert not server.has_session("build") and server.has_session("keeper")


def test_session_cleanup_freezes_relative_socket_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing cwd cannot reinterpret a captured relative TMUX_TMPDIR."""
    from libtmux import Server

    with tempfile.TemporaryDirectory(prefix="l804wd-", dir="/tmp") as directory:
        root = pathlib.Path(directory)
        (root / "socket-root").mkdir()
        other = root / "other"
        other.mkdir()
        (other / "socket-root").mkdir()
        socket_path = root / "socket-root" / f"tmux-{os.getuid()}" / "owned"
        with monkeypatch.context() as patch:
            patch.chdir(root)
            patch.setenv("TMUX_TMPDIR", "socket-root")
            server = Server(socket_name="owned", config_file=os.devnull)
            try:
                result = server.create_session("owned", window_command="cat")
                result.value.server.new_session(
                    session_name="keeper", window_command="cat"
                )
                patch.chdir(other)
                result.close()
                assert not result.value.server.has_session("owned")
                assert result.value.server.has_session("keeper")
            finally:
                Server(socket_path=socket_path).kill()


def test_session_acquisition_resolves_explicit_binary_name(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit executable basename still uses the captured PATH."""
    server.config_file = os.devnull
    monkeypatch.setattr(server, "tmux_bin", "tmux")
    result = server.create_session("owned", window_command="cat")
    assert (
        result.identity.server_version
        == server.cmd("display-message", "-p", "#{version}").stdout[0]
    )
    result.close()


def test_session_reuse_ignores_unowned_token(server: Server) -> None:
    """Borrowed environment text must not become a format or ownership proof."""
    server.config_file = os.devnull
    legacy = server.new_session(
        session_name="legacy",
        window_command="cat",
        environment={"LIBTMUX_SESSION_OWNER": "#{?1,not-a-token,}"},
    )
    result = server.reuse_session("legacy")
    assert not result.created and result.identity.creation_token is None
    assert result.identity.incarnation_verified is None
    assert result.value.session_id == legacy.session_id
    result.close()
    assert server.has_session("legacy")
