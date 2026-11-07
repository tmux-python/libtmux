"""Fresh program completion, ownership and explicit cleanup."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import os
import pathlib
import subprocess
import sys
import threading
import typing as t

import pytest

from libtmux import exc
from libtmux._internal import program
from libtmux.common import has_gte_version

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.session import Session


requires_events = pytest.mark.skipif(
    not has_gte_version("3.8"), reason="native program observers require tmux 3.8"
)


@requires_events
def test_program_exit_and_retained_capture(session: Session) -> None:
    """Exit status and capture survive cleanup without deleting the parent."""
    arguments = ["a b", "", "$HOME", "-n", "semi;", "line\nbreak"]
    parent = session.cmd("display-message", "-p", "#{pid}|#{session_id}").stdout
    job = session.run_program(
        [
            sys.executable,
            "-c",
            "import json,sys; print(json.dumps(sys.argv[1:])); sys.exit(7)",
            *arguments,
        ]
    )
    try:
        result = job.wait(timeout=1)
        assert result.exit_status == 7
        assert result.exit_signal is None
        observation = job.collect(start=-10)
        assert json.dumps(arguments) in observation.text
        assert observation.pane_id == result.pane_id == job.pane_id
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.exit_status = 0  # type: ignore[misc]
    finally:
        job.cleanup()
    assert session.cmd("display-message", "-p", "#{pid}|#{session_id}").stdout == parent
    assert json.dumps(arguments) in observation.text


@requires_events
def test_unrelated_exit_cannot_complete_program(session: Session) -> None:
    """A real status-9 exit cannot release the selected live status-7 program."""
    job = session.run_program(
        [sys.executable, "-c", "import os; os.read(0,1); raise SystemExit(7)"]
    )
    other = session.run_program([sys.executable, "-c", "raise SystemExit(9)"])
    try:
        assert other.wait(timeout=1).exit_status == 9
        with pytest.raises(exc.WaitTimeout) as caught:
            job.wait(timeout=0.01)
        assert t.cast("program._FailureEvidence", caught.value).last_observation is None
        assert caught.value.__cause__ is not None
        session.cmd("send-keys", "-t", job.pane_id, "x", "Enter")
        assert job.wait(timeout=1).exit_status == 7
    finally:
        job.terminate()
        job.cleanup()
        other.cleanup()


@requires_events
def test_cancel_before_launch_cleans_ready_observer(
    session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Cancel at the native readiness boundary, before the producer can run."""
    cancel = threading.Event()
    marker = tmp_path / "started"
    before = session.server.cmd("list-panes", "-a", "-F", "#{pane_id}").stdout
    original = program._Client.until
    clients = []

    def ready_then_cancel(client: program._Client, *args: t.Any) -> None:
        original(client, *args)
        if "-C" in client.command:
            clients.append(client)
            cancel.set()

    with monkeypatch.context() as patch:
        patch.setattr(program._Client, "until", ready_then_cancel)
        with pytest.raises(concurrent.futures.CancelledError):
            session.run_program(
                [
                    sys.executable,
                    "-c",
                    "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
                    str(marker),
                ],
                cancel_event=cancel,
            )
    assert not marker.exists()
    assert session.server.cmd("list-panes", "-a", "-F", "#{pane_id}").stdout == before
    assert clients and all(client.process.poll() is not None for client in clients)


