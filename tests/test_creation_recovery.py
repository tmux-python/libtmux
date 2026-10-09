"""Creation failures retain their daemon receipt and recover known resources."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import typing as t

import pytest

import libtmux.lifecycle as lifecycle_module
import libtmux.server as server_module
from libtmux import Pane, Server, Session, Window, exc
from libtmux.lifecycle import CreationCleanupError, UnknownCreation
from libtmux.neo import parse_output
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.common import tmux_cmd


def _create(server: Server, kind: str) -> Session | Window | Pane:
    if kind == "session":
        return server.new_session(session_name="created")
    session = server.sessions.get(session_name="keeper")
    assert session is not None
    if kind == "window":
        return session.new_window(window_name="created")
    return session.active_window.split()


def _ids(server: Server, kind: str) -> list[str]:
    result = server.cmd(
        f"list-{kind}s",
        *(("-a",) if kind != "session" else ()),
        "-F",
        f"#{{{kind}_id}}",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
@pytest.mark.parametrize(
    "failure", [RuntimeError("readback failed"), KeyboardInterrupt()]
)
def test_known_creation_rolls_back_failed_materialization(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    failure: BaseException,
) -> None:
    """A real create succeeds before an injected parser or query failure."""
    server.new_session(session_name="keeper")
    before = _ids(server, kind)

    def fail_readback(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise failure

    with monkeypatch.context() as patch:
        if kind == "session":
            patch.setattr(server_module, "parse_output", fail_readback)
        elif kind == "window":
            patch.setattr(Window, "from_window_id", fail_readback)
        else:
            patch.setattr(Pane, "from_pane_id", fail_readback)
        with pytest.raises(type(failure)) as caught:
            _create(server, kind)
    assert caught.value is failure
    assert _ids(server, kind) == before
    assert server.has_session("keeper")


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_interrupted_client_retains_completed_creation_receipt(
    server: Server,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    interrupt: bool,
) -> None:
    """Timeout or interruption after stdout still recovers the reported ID."""
    server.new_session(session_name="keeper")
    before = _ids(server, kind)
    wrapper = tmp_path / "tmux-client"
    pid_file = tmp_path / "wrapper-pid"
    binary = server._require_tmux_bin()
    operation = {
        "session": "new-session",
        "window": "new-window",
        "pane": "split-window",
    }[kind]
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, signal, subprocess, sys, time\n"
        f"if any({operation + ' '!r} in arg for arg in sys.argv):\n"
        f"    result = subprocess.run([{binary!r}, *sys.argv[1:]], "
        "capture_output=True)\n"
        "    assert result.returncode == 0 and result.stdout\n"
        "    os.write(1, result.stdout)\n"
        "    os.write(2, result.stderr)\n"
        f"    pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        f"    if {interrupt!r}: os.kill(os.getppid(), signal.SIGINT)\n"
        "    time.sleep(30)\n"
        f"os.execv({binary!r}, [{binary!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o700)
    client = Server(socket_path=server.socket_path, tmux_bin=wrapper)
    command = client.cmd

    def short_deadline(cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        if any(operation + " " in str(arg) for arg in args):
            kwargs["timeout"] = 1.0
        return command(cmd, *args, **kwargs)

    monkeypatch.setattr(client, "cmd", short_deadline)
    failure = KeyboardInterrupt if interrupt else subprocess.TimeoutExpired
    with pytest.raises(failure):
        _create(client, kind)
    assert _ids(server, kind) == before
    with pytest.raises(ChildProcessError):
        os.waitpid(int(pid_file.read_text()), os.WNOHANG)


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_failed_acquisition_rollback_exposes_retry_owner(
    server: Server, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Retain the operation error, cleanup error and exact owner for retry."""
    server.new_session(session_name="keeper")
    before = _ids(server, kind)
    command = server.cmd
    failure = KeyboardInterrupt()
    cleanup_error = PermissionError("rollback denied")

    def fail_readback(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise failure

    def deny_cleanup(cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        if any(str(arg).startswith(f"kill-{kind} ") for arg in args):
            raise cleanup_error
        return command(cmd, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(server, "cmd", deny_cleanup)
        if kind == "session":
            patch.setattr(server_module, "parse_output", fail_readback)
        elif kind == "window":
            patch.setattr(Window, "from_window_id", fail_readback)
        else:
            patch.setattr(Pane, "from_pane_id", fail_readback)
        with pytest.raises(BaseExceptionGroup) as caught:
            _create(server, kind)
    assert caught.value.exceptions[0] is failure
    recovery = caught.value.exceptions[1]
    assert isinstance(recovery, CreationCleanupError)
    assert recovery.__cause__ is cleanup_error
    owner = recovery.owner
    assert owner.cleanup_error is cleanup_error
    assert not owner.closed
    monkeypatch.setattr(owner._client, "cmd", command)
    owner.close()
    assert _ids(server, kind) == before


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_empty_successful_reply_exposes_unknown_creation(
    server: Server, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Missing stdout cannot prove absence after a real successful create."""
    server.new_session(session_name="keeper")
    before = _ids(server, kind)
    command = server.cmd
    operation = {
        "session": "new-session",
        "window": "new-window",
        "pane": "split-window",
    }[kind]

    def empty_reply(cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        result = command(cmd, *args, **kwargs)
        if any(operation + " " in str(arg) for arg in args):
            assert result.returncode == 0 and result.stdout
            result.stdout = []
        return result

    with monkeypatch.context() as patch:
        patch.setattr(server, "cmd", empty_reply)
        with pytest.raises(UnknownCreation, match="inspect the endpoint"):
            _create(server, kind)
    assert len(_ids(server, kind)) == len(before) + 1


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_materialization_cannot_accept_a_replacement_daemon(
    server: Server, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """The receipt must remain authoritative across the first snapshot query."""
    server.new_session(session_name="keeper")
    owner = server.own()
    original: t.Callable[..., t.Any]
    if kind == "session":
        original = parse_output
    elif kind == "window":
        original = Window.from_window_id
    else:
        original = Pane.from_pane_id
    replace = True
    replacement: list[Session | Window | Pane] = []

    def replace_before_readback(*args: t.Any, **kwargs: t.Any) -> t.Any:
        nonlocal replace
        if replace:
            replace = False
            owner.close()
            server.new_session(session_name="keeper")
            replacement.append(_create(server, kind))
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        if kind == "session":
            patch.setattr(server_module, "parse_output", replace_before_readback)
        elif kind == "window":
            patch.setattr(Window, "from_window_id", replace_before_readback)
        else:
            patch.setattr(Pane, "from_pane_id", staticmethod(replace_before_readback))
        with pytest.raises(exc.StaleTmuxOwner):
            _create(server, kind)
    assert getattr(replacement[0], f"{kind}_id") in _ids(server, kind)


def test_interrupted_rollback_preserves_interrupt_and_retry_owner(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupt during rollback remains a BaseException in the group."""
    server.new_session(session_name="keeper")
    before = _ids(server, "window")
    failure = RuntimeError("snapshot failed")
    interrupted = KeyboardInterrupt()
    command = server.cmd

    def fail_readback(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise failure

    def interrupt_cleanup(cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        if any(str(arg).startswith("kill-window ") for arg in args):
            raise interrupted
        return command(cmd, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(server, "cmd", interrupt_cleanup)
        patch.setattr(Window, "from_window_id", fail_readback)
        with pytest.raises(BaseExceptionGroup) as caught:
            _create(server, "window")
    assert not isinstance(caught.value, Exception)
    assert caught.value.exceptions[0] is failure
    rollback = caught.value.exceptions[1]
    assert isinstance(rollback, BaseExceptionGroup)
    assert rollback.exceptions[0] is interrupted
    recovery = rollback.exceptions[1]
    assert isinstance(recovery, CreationCleanupError)
    assert recovery.__cause__ is interrupted
    assert recovery.owner.cleanup_error is interrupted
    monkeypatch.setattr(recovery.owner._client, "cmd", command)
    recovery.owner.close()
    assert _ids(server, "window") == before


def test_select_existing_still_recovers_a_reported_new_window(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The select flag cannot exempt a known newly created ID from rollback."""
    session = server.new_session(session_name="keeper")
    before = _ids(server, "window")
    failure = RuntimeError("window readback failed")

    def fail_readback(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(Window, "from_window_id", fail_readback)
        with pytest.raises(RuntimeError) as caught:
            session.new_window(window_name="created", select_existing=True)
    assert caught.value is failure
    assert _ids(server, "window") == before


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_interruption_before_receipt_decode_recovers_observed_output(
    server: Server, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """An interruption between client completion and receipt decoding keeps its ID."""
    server.new_session(session_name="keeper")
    before = _ids(server, kind)
    decode = lifecycle_module._creation_receipt
    interrupted = KeyboardInterrupt()
    first = True

    def interrupt_once(*args: t.Any, **kwargs: t.Any) -> t.Any:
        nonlocal first
        if first:
            first = False
            raise interrupted
        return decode(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_module, "_creation_receipt", interrupt_once)
        with pytest.raises(KeyboardInterrupt) as caught:
            _create(server, kind)
    assert caught.value is interrupted
    assert _ids(server, kind) == before


def test_creation_matches_native_names_and_preserves_environment(
    server: Server,
) -> None:
    """Command parsing preserves tmux naming behavior and literal environment data."""
    name = "quotes ' \" ; $HOME #{pane_id}"
    value = "literal ; ' \" $HOME $(printf injected) #{pane_id}"
    with (
        server.new_session(session_name="keeper") as session,
        session.new_window(
            window_name=name,
            environment={"LIBTMUX_CREATION_TEST": value},
            window_shell="/bin/sh",
        ) as window,
    ):
        window.set_option("automatic-rename", False)
        native = server.cmd(
            "new-window",
            "-d",
            "-t",
            session.session_id,
            "-n",
            name,
            "-P",
            "-F",
            "#{window_name}",
        )
        assert native.returncode == 0 and native.stdout
        assert window.window_name == native.stdout[0]
        pane = window.active_pane
        assert pane is not None
        command = 'printf "%s" "$LIBTMUX_CREATION_TEST"'
        pane.send_keys(command)

        def has_value() -> bool:
            return any(value in line for line in pane.capture_pane())

        retry_until(has_value, seconds=2)
        assert has_value()


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_context_entry_keeps_the_creation_daemon(server: Server, kind: str) -> None:
    """A replacement between create and context entry cannot become owned."""
    server.new_session(session_name="keeper")
    created = _create(server, kind)
    server.own().close()
    server.new_session(session_name="keeper")
    replacement = _create(server, kind)
    replacement_id = getattr(replacement, f"{kind}_id")
    assert getattr(created, f"{kind}_id") == replacement_id
    with pytest.raises(exc.StaleTmuxOwner), created:
        pytest.fail("entered ownership on a replacement daemon")
    assert replacement_id in _ids(server, kind)


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_completed_failure_with_receipt_recovers_created_resource(
    server: Server, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """A nonzero client result must not discard its valid creation receipt."""
    server.new_session(session_name="keeper")
    before = _ids(server, kind)
    command = server.cmd
    operation = {
        "session": "new-session",
        "window": "new-window",
        "pane": "split-window",
    }[kind]

    def failed_result(cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        result = command(cmd, *args, **kwargs)
        if any(operation + " " in str(arg) for arg in args):
            assert result.returncode == 0 and result.stdout
            result.returncode = 77
            result.stderr = ["failure after receipt"]
        return result

    with monkeypatch.context() as patch:
        patch.setattr(server, "cmd", failed_result)
        with pytest.raises(exc.LibTmuxException, match="failure after receipt"):
            _create(server, kind)
    assert _ids(server, kind) == before


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_context_acceptance_failure_recovers_known_creation(
    server: Server, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Context entry recovers a known create if its acceptance query fails."""
    server.new_session(session_name="keeper")
    before = _ids(server, kind)
    created = _create(server, kind)
    assert created._creation_receipt is not None
    client = created._creation_receipt.client
    command = client.cmd
    failure = PermissionError("acceptance query failed")

    def denied(cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        if "display-message" in args:
            raise failure
        return command(cmd, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(client, "cmd", denied)
        with pytest.raises(PermissionError) as caught, created:
            pytest.fail("entered ownership after a failed acceptance query")
    assert caught.value is failure
    assert _ids(server, kind) == before
