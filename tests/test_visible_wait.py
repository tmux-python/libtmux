"""Visible text is sampled evidence, including text echoed before execution."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import os
import pathlib
import selectors
import shlex
import subprocess
import sys
import threading
import typing as t

import pytest

from libtmux import exc
from libtmux._internal import visible_wait

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_visible_wait_echo_is_not_execution(
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """An unexecuted shell command can satisfy a visible literal predicate."""
    pane = session.active_window.split(shell="sh")
    marker = tmp_path / "executed"
    pane.send_keys(f"printf ECHO_ONLY; touch {shlex.quote(str(marker))}", enter=False)

    observation = pane.wait_for_text("ECHO_ONLY", timeout=0.5)

    assert "ECHO_ONLY" in observation.text
    assert not marker.exists()
    assert observation.pane_id == pane.pane_id
    assert observation.started_ns <= observation.finished_ns
    assert observation.target_lifetime_verified is None
    assert "capture-pane" in observation.command
    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.lines = ()  # type: ignore[misc]
    pane.kill()
    assert "ECHO_ONLY" in observation.text
    assert session.server.is_alive()


def test_visible_wait_absence_is_one_sample(session: Session) -> None:
    """An absence result retains the exact empty selected sample."""
    pane = session.active_window.split(shell="cat")
    observation = pane.wait_for_text("not-here", present=False, timeout=1e308)
    assert observation.lines == ()
    assert observation.text == ""
    assert observation.start is None
    assert observation.end is None
    assert not observation.join_wrapped


def test_visible_wait_unicode_wrap_selection(session: Session) -> None:
    """Joining wrapped Unicode retains the selected capture and immutable argv."""
    window = session.new_window(window_shell="cat")
    window.resize(width=40, height=10)
    pane = window.active_pane
    assert pane is not None
    text = "éλ" * 30
    pane.send_keys(text, enter=False)
    observation = pane.wait_for_text(
        text, start=0, end=2, join_wrapped=True, timeout=0.5
    )
    assert text in observation.text
    assert isinstance(observation.lines, tuple)
    assert isinstance(observation.command, tuple)
    assert observation.start == 0
    assert observation.end == 2
    assert observation.join_wrapped
    window.kill()
    assert text in observation.text


def test_visible_wait_timeout_distinguishes_no_sample(session: Session) -> None:
    """A zero deadline and a sampled empty pane retain different evidence."""
    pane = session.active_window.split(shell="cat")
    with pytest.raises(exc.WaitTimeout) as no_sample:
        pane.wait_for_text("not-here", timeout=0)
    assert getattr(no_sample.value, "last_observation", "missing") is None
    assert no_sample.value.__cause__ is not None

    with pytest.raises(exc.WaitTimeout) as empty_sample:
        pane.wait_for_text("not-here", timeout=0.1, interval=0.01)
    observation = getattr(empty_sample.value, "last_observation", None)
    assert observation is not None
    assert observation.text == ""
    pane.kill()
    assert observation.text == ""


def test_visible_wait_disappearance_retains_sample(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove the owned pane immediately after a real empty capture."""
    pane = session.active_window.split(shell="cat")
    capture = visible_wait._capture
    samples = []

    def capture_then_remove(*args: t.Any) -> t.Any:
        sample = capture(*args)
        samples.append(sample)
        pane.kill()
        return sample

    monkeypatch.setattr(visible_wait, "_capture", capture_then_remove)
    with pytest.raises(exc.LibTmuxException) as failure:
        pane.wait_for_text("not-here", timeout=0.5, interval=0.001)
    assert len(samples) == 1
    assert isinstance(failure.value.__cause__, subprocess.CalledProcessError)
    observation = getattr(failure.value, "last_observation", None)
    assert observation is not None
    assert observation.text == ""
    assert session.server.is_alive()
    with pytest.raises(exc.LibTmuxException) as missing:
        pane.wait_for_text("not-here", present=False, timeout=0.5)
    assert getattr(missing.value, "last_observation", "missing") is None
    assert isinstance(missing.value.__cause__, subprocess.CalledProcessError)