@requires_events
def test_cleanup_failure_retains_original_and_owner(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inject cleanup failure after real reaping to exercise paired errors safely."""
    original = OSError("registration read failed")
    cleanup = OSError("observer cleanup failed")
    close = program._Client.close
    until = program._Client.until

    def fail_ready(client: program._Client, *args: t.Any) -> None:
        until(client, *args)
        if "-C" in client.command:
            raise original

    def fail_close(client: program._Client) -> None:
        close(client)
        if "-C" in client.command:
            raise cleanup

    before = session.server.cmd("list-panes", "-a", "-F", "#{pane_id}").stdout
    with monkeypatch.context() as patch:
        patch.setattr(program._Client, "until", fail_ready)
        patch.setattr(program._Client, "close", fail_close)
        with pytest.raises(exc.LibTmuxException) as caught:
            session.run_program([sys.executable, "-c", "raise SystemExit(7)"])
    assert caught.value.__cause__ is original
    assert t.cast("program._FailureEvidence", caught.value).operation_error is original
    assert t.cast("program._FailureEvidence", caught.value).cleanup_errors == (cleanup,)
    t.cast("program._FailureEvidence", caught.value).owner.cleanup()
    assert session.server.cmd("list-panes", "-a", "-F", "#{pane_id}").stdout == before


@requires_events
def test_program_signal_and_capture_admission(session: Session) -> None:
    """Signals stay distinct from exit codes; capture bounds preserve prior evidence."""
    job = session.run_program(
        [
            sys.executable,
            "-c",
            (
                "import os,signal; print('%error 1 2 0',flush=True); "
                "os.kill(os.getpid(),signal.SIGTERM)"
            ),
        ]
    )
    try:
        result = job.wait(timeout=1)
        assert result.exit_status is None
        assert result.exit_signal in ("TERM", "15")
        observation = job.collect(start=-10)
        assert "%error 1 2 0" in observation.text
        with pytest.raises(exc.LibTmuxException, match="max_text_codepoints") as caught:
            job.collect(max_text_codepoints=1)
        assert (
            t.cast("program._FailureEvidence", caught.value).last_capture is observation
        )
        assert (
            t.cast("program._FailureEvidence", caught.value).last_observation is result
        )
        assert isinstance(caught.value.__cause__, ValueError)
    finally:
        job.cleanup()


def test_invalid_program_and_custom_routing_refuse_before_client(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Native creation must never silently bypass an unsupported dispatcher."""

    def forbidden(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("a refused program started a native client")

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", forbidden)
        for timeout in (-1, float("inf"), float("nan"), True, 10**1000):
            with pytest.raises(ValueError):
                session.run_program(["program", "arg"], timeout=timeout)
        for argv in (["program"], ["", "arg"], ["program", "\0"], "program"):
            with pytest.raises((TypeError, ValueError)):
                session.run_program(argv)
        for attribute in ("engine", "_engine"):
            patch.setattr(session.server, attribute, object(), raising=False)
            with pytest.raises(NotImplementedError):
                session.run_program(["program", "arg"])
            patch.delattr(session.server, attribute)
        patch.setattr(session, "cmd", forbidden)
        with pytest.raises(NotImplementedError):
            session.run_program(["program", "arg"])


@requires_events
def test_program_cancel_and_explicit_termination(session: Session) -> None:
    """Cancelling a wait preserves the live producer and its observer."""
    job = session.run_program([sys.executable, "-c", "import os; os.read(0,1)"])
    cancel = threading.Event()
    cancel.set()
    try:
        with pytest.raises(concurrent.futures.CancelledError):
            job.wait(timeout=1, cancel_event=cancel)
        with pytest.raises(exc.WaitTimeout):
            job.wait(timeout=0)
        with pytest.raises(exc.LibTmuxException, match="running"):
            job.cleanup()
        assert session.cmd(
            "display-message", "-p", "-t", job.pane_id, "#{pane_dead}"
        ).stdout == ["0"]
        terminated = job.terminate()
        assert terminated.pane_removed is True
        assert terminated.exit_status is None
    finally:
        job.cleanup()
    assert session.server.is_alive()


@requires_events
def test_program_rejects_replacement_lifetime(session: Session) -> None:
    """A later program in the same pane cannot supply this program's status."""
    job = session.run_program([sys.executable, "-c", "import os; os.read(0,1)"])
    session.cmd(
        "respawn-pane",
        "-k",
        "-t",
        job.pane_id,
        sys.executable,
        "-c",
        "raise SystemExit(9)",
    )
    try:
        with pytest.raises(exc.LibTmuxException, match="lifetime"):
            job.wait(timeout=1)
        with pytest.raises(exc.LibTmuxException):
            job.terminate()
        with pytest.raises(exc.LibTmuxException):
            job.cleanup()
        assert session.cmd(
            "display-message", "-p", "-t", job.pane_id, "#{pane_id}"
        ).stdout == [job.pane_id]
    finally:
        # The replacement is deliberately created by this test and removed here.
        session.cmd("kill-pane", "-t", job.pane_id)
        job.cleanup()


@requires_events
def test_lost_observer_refuses_destructive_operations(session: Session) -> None:
    """Losing observation cannot authorize killing an unproved program lifetime."""
    job = session.run_program([sys.executable, "-c", "import os; os.read(0,1)"])
    assert job._generation is not None
    job._generation.close()
    try:
        with pytest.raises(exc.LibTmuxException) as caught:
            job.wait(timeout=1)
        assert t.cast("program._FailureEvidence", caught.value).last_observation is None
        assert caught.value.__cause__ is not None
        with pytest.raises(exc.LibTmuxException):
            job.terminate()
        assert session.cmd(
            "display-message", "-p", "-t", job.pane_id, "#{pane_dead}"
        ).stdout == ["0"]
    finally:
        session.cmd("kill-pane", "-t", job.pane_id)
        job.cleanup()


@requires_events
def test_completed_cleanup_preserves_cleanup_cause(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cleanup-only failure keeps the real cause and can be retried."""
    job = session.run_program([sys.executable, "-c", "raise SystemExit(7)"])
    job.wait(timeout=1)
    failure = OSError("generation cleanup failed")
    close = program._Client.close

    def failed_close(client: program._Client) -> None:
        close(client)
        if client is job._generation:
            raise failure

    with monkeypatch.context() as patch:
        patch.setattr(program._Client, "close", failed_close)
        with pytest.raises(exc.LibTmuxException) as caught:
            job.cleanup()
    assert caught.value.__cause__ is failure
    assert t.cast("program._FailureEvidence", caught.value).cleanup_errors == (failure,)
    job.cleanup()


@requires_events
def test_setup_rejects_replaced_server(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replace an owned test daemon between its creation receipt and setup."""
    guarded = program._Program._guarded
    replacement: list[Pane] = []

    def replace_before_setup(job: program._Program, *args: t.Any) -> bytes:
        if not replacement:
            session.server.kill()
            session.server.new_session(session_name="foreign0")
            parent = session.server.new_session(session_name="foreign1")
            pane = parent.new_window(window_name="foreign").active_pane
            assert pane is not None and pane.pane_id == job.pane_id
            replacement.append(pane)
        return guarded(job, *args)

    with monkeypatch.context() as patch:
        patch.setattr(program._Program, "_guarded", replace_before_setup)
        with pytest.raises(exc.LibTmuxException, match="ownership") as caught:
            session.run_program([sys.executable, "-c", "raise SystemExit(7)"])
    assert t.cast("program._FailureEvidence", caught.value).cleanup_errors
    assert replacement[0].cmd(
        "display-message", "-p", "#{pane_dead}|#{window_name}"
    ).stdout == ["0|foreign"]
    assert replacement[0].cmd(
        "show-options", "-A", "-p", "-v", "remain-on-exit"
    ).stdout == ["off"]


@requires_events
def test_missing_creation_receipt_stays_uncertain(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drop a real accepted creation's receipt; do not infer ownership by name."""
    run = program._Program._run
    before = len(session.windows)

    def lose_receipt(
        job: program._Program, args: tuple[str, ...], *rest: t.Any
    ) -> bytes:
        output = run(job, args, *rest)
        if args[0] == "if-shell" and args[5].startswith("new-window "):
            return b""
        return output

    with monkeypatch.context() as patch:
        patch.setattr(program._Program, "_run", lose_receipt)
        with pytest.raises(exc.LibTmuxException, match="unknown") as caught:
            session.run_program([sys.executable, "-c", "raise SystemExit(7)"])
    assert t.cast("program._FailureEvidence", caught.value).last_observation is None
    assert t.cast("program._FailureEvidence", caught.value).owner._receipt == ()
    assert len(session.windows) == before + 1


@requires_events
def test_standalone_program_preserves_parent(
    session: Session, tmp_path: pathlib.Path
) -> None:
    """Ignore caller configuration and attachment while preserving its parent."""
    script = pathlib.Path(__file__).parents[1] / "examples" / "owned_program.py"
    (tmp_path / ".tmux.conf").write_text(
        'set-hook -g after-new-session "kill-server"\n'
    )
    environment = {
        **os.environ,
        "HOME": str(tmp_path),
        "TMUX": "caller-attachment,1,0",
        "TMUX_PANE": "%0",
    }
    before = session.cmd(
        "display-message", "-p", "#{pid}|#{session_id}|#{pane_id}|#{pane_pid}"
    ).stdout
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            check=True,
            timeout=1,
            env=environment,
        )
        assert result.stdout == "exit status: 7\nhello from the program\n"
        assert (
            session.cmd(
                "display-message", "-p", "#{pid}|#{session_id}|#{pane_id}|#{pane_pid}"
            ).stdout
            == before
        )


@pytest.mark.skipif(has_gte_version("3.8"), reason="exercise the older-daemon refusal")
def test_program_version_gate_precedes_creation(session: Session) -> None:
    """Refuse unsupported jobs before changing the older daemon."""
    before = session.cmd("list-windows", "-F", "#{window_id}").stdout
    with pytest.raises(exc.LibTmuxException, match=r"tmux 3\.8"):
        session.run_program([sys.executable, "-c", "raise SystemExit(7)"])
    assert session.cmd("list-windows", "-F", "#{window_id}").stdout == before


@requires_events
def test_program_accepts_connected_next_version(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Qualify the next-release spelling without requiring a development binary."""
    run = program._Program._run

    def next_version(
        job: program._Program, args: tuple[str, ...], *rest: t.Any
    ) -> bytes:
        output = run(job, args, *rest)
        if args[-1] == "#{pid}|#{start_time}|#{session_id}|#{version}":
            return output.rsplit(b"|", 1)[0] + b"|next-3.9\n"
        return output

    with monkeypatch.context() as patch:
        patch.setattr(program._Program, "_run", next_version)
        job = session.run_program([sys.executable, "-c", "raise SystemExit(7)"])
    try:
        assert job.wait(timeout=1).exit_status == 7
    finally:
        job.cleanup()


@requires_events
@pytest.mark.parametrize("interrupt", [False, True])
def test_interrupted_collection_reaps_only_its_client(
    session: Session, monkeypatch: pytest.MonkeyPatch, interrupt: bool
) -> None:
    """Block a real native client to qualify deadline and interruption cleanup."""
    job = session.run_program([sys.executable, "-c", "import os; os.read(0,1)"])
    before = session.cmd(
        "display-message", "-p", "#{pid}|#{pane_id}|#{pane_pid}"
    ).stdout
    original = program._Client.until
    interrupted = KeyboardInterrupt()
    clients = []

    def native_wait(client: program._Client, *args: t.Any) -> None:
        if client.command[-1] == "never-signalled-program-client":
            clients.append(client)
            if interrupt:
                raise interrupted
        original(client, *args)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                job,
                "_guard",
                lambda _, **kwargs: ("wait-for", "never-signalled-program-client"),
            )
            patch.setattr(program._Client, "until", native_wait)
            with pytest.raises(
                KeyboardInterrupt if interrupt else exc.WaitTimeout
            ) as caught:
                job.collect(timeout=0.05)
        if interrupt:
            assert caught.value is interrupted
        assert clients and all(client.closed for client in clients)
        assert all(client.process.poll() is not None for client in clients)
        assert (
            session.cmd("display-message", "-p", "#{pid}|#{pane_id}|#{pane_pid}").stdout
            == before
        )
    finally:
        job.terminate()
        job.cleanup()


@requires_events
def test_cleanup_preserves_borrowed_pane_in_owned_window(session: Session) -> None:
    """Removing the created pane must not delete a borrowed pane joined beside it."""
    borrowed = session.new_window(window_name="borrowed").active_pane
    assert borrowed is not None
    before = borrowed.cmd("display-message", "-p", "#{pane_id}|#{pane_pid}").stdout
    job = session.run_program([sys.executable, "-c", "raise SystemExit(7)"])
    job.wait(timeout=1)
    session.cmd("join-pane", "-s", borrowed.pane_id, "-t", job.pane_id)
    job.cleanup()
    assert (
        borrowed.cmd("display-message", "-p", "#{pane_id}|#{pane_pid}").stdout == before
    )


@requires_events
@pytest.mark.parametrize("before_ready", [False, True])
def test_startup_compensation_refuses_replacement_program(
    session: Session, monkeypatch: pytest.MonkeyPatch, before_ready: bool
) -> None:
    """Replace the program after launch but before factory readiness returns."""
    verify = program._Program._generation_alive
    owners: list[program._Program] = []
    until = program._Client.until
    original = subprocess.TimeoutExpired("launch readiness", 0)

    def replaced(job: program._Program, *args: t.Any) -> None:
        if not owners:
            owners.append(job)
            session.cmd(
                "respawn-pane",
                "-k",
                "-t",
                job.pane_id,
                sys.executable,
                "-c",
                "import os; os.read(0,1)",
            )
        verify(job, *args)

    def lose_readiness(client: program._Client, *args: t.Any) -> None:
        until(client, *args)
        if "-C" in client.command and any(
            "respawn-pane" in arg for arg in client.command
        ):
            pane = session.windows[-1].active_pane
            assert pane is not None
            session.cmd(
                "respawn-pane",
                "-k",
                "-t",
                pane.pane_id,
                sys.executable,
                "-c",
                "import os; os.read(0,1)",
            )
            raise original

    with monkeypatch.context() as patch:
        if before_ready:
            patch.setattr(program._Client, "until", lose_readiness)
        else:
            patch.setattr(program._Program, "_generation_alive", replaced)
        with pytest.raises(exc.LibTmuxException) as caught:
            session.run_program([sys.executable, "-c", "import os; os.read(0,1)"])
    failure = t.cast("program._FailureEvidence", caught.value)
    assert failure.cleanup_errors
    if before_ready:
        assert caught.value.__cause__ is original
        assert failure.owner._launched is False
        assert failure.owner._launch_submitted is True
    assert session.cmd(
        "display-message", "-p", "-t", failure.owner.pane_id, "#{pane_dead}"
    ).stdout == ["0"]


@requires_events
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_selector_registration_failure_reaps_started_client(
    session: Session, monkeypatch: pytest.MonkeyPatch, cleanup_fails: bool
) -> None:
    """A failed transport constructor must reap the Popen it already started."""
    import selectors

    job = session.run_program([sys.executable, "-c", "import os; os.read(0,1)"])
    original = OSError("selector registration failed")
    cleanup = OSError("constructor cleanup failed")
    close = program._Client.close

    def failed_close(client: program._Client) -> None:
        close(client)
        raise cleanup

    constructor = subprocess.Popen
    selector = selectors.DefaultSelector
    processes = []

    def recorded_process(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[bytes]:
        process = constructor(*args, **kwargs)
        processes.append(process)
        return process

    def broken_selector() -> selectors.BaseSelector:
        selected = selector()

        def fail(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
            raise original

        selected.register = fail  # type: ignore[method-assign]
        return selected

    try:
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "Popen", recorded_process)
            patch.setattr(selectors, "DefaultSelector", broken_selector)
            if cleanup_fails:
                patch.setattr(program._Client, "close", failed_close)
            with pytest.raises(exc.LibTmuxException) as caught:
                job.collect()
        assert caught.value.__cause__ is original
        assert t.cast("program._FailureEvidence", caught.value).cleanup_errors == (
            (cleanup,) if cleanup_fails else ()
        )
        assert processes and all(process.poll() is not None for process in processes)
        assert all(
            pipe.closed
            for process in processes
            for pipe in (process.stdin, process.stdout, process.stderr)
            if pipe is not None
        )
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=0.5)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
        job.terminate()
        job.cleanup()


@requires_events
def test_cancel_before_submission_preserves_intervening_program(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A foreign program can take the initially empty pane before our launch."""
    cancel = threading.Event()
    until = program._Client.until

    def replace_empty_pane(client: program._Client, *args: t.Any) -> None:
        until(client, *args)
        if "-C" in client.command:
            pane = session.windows[-1].active_pane
            assert pane is not None
            session.cmd(
                "respawn-pane",
                "-t",
                pane.pane_id,
                sys.executable,
                "-c",
                "import os; os.read(0,1)",
            )
            cancel.set()

    with monkeypatch.context() as patch:
        patch.setattr(program._Client, "until", replace_empty_pane)
        with pytest.raises(concurrent.futures.CancelledError) as caught:
            session.run_program(
                [sys.executable, "-c", "raise SystemExit(7)"], cancel_event=cancel
            )
    failure = t.cast("program._FailureEvidence", caught.value)
    assert failure.cleanup_errors
    assert session.cmd(
        "display-message", "-p", "-t", failure.owner.pane_id, "#{pane_dead}"
    ).stdout == ["0"]


@requires_events
def test_capture_transport_admission_keeps_exit_evidence(session: Session) -> None:
    """Bound native pipe collection before a large decoded capture can accumulate."""
    job = session.run_program(
        [sys.executable, "-c", "print('A' * 200000); raise SystemExit(7)"]
    )
    try:
        result = job.wait(timeout=1)
        with pytest.raises(
            exc.LibTmuxException, match="transport byte limit"
        ) as caught:
            job.collect(max_text_codepoints=1)
        evidence = t.cast("program._FailureEvidence", caught.value)
        assert evidence.last_observation is result
        assert evidence.last_capture is None
        assert session.server.is_alive()
    finally:
        job.cleanup()


@requires_events
def test_standalone_preserves_operation_and_cleanup_errors(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The published example must not replace a body failure with cleanup failure."""
    import runpy

    script = pathlib.Path(__file__).parents[1] / "examples" / "owned_program.py"
    main = runpy.run_path(str(script))["main"]
    original = OSError("example collection failed")
    cleanup = OSError("example termination cleanup failed")
    terminate = program._Program.terminate

    def failed_collect(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise original

    def failed_terminate(job: program._Program, **kwargs: t.Any) -> t.NoReturn:
        terminate(job, **kwargs)
        raise cleanup

    with monkeypatch.context() as patch:
        patch.setattr(program._Program, "collect", failed_collect)
        patch.setattr(program._Program, "terminate", failed_terminate)
        with pytest.raises(OSError) as caught:
            main()
    assert caught.value is original
    assert caught.value.cleanup_errors == (cleanup,)  # type: ignore[attr-defined]
    assert session.server.is_alive()


@requires_events
@pytest.mark.parametrize("loss", ["renamed", "server-removed", "respawned"])
def test_cleanup_reaps_observers_after_ownership_loss(
    session: Session, monkeypatch: pytest.MonkeyPatch, loss: str
) -> None:
    """Terminal identity failure reaps clients and retains paired cleanup errors."""
    job = session.run_program([sys.executable, "-c", "import os; os.read(0,1)"])
    cleanup_error = OSError("ownership-loss observer cleanup failed")
    close = program._Client.close

    def fail_close(client: program._Client) -> None:
        close(client)
        if client is job._generation:
            raise cleanup_error

    try:
        if loss == "renamed":
            session.cmd("rename-window", "-t", job.pane_id, "foreign")
        elif loss == "server-removed":
            session.server.kill()
        else:
            session.cmd(
                "respawn-pane",
                "-k",
                "-t",
                job.pane_id,
                sys.executable,
                "-c",
                "import os; os.read(0,1)",
            )
        with monkeypatch.context() as patch:
            if loss == "renamed":
                patch.setattr(program._Client, "close", fail_close)
            with pytest.raises(exc.LibTmuxException) as caught:
                job.cleanup(timeout=1)
        evidence = t.cast("program._FailureEvidence", caught.value)
        assert evidence.operation_error is caught.value.__cause__
        assert evidence.cleanup_errors == (
            (cleanup_error,) if loss == "renamed" else ()
        )
        for client in (job._exit, job._generation):
            assert client is not None
            assert client.closed and client.process.poll() is not None
            assert all(
                pipe.closed
                for pipe in (
                    client.process.stdin,
                    client.process.stdout,
                    client.process.stderr,
                )
                if pipe is not None
            )
        if loss != "server-removed":
            assert session.cmd(
                "display-message", "-p", "-t", job.pane_id, "#{pane_dead}"
            ).stdout == ["0"]
            assert session.server.is_alive()
    finally:
        job._close_observers()


@requires_events
def test_capture_preserves_guard_token_text(session: Session) -> None:
    """Rendered text equal to transport guard tokens remains ordinary text."""
    tokens = ("LIBTMUX_PROGRAM_REFUSED", "LIBTMUX_PROGRAM_ADMITTED")
    job = session.run_program(
        [sys.executable, "-c", "import sys; print(*sys.argv[1:], sep='\\n')", *tokens]
    )
    try:
        assert job.wait(timeout=1).exit_status == 0
        for row, token in enumerate(tokens):
            assert job.collect(start=row, end=row).lines == (token,)
    finally:
        job.cleanup()
