"""Integration tests for the persistent ``tmux -C`` control-mode engine.

These tests need a real ``tmux`` binary; they exercise the full
spawn → command → response → close cycle. Heavier engine + lifecycle
behaviour (``weakref.finalize`` cleanup, abrupt-kill recovery) lands
in step 4.
"""

from __future__ import annotations

import gc
import os
import threading
import typing as t
import uuid
import warnings

import pytest

from libtmux import pytest_plugin
from libtmux.engines.base import CommandRequest, CommandResult
from libtmux.engines.control_mode.base import (
    ControlModeEngine,
    TmuxControlModeError,
    _ParsedRequest,
)

if t.TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def control_engine() -> Iterator[tuple[ControlModeEngine, str]]:
    """Yield a ControlModeEngine + a unique socket name; reap on teardown.

    The engine is *not* pre-bound to the socket — each test passes the
    flag through ``CommandRequest.args`` so the engine takes its
    spawn-time global args from the first ``run`` call. That mirrors
    how :class:`libtmux.Server` drives any engine.
    """
    socket_name = f"libtmux_test_cm_{uuid.uuid4().hex[:10]}"
    engine = ControlModeEngine()
    try:
        yield engine, socket_name
    finally:
        engine.close()
        pytest_plugin._reap_test_server(socket_name)


# ---------------------------------------------------------------- parse --


def test_parse_args_extracts_socket_name() -> None:
    """``-L name`` is taken into ``global_args`` and dropped from the command."""
    parsed = ControlModeEngine._parse_args(("-L", "test", "list-sessions"))
    assert parsed == _ParsedRequest(
        global_args=("-L", "test"),
        command_argv=("list-sessions",),
    )


def test_parse_args_extracts_socket_path_and_config() -> None:
    """``-S`` and ``-f`` flags are also pulled into ``global_args``."""
    parsed = ControlModeEngine._parse_args(
        ("-S", "/tmp/sock", "-f", "/etc/tmux.conf", "kill-server"),
    )
    assert parsed.global_args == ("-S", "/tmp/sock", "-f", "/etc/tmux.conf")
    assert parsed.command_argv == ("kill-server",)


def test_parse_args_handles_attached_short_form() -> None:
    """``-Lsocket`` (no separator) is treated as a client-level flag."""
    parsed = ControlModeEngine._parse_args(("-Ltest", "display-message", "hi"))
    assert parsed.global_args == ("-Ltest",)
    assert parsed.command_argv == ("display-message", "hi")


def test_parse_args_keeps_unrecognised_flags_in_command() -> None:
    """Flags that aren't client-level (e.g. ``-t target``) stay in command."""
    parsed = ControlModeEngine._parse_args(
        ("-L", "test", "list-windows", "-t", "main"),
    )
    assert parsed.global_args == ("-L", "test")
    assert parsed.command_argv == ("list-windows", "-t", "main")


# ----------------------------------------------------------------- run --