def test_visible_wait_freezes_target_before_capture(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent facade mutation cannot relabel a capture of the original target."""
    pane = session.active_window.split(shell="cat")
    original_id = pane.pane_id
    capture = visible_wait._capture

    def change_handle_after_capture(*args: t.Any) -> t.Any:
        sample = capture(*args)
        pane.pane_id = "%changed"
        return sample

    monkeypatch.setattr(visible_wait, "_capture", change_handle_after_capture)
    observation = pane.wait_for_text("not-here", present=False, timeout=0.5)
    assert observation.pane_id == original_id
    target_index = observation.command.index("-t")
    assert observation.command[target_index + 1] == original_id


def test_visible_wait_freezes_endpoint_environment(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Changing TMUX_TMPDIR between samples cannot redirect a named socket."""
    pane = session.active_window.split(shell="cat")
    capture = visible_wait._capture
    first_sample = True

    def change_environment_after_capture(*args: t.Any) -> t.Any:
        nonlocal first_sample
        sample = capture(*args)
        if first_sample:
            first_sample = False
            pane.send_keys("same-endpoint", enter=False)
            patch.setenv("TMUX_TMPDIR", str(tmp_path))
        return sample

    with monkeypatch.context() as patch:
        patch.setattr(visible_wait, "_capture", change_environment_after_capture)
        observation = pane.wait_for_text("same-endpoint", interval=0.001, timeout=0.5)
    assert "same-endpoint" in observation.text


@pytest.mark.parametrize("stop", ["deadline", "cancel", "interrupt"])
def test_visible_wait_reaps_owned_client(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    stop: str,
) -> None:
    """Substitute a blocking native client to exercise cancellation during capture."""
    pane = session.active_window.split(shell="cat")
    process_factory = subprocess.Popen
    command = session.server.cmd("display-message", "-p", "#{pid}").cmd
    wait_command = [*command[: command.index("display-message")], "wait-for", "blocked"]
    clients: list[subprocess.Popen[bytes]] = []
    cancel = threading.Event()
    interrupt = KeyboardInterrupt("controlled interrupt")
    check = visible_wait._check
    capture = visible_wait._capture
    samples = 0

    def blocked_client(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[bytes]:
        client = process_factory(wait_command, **kwargs)
        clients.append(client)
        if stop == "cancel":
            cancel.set()
        return client

    def interrupt_check(*args: t.Any) -> float:
        if clients and stop == "interrupt":
            raise interrupt
        return check(*args)

    def capture_then_block(*args: t.Any) -> t.Any:
        nonlocal samples
        if samples == 0:
            result = capture(*args)
            samples += 1
            patch.setattr(subprocess, "Popen", blocked_client)
            return result
        return capture(*args)

    with monkeypatch.context() as patch:
        patch.setattr(visible_wait, "_capture", capture_then_block)
        patch.setattr(visible_wait, "_check", interrupt_check)
        expected = {
            "deadline": exc.WaitTimeout,
            "cancel": concurrent.futures.CancelledError,
            "interrupt": KeyboardInterrupt,
        }[stop]
        with pytest.raises(expected) as failure:
            pane.wait_for_text(
                "not-here", timeout=0.15, interval=0.001, cancel_event=cancel
            )
    assert samples == 1
    assert len(clients) == 1
    client = clients[0]
    assert client.returncode is not None
    assert client.stdout is not None and client.stdout.closed
    assert client.stderr is not None and client.stderr.closed
    observation = getattr(failure.value, "last_observation", None)
    assert observation is not None
    assert observation.text == ""
    if stop == "interrupt":
        assert failure.value is interrupt
    else:
        assert failure.value.__cause__ is not None
    assert session.server.is_alive()
    assert pane.pane_pid is not None
    assert session.server.cmd("display-message", "-p", "usable").stdout == ["usable"]


def test_visible_wait_refuses_invalid_bounds_before_client(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid input cannot reach the native client factory."""
    pane = session.active_window.active_pane
    assert pane is not None

    def forbidden_client(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("invalid bounds spawned a native client")

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", forbidden_client)
        invalid: list[dict[str, t.Any]] = [
            {"timeout": -1},
            {"timeout": float("nan")},
            {"timeout": float("inf")},
            {"timeout": 10**1000},
            {"timeout": True},
            {"timeout": "1"},
            {"interval": 0},
            {"interval": float("inf")},
            {"interval": 1.1},
            {"max_text_codepoints": 0},
            {"max_text_codepoints": 1048577},
            {"max_text_codepoints": True},
            {"start": False},
            {"end": "bad"},
            {"present": "yes"},
            {"cancel_event": object()},
        ]
        for kwargs in invalid:
            with pytest.raises(ValueError):
                pane.wait_for_text("text", **kwargs)
        for text in ["", "x" * 1048577, 12]:
            with pytest.raises(ValueError):
                pane.wait_for_text(text)  # type: ignore[arg-type]


@pytest.mark.parametrize("owner", ["pane", "server"])
@pytest.mark.parametrize("placement", ["instance", "class"])
def test_visible_wait_refuses_custom_routing(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    owner: str,
    placement: str,
) -> None:
    """A custom dispatcher must never be bypassed by a facade-endpoint capture."""
    pane = session.active_window.active_pane
    assert pane is not None
    obj = pane if owner == "pane" else session.server

    def forbidden_dispatch(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("unsupported dispatcher was called")

    with monkeypatch.context() as patch:
        patch.setattr(
            obj if placement == "instance" else type(obj), "cmd", forbidden_dispatch
        )
        patch.setattr(subprocess, "Popen", forbidden_dispatch)
        with pytest.raises(NotImplementedError, match="stock command dispatcher"):
            pane.wait_for_text("text")


def test_visible_wait_presignalled_cancellation_and_engine_refusal(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation before a sample and an injected route never spawn clients."""
    pane = session.active_window.active_pane
    assert pane is not None
    cancel = threading.Event()
    cancel.set()

    def forbidden_client(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("preflight spawned a client")

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", forbidden_client)
        with pytest.raises(concurrent.futures.CancelledError) as failure:
            pane.wait_for_text("text", cancel_event=cancel)
        assert getattr(failure.value, "last_observation", "missing") is None
        assert isinstance(failure.value.__cause__, concurrent.futures.CancelledError)
        patch.setattr(session.server, "_engine", object(), raising=False)
        with pytest.raises(NotImplementedError, match="stock command dispatcher"):
            pane.wait_for_text("text")


@pytest.mark.parametrize("transport", [False, True])
def test_visible_wait_capture_limits(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    transport: bool,
) -> None:
    """A controlled pipe producer tests byte retention and decoded admission."""
    pane = session.active_window.active_pane
    assert pane is not None
    process_factory = subprocess.Popen
    clients: list[subprocess.Popen[bytes]] = []
    size = 70000 if transport else 10

    def oversized_client(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[bytes]:
        client = process_factory(
            [sys.executable, "-c", f"import os; os.write(1, b'x' * {size})"], **kwargs
        )
        clients.append(client)
        return client

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", oversized_client)
        with pytest.raises(exc.LibTmuxException) as failure:
            pane.wait_for_text("x", max_text_codepoints=2, timeout=0.5)
    assert isinstance(failure.value.__cause__, ValueError)
    expected_limit = "transport byte" if transport else "max_text_codepoints"
    assert expected_limit in str(failure.value.__cause__)
    assert getattr(failure.value, "last_observation", "missing") is None
    assert clients[0].returncode is not None
    assert clients[0].stdout is not None and clients[0].stdout.closed


def test_visible_wait_inherited_pipe_does_not_extend_deadline(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pipe holder survives client cleanup and exits on an explicit release."""
    pane = session.active_window.active_pane
    assert pane is not None
    release_read, release_write = os.pipe()
    pid_read, pid_write = os.pipe()
    process_factory = subprocess.Popen
    clients: list[subprocess.Popen[bytes]] = []
    producer = (
        "import os; pid = os.fork(); "
        f"os.write({pid_write}, str(os.getpid()).encode()) if pid == 0 else None; "
        f"os.read({release_read}, 1) if pid == 0 else None"
    )

    def inherited_client(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[bytes]:
        client = process_factory(
            [sys.executable, "-c", producer],
            pass_fds=(release_read, pid_write),
            **kwargs,
        )
        clients.append(client)
        return client

    try:
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "Popen", inherited_client)
            with pytest.raises(exc.WaitTimeout):
                pane.wait_for_text("not-here", timeout=0.15)
        os.close(pid_write)
        pid_write = -1
        with selectors.DefaultSelector() as ready:
            ready.register(pid_read, selectors.EVENT_READ)
            assert ready.select(0.5)
        holder_pid = int(os.read(pid_read, 32))
        os.kill(holder_pid, 0)
        assert clients[0].returncode == 0
        assert clients[0].stdout is not None and clients[0].stdout.closed
        os.write(release_write, b"x")
        with selectors.DefaultSelector() as exited:
            exited.register(pid_read, selectors.EVENT_READ)
            assert exited.select(0.5)
        assert os.read(pid_read, 1) == b""
    finally:
        for descriptor in (release_read, release_write, pid_read, pid_write):
            if descriptor != -1:
                os.close(descriptor)