def test_run_display_message(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """A simple round-trip command returns its stdout via the persistent client."""
    engine, socket_name = control_engine
    result = engine.run(
        CommandRequest.from_args("-L", socket_name, "display-message", "-p", "hello"),
    )
    assert result.returncode == 0
    assert result.stdout == ["hello"]
    assert result.stderr == []


def test_run_reuses_subprocess_across_calls(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """Subsequent commands flow through the same already-spawned client."""
    engine, socket_name = control_engine
    engine.run(
        CommandRequest.from_args(
            "-L",
            socket_name,
            "new-session",
            "-d",
            "-s",
            "first",
        ),
    )
    first_pid = engine._state.proc.pid if engine._state else None
    assert first_pid is not None

    result = engine.run(
        CommandRequest.from_args("-L", socket_name, "list-sessions", "-F", "#S"),
    )
    second_pid = engine._state.proc.pid if engine._state else None
    assert second_pid == first_pid, "engine should not respawn between calls"
    assert "first" in result.stdout


def test_run_error_command_populates_stderr(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """``%error`` blocks decode into ``stderr`` and ``returncode == 1``."""
    engine, socket_name = control_engine
    # Make sure the server exists first, otherwise the typo would just spawn
    # a new server and parse-error inside it — the test outcome is identical
    # but the fixture path is clearer.
    engine.run(
        CommandRequest.from_args(
            "-L",
            socket_name,
            "new-session",
            "-d",
            "-s",
            "alive",
        ),
    )
    result = engine.run(
        CommandRequest.from_args("-L", socket_name, "no-such-command"),
    )
    assert result.returncode == 1
    assert result.stdout == []
    assert result.stderr  # tmux echoes a parse error message


def test_run_serialises_concurrent_calls(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """Two threads issuing commands in parallel both succeed in lockstep.

    The internal ``_lock`` serialises the in-flight ``%begin``/``%end``
    correlation so both threads receive the right Block. This test
    catches a regression where the lock is dropped or re-entered.
    """
    engine, socket_name = control_engine
    engine.run(
        CommandRequest.from_args(
            "-L",
            socket_name,
            "new-session",
            "-d",
            "-s",
            "t1",
        ),
    )

    results: list[list[str]] = []
    errors: list[BaseException] = []

    def call(label: str) -> None:
        try:
            r = engine.run(
                CommandRequest.from_args(
                    "-L",
                    socket_name,
                    "display-message",
                    "-p",
                    label,
                ),
            )
            results.append(r.stdout)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=call, args=(f"thread-{i}",)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert sorted(["".join(r) for r in results]) == [f"thread-{i}" for i in range(8)]


def test_run_global_args_must_match_first_spawn(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """A second call with different socket flags is rejected, not silently rerouted."""
    engine, socket_name = control_engine
    engine.run(
        CommandRequest.from_args("-L", socket_name, "display-message", "-p", "ok"),
    )
    with pytest.raises(TmuxControlModeError, match="bound to global args"):
        engine.run(
            CommandRequest.from_args(
                "-L",
                "different-socket",
                "display-message",
                "-p",
                "nope",
            ),
        )


def test_run_after_close_respawns(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """``close()`` then ``run()`` spawns a fresh subprocess."""
    engine, socket_name = control_engine
    engine.run(
        CommandRequest.from_args("-L", socket_name, "display-message", "-p", "first"),
    )
    first_pid = engine._state.proc.pid if engine._state else None
    engine.close()
    assert engine._state is None

    result = engine.run(
        CommandRequest.from_args("-L", socket_name, "display-message", "-p", "second"),
    )
    second_pid = engine._state.proc.pid if engine._state else None
    assert second_pid is not None
    assert second_pid != first_pid
    assert result.stdout == ["second"]


def test_run_recovers_from_dead_subprocess(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """A SIGKILL'd subprocess marks the engine broken on next call."""
    engine, socket_name = control_engine
    engine.run(
        CommandRequest.from_args("-L", socket_name, "display-message", "-p", "go"),
    )
    state = engine._state
    assert state is not None
    proc = state.proc

    os.kill(proc.pid, 9)  # SIGKILL
    proc.wait()

    with pytest.raises(TmuxControlModeError):
        engine.run(
            CommandRequest.from_args(
                "-L",
                socket_name,
                "display-message",
                "-p",
                "after-kill",
            ),
        )


# --------------------------------------------------------- run_batch --


def test_run_batch_empty_returns_empty_without_spawning(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """``run_batch([])`` is a no-op; it must not spawn the subprocess."""
    engine, _ = control_engine
    assert engine.run_batch([]) == []
    assert engine._state is None


def test_run_batch_single_request_matches_run(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """A one-element batch yields the same shape as a single ``run()``."""
    engine, socket_name = control_engine
    request = CommandRequest.from_args(
        "-L",
        socket_name,
        "display-message",
        "-p",
        "solo",
    )
    [result] = engine.run_batch([request])
    assert result.returncode == 0
    assert result.stdout == ["solo"]


def test_run_batch_preserves_send_order(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """Five commands batched return five results in send order.

    Verifies the FIFO contract from tmux's command queue
    (``cmd-queue.c:315``) — the i-th block is the i-th request's
    response.
    """
    engine, socket_name = control_engine
    requests = [
        CommandRequest.from_args(
            "-L",
            socket_name,
            "display-message",
            "-p",
            f"line-{i}",
        )
        for i in range(5)
    ]
    results = engine.run_batch(requests)
    assert len(results) == 5
    for index, result in enumerate(results):
        assert result.returncode == 0, result.stderr
        assert result.stdout == [f"line-{index}"], result.stdout


def test_run_batch_writes_in_one_stdin_write(
    control_engine: tuple[ControlModeEngine, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pipelined path issues exactly one ``stdin.write`` for N commands.

    Catches a regression that would slip back to per-command writes
    and lose the lock + flush amortisation that motivated this work.
    """
    engine, socket_name = control_engine
    # Prime the engine so ``_state`` is populated before we patch.
    engine.run(
        CommandRequest.from_args("-L", socket_name, "display-message", "-p", "x"),
    )
    state = engine._state
    assert state is not None
    assert state.proc.stdin is not None

    write_calls: list[bytes] = []
    real_write = state.proc.stdin.write

    def counting_write(data: bytes) -> int:
        write_calls.append(bytes(data))
        return real_write(data)

    monkeypatch.setattr(state.proc.stdin, "write", counting_write)

    requests = [
        CommandRequest.from_args(
            "-L",
            socket_name,
            "display-message",
            "-p",
            f"batch-{i}",
        )
        for i in range(4)
    ]
    engine.run_batch(requests)

    assert len(write_calls) == 1, (
        f"expected 1 stdin.write for batch, got {len(write_calls)}: "
        f"{[w[:40] for w in write_calls]}"
    )
    assert write_calls[0].count(b"\n") == 4


def test_run_batch_mid_batch_error_returns_per_result_returncode(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """A bad command in the middle of a batch yields a returncode=1 result.

    The batch as a whole completes; only that one result has
    ``returncode=1`` and a populated ``stderr``. Mirrors single-call
    ``run()`` semantics.
    """
    engine, socket_name = control_engine
    # Provoke a server first so the second request lands in a real session.
    engine.run(
        CommandRequest.from_args(
            "-L",
            socket_name,
            "new-session",
            "-d",
            "-s",
            "alive",
        ),
    )
    requests = [
        CommandRequest.from_args(
            "-L",
            socket_name,
            "display-message",
            "-p",
            "before",
        ),
        CommandRequest.from_args("-L", socket_name, "no-such-command"),
        CommandRequest.from_args(
            "-L",
            socket_name,
            "display-message",
            "-p",
            "after",
        ),
    ]
    before, bad, after = engine.run_batch(requests)
    assert before.returncode == 0
    assert before.stdout == ["before"]
    assert bad.returncode == 1
    assert bad.stderr  # tmux echoes a parse error
    assert after.returncode == 0
    assert after.stdout == ["after"]


def test_run_batch_rejects_mismatched_global_args(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """A batch mixing two different ``-L`` sockets raises before any wire I/O."""
    engine, socket_name = control_engine
    engine.run(
        CommandRequest.from_args("-L", socket_name, "display-message", "-p", "go"),
    )
    requests = [
        CommandRequest.from_args(
            "-L",
            socket_name,
            "display-message",
            "-p",
            "ok",
        ),
        CommandRequest.from_args(
            "-L",
            "different-socket",
            "display-message",
            "-p",
            "nope",
        ),
    ]
    with pytest.raises(TmuxControlModeError, match="uniform global args"):
        engine.run_batch(requests)


def test_run_batch_rejects_empty_command_argv(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """A batch member without a tmux subcommand raises before spawning."""
    engine, socket_name = control_engine
    requests = [
        CommandRequest.from_args(
            "-L",
            socket_name,
            "display-message",
            "-p",
            "ok",
        ),
        CommandRequest.from_args("-L", socket_name),  # no subcommand
    ]
    from libtmux import exc as libtmux_exc

    with pytest.raises(libtmux_exc.LibTmuxException, match="run_batch requires"):
        engine.run_batch(requests)


def test_run_batch_serialises_with_concurrent_run(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """A run_batch holds the engine lock; concurrent run() blocks until done.

    Two threads: thread A issues a 5-command batch, thread B issues
    a single ``run()``. Both must complete with no interleaved
    %begin/%end correlation errors.
    """
    engine, socket_name = control_engine
    engine.run(
        CommandRequest.from_args(
            "-L",
            socket_name,
            "new-session",
            "-d",
            "-s",
            "racey",
        ),
    )

    batch_results: list[CommandResult] = []
    single_results: list[CommandResult] = []
    errors: list[BaseException] = []

    def run_batch_thread() -> None:
        try:
            batch_results.extend(
                engine.run_batch(
                    [
                        CommandRequest.from_args(
                            "-L",
                            socket_name,
                            "display-message",
                            "-p",
                            f"b{i}",
                        )
                        for i in range(5)
                    ],
                ),
            )
        except BaseException as error:
            errors.append(error)

    def run_single_thread() -> None:
        try:
            single_results.append(
                engine.run(
                    CommandRequest.from_args(
                        "-L",
                        socket_name,
                        "display-message",
                        "-p",
                        "single",
                    ),
                ),
            )
        except BaseException as error:
            errors.append(error)

    threads = [
        threading.Thread(target=run_batch_thread),
        threading.Thread(target=run_single_thread),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(batch_results) == 5
    assert [r.stdout for r in batch_results] == [[f"b{i}"] for i in range(5)]
    assert len(single_results) == 1
    assert single_results[0].stdout == ["single"]


# --------------------------------------------------------------- close --


def test_close_is_idempotent(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """``close()`` may be called repeatedly without raising or hanging."""
    engine, socket_name = control_engine
    engine.run(
        CommandRequest.from_args("-L", socket_name, "display-message", "-p", "x"),
    )
    engine.close()
    engine.close()
    engine.close()
    assert engine._state is None


def test_close_uses_graceful_empty_line_path(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """``close()`` exits via the empty-line CLIENT_EXIT path on the happy case.

    A well-behaved tmux exits cleanly when its control client sends an
    empty line on stdin (``control.c:551``). We verify by patching
    ``terminate`` and ``kill`` to raise — they should never be called
    when graceful shutdown succeeds, which is the steady-state.
    """
    engine, socket_name = control_engine
    engine.run(
        CommandRequest.from_args("-L", socket_name, "display-message", "-p", "go"),
    )
    state = engine._state
    assert state is not None
    proc = state.proc

    def _no_signal_call(*_args: object, **_kwargs: object) -> None:
        msg = "graceful close should not need terminate/kill"
        raise AssertionError(msg)

    proc.terminate = _no_signal_call  # type: ignore[method-assign]
    proc.kill = _no_signal_call  # type: ignore[method-assign]

    engine.close()

    assert engine._state is None
    assert proc.poll() is not None  # tmux exited under its own steam


def test_close_releases_subprocess_on_gc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dropping the engine reference reaps the subprocess via weakref.finalize.

    The finalizer runs at GC time and tears down the same way explicit
    ``close()`` does, so leaked engines do not leave zombie tmux
    processes behind. We assert no ``ResourceWarning`` is raised — that
    is the canary for a leaked ``Popen`` in CPython.
    """
    monkeypatch.setattr(warnings, "filters", warnings.filters[:])
    warnings.simplefilter("error", ResourceWarning)

    socket_name = f"libtmux_test_cm_gc_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    try:
        engine.run(
            CommandRequest.from_args(
                "-L",
                socket_name,
                "display-message",
                "-p",
                "leak-check",
            ),
        )
        state = engine._state
        assert state is not None
        proc = state.proc

        # Drop the only reference and force a GC pass; the finalizer
        # should reap the subprocess synchronously.
        del state
        del engine
        gc.collect()

        # Give the cleanup a brief grace period; reader join + selector
        # close happen on the GC thread but the subprocess wait is
        # bounded by _GRACEFUL_EXIT_TIMEOUT.
        proc.wait(timeout=5)
        assert proc.returncode is not None
    finally:
        pytest_plugin._reap_test_server(socket_name)


def test_close_after_subprocess_already_dead_is_safe(
    control_engine: tuple[ControlModeEngine, str],
) -> None:
    """``close()`` works even if the tmux subprocess already exited.

    Common when the user kills the tmux server with ``kill-server``:
    by the time ``close()`` runs, the subprocess is gone, the reader
    thread has marked the engine broken, and the cleanup must not
    re-raise.
    """
    engine, socket_name = control_engine
    engine.run(
        CommandRequest.from_args("-L", socket_name, "display-message", "-p", "go"),
    )
    state = engine._state
    assert state is not None

    os.kill(state.proc.pid, 9)
    state.proc.wait()
    # Give the reader thread a moment to see EOF.
    threading.Event().wait(0.3)

    engine.close()
    assert engine._state is None
