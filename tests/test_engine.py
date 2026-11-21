"""Tests for the libtmux.engine raw-byte transport seam."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
import warnings
from typing import TYPE_CHECKING

import pytest

from libtmux import exc
from libtmux._internal.instrumentation import CountingSink, instrument
from libtmux._internal.invocation import (
    MAX_PACKED_ARGV_BYTES,
    MAX_PACKED_ARGV_COUNT,
    flatten_commands,
)
from libtmux.common import has_gte_version
from libtmux.engine import (
    ControlModeEngine,
    DaemonGuard,
    ExecEngine,
    SubprocessEngine,
    TmuxEngine,
    TmuxRequest,
    TmuxResult,
)
from libtmux.neo import get_output_format
from libtmux.server import Server
from libtmux.test import FakeEngine, RecordingEngine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.session import Session


def test_engine_public_surface_and_zero_eager_imports() -> None:
    """libtmux.engine exports its exact surface and import libtmux stays lean."""
    import libtmux
    import libtmux.engine as engine_mod

    expected = {
        "AsyncTmuxEngine",
        "ControlModeEngine",
        "DaemonGuard",
        "ExecEngine",
        "SubprocessEngine",
        "TmuxEngine",
        "TmuxRequest",
        "TmuxResult",
    }
    assert set(engine_mod.__all__) == expected

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, libtmux; "
                "assert 'asyncio' not in sys.modules; "
                "assert 'libtmux.test' not in sys.modules"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0
    assert hasattr(libtmux, "Server")


def test_fake_engine_drives_server_without_tmux_on_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FakeEngine satisfies TmuxEngine and drives Server with PATH empty.

    Uses FakeEngine directly to prove offline tests require no installed tmux
    binary.
    """
    monkeypatch.setenv("PATH", "")
    fields, _ = get_output_format("list-sessions", "3.2a")
    row = [""] * len(fields)
    row[fields.index("session_id")] = "$1"
    row[fields.index("session_name")] = "offline"
    line = "\u241e".join(row) + "\u241e\n"

    fake = FakeEngine()
    fake.enqueue(stdout=b"hello\n")
    fake.enqueue(stdout=line.encode("utf-8"))

    srv = Server(socket_name="offline_sock", engine=fake)
    assert isinstance(fake, TmuxEngine)
    assert srv.cmd("display-message", "-p", "hello").stdout == ["hello"]

    sessions = srv.sessions
    assert len(sessions) == 1
    assert sessions[0].session_id == "$1"
    assert sessions[0].session_name == "offline"
    assert len(fake.requests) == 2


def test_recording_and_instrumented_engines_delegate_batch() -> None:
    """Wrappers forward execute_batch to inner.execute_batch instead of looping.

    Uses an in-memory batch-tracking double to assert exact call counts on
    execute versus execute_batch.
    """

    class BatchDouble:
        endpoint = None

        def __init__(self) -> None:
            self.single_calls = 0
            self.batch_calls = 0

        def execute(self, request: TmuxRequest) -> TmuxResult:
            self.single_calls += 1
            return TmuxResult(argv=request.commands[0], stdout=b"single\n")

        def execute_batch(
            self,
            requests: Sequence[TmuxRequest],
        ) -> list[TmuxResult]:
            self.batch_calls += 1
            return [
                TmuxResult(argv=req.commands[0], stdout=b"batched\n")
                for req in requests
            ]

    inner = BatchDouble()
    sink = CountingSink()
    recorded = RecordingEngine(inner)
    wrapped = instrument(recorded, sink)

    reqs = [
        TmuxRequest.from_args("display-message", "-p", "1"),
        TmuxRequest(
            commands=(
                ("set-option", "-g", "@k", "v"),
                ("show-options", "-g", "@k"),
            ),
        ),
    ]
    results = wrapped.execute_batch(reqs)

    assert [r.stdout for r in results] == [b"batched\n", b"batched\n"]
    assert inner.batch_calls == 1
    assert inner.single_calls == 0
    assert len(recorded.batches) == 1
    assert sink.requests == 2
    assert sink.tmux_commands == 3
    assert sink.inlined == 1


def test_invocation_enforces_imsg_byte_and_argv_limits() -> None:
    """flatten_commands rejects oversized payloads and argument vectors early."""
    near_limit = "x" * (MAX_PACKED_ARGV_BYTES - len("set-option") - 4)
    ok_tokens = flatten_commands((("set-option", near_limit),))
    assert ok_tokens[0] == "set-option"

    with pytest.raises(exc.TmuxCommandTooLong, match="command too long"):
        flatten_commands((("set-option", "x" * MAX_PACKED_ARGV_BYTES),))

    many_args = tuple(str(i) for i in range(MAX_PACKED_ARGV_COUNT + 1))
    with pytest.raises(exc.TmuxCommandTooLong, match="command too long"):
        flatten_commands((many_args,))


def test_trailing_semicolon_token_stays_data_against_live_tmux(
    session: Session,
) -> None:
    """Data arguments ending in ';' are escaped so tmux never splits commands."""
    srv = session.server
    srv.cmd("set-option", "-g", "@semi_check", "alpha;")
    assert srv.cmd("show-options", "-g", "-v", "@semi_check").stdout == ["alpha;"]

    engine = SubprocessEngine.for_server(srv)
    grouped = TmuxRequest(
        commands=(
            ("set-option", "-g", "@semi_group", "beta;"),
            ("show-options", "-g", "-v", "@semi_group"),
        ),
    )
    res = engine.execute(grouped)
    assert res.returncode == 0
    assert res.stdout == b"beta;\n"


def test_raw_bytes_stdin_and_stdout_64kib_round_trip(session: Session) -> None:
    """Non-UTF-8 and NUL-free binary payloads survive stdin/stdout unmodified."""
    srv = session.server
    # Include invalid UTF-8 sequences (0x80..0xff) and trailing newlines;
    # exclude 0x00 only if load-buffer handles all bytes (tmux buffers store
    # arbitrary byte lengths including NUL).
    payload = (bytes(range(256)) * 256) + b"\n\n"
    assert len(payload) == 65_538

    load_proc = srv.cmd("load-buffer", "-b", "raw_64k", "-", stdin=payload)
    assert load_proc.returncode == 0

    save_proc = srv.cmd("save-buffer", "-b", "raw_64k", "-")
    assert save_proc.returncode == 0
    assert save_proc.raw_stdout == payload


def test_subprocess_engine_timeout_reaps_blocking_wait_for(
    session: Session,
) -> None:
    """TmuxCommandTimeout kills and reaps a blocked client process."""
    engine = SubprocessEngine.for_server(session.server)
    channel = f"timeout-{uuid.uuid4().hex[:8]}"

    with pytest.raises(exc.TmuxCommandTimeout):
        engine.execute(TmuxRequest.from_args("wait-for", channel, timeout=0.15))


def test_spawn_client_supports_concurrent_wait_for_signaling(
    session: Session,
) -> None:
    """spawn_client holds a blocking wait-for client open until signaled."""
    import time

    engine = SubprocessEngine.for_server(session.server)
    channel = f"signal-{uuid.uuid4().hex[:8]}"

    waiter = engine.spawn_client(TmuxRequest.from_args("wait-for", channel))
    try:
        for _ in range(50):
            session.server.cmd("wait-for", "-S", channel)
            if waiter.poll() is not None:
                break
            time.sleep(0.02)
        res = waiter.wait(timeout=2.0)
        assert res.returncode == 0
    finally:
        waiter.kill()


def test_daemon_guard_fences_stale_server_generation(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """DaemonGuard executes on matching generation and aborts on a restarted daemon."""
    sock = tmp_path / "guard.sock"  # type: ignore[operator]
    srv = Server(socket_path=str(sock), config_file=os.devnull)
    try:
        srv.new_session(session_name="gen1")
        caps1 = srv.capabilities()
        guard1 = DaemonGuard(pid=caps1.pid, start_time=caps1.start_time)

        ok = srv.cmd(
            "set-option",
            "-g",
            "@gen_marker",
            "v1",
            daemon_guard=guard1,
        )
        assert ok.returncode == 0
        assert srv.cmd("show-options", "-g", "-v", "@gen_marker").stdout == ["v1"]

        srv.kill(wait=True)
        srv.new_session(session_name="gen2")
        caps2 = srv.capabilities(refresh=True)
        assert caps2.pid != caps1.pid or caps2.start_time != caps1.start_time

        with pytest.raises(exc.TmuxServerRestarted):
            srv.cmd(
                "set-option",
                "-g",
                "@gen_marker",
                "stale_write",
                daemon_guard=guard1,
            )

        assert srv._cached_capabilities is None
        check = srv.cmd("show-options", "-g", "-q", "-v", "@gen_marker")
        assert check.stdout == []
    finally:
        if srv.is_alive():
            srv.kill(wait=True)


def test_exec_engine_wraps_prefix_and_scopes_server_equality(
    session: Session,
) -> None:
    """ExecEngine prepends wrapper argv and keeps distinct endpoints unequal."""
    sock_name = session.server.socket_name
    assert sock_name is not None

    exec_engine = ExecEngine(("/usr/bin/env", "LIBTMUX_EXEC_WRAP=1"))
    wrapped_srv = Server(socket_name=sock_name, engine=exec_engine)
    out = wrapped_srv.cmd("display-message", "-p", "via-exec")
    assert out.stdout == ["via-exec"]
    assert out.cmd[:2] == ["/usr/bin/env", "LIBTMUX_EXEC_WRAP=1"]

    srv_a = Server(socket_name="shared", engine=ExecEngine(("env", "HOST=a")))
    srv_b = Server(socket_name="shared", engine=ExecEngine(("env", "HOST=b")))
    assert srv_a != srv_b


def test_server_engine_configuration_mismatch_and_adoption(
    session: Session,
) -> None:
    """Unbound engines adopt Server socket flags; conflicting engines raise."""
    sock_name = session.server.socket_name
    assert sock_name is not None

    adopted_srv = Server(socket_name=sock_name, engine=SubprocessEngine())
    assert adopted_srv.is_alive()

    conflicting = SubprocessEngine.of(server_args=("-L", f"{sock_name}_other"))
    with pytest.raises(exc.EngineConfigurationMismatch):
        Server(socket_name=sock_name, engine=conflicting)


def test_async_engine_mismatch_closes_coroutine_without_warning() -> None:
    """Passing an async engine to synchronous Server raises cleanly with zero warnings.

    Uses a minimal async double to exercise the synchronous mismatch guard.
    """

    class AsyncDouble:
        endpoint = None

        async def execute(self, request: TmuxRequest) -> TmuxResult:
            return TmuxResult(argv=request.commands[0])

    srv = Server(socket_name="async_guard", engine=AsyncDouble())  # type: ignore[arg-type]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(exc.AsyncEngineMismatch):
            srv.cmd("list-sessions")
        with pytest.raises(exc.AsyncEngineMismatch):
            _ = srv.sessions

    runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert runtime_warnings == []


@pytest.mark.skipif(
    not has_gte_version("3.7"),
    reason="ControlModeEngine requires tmux >= 3.7",
)
def test_control_mode_engine_ignores_hook_blocks_and_literal_guards(
    session: Session,
) -> None:
    """ControlModeEngine filters flags==0 hook frames and nested %begin text."""
    srv = session.server
    srv.cmd(
        "set-hook",
        "-g",
        "after-set-option",
        "display-message -p hook-fired-noise",
    )
    try:
        with ControlModeEngine.for_server(srv) as ctl_engine:
            literal = ctl_engine.execute(
                TmuxRequest.from_args("display-message", "-p", "-l", "%begin 1 2 1"),
            )
            assert literal.stdout == b"%begin 1 2 1\n"

            batch = ctl_engine.execute_batch(
                [
                    TmuxRequest.from_args("set-option", "-g", "@ctl_k", "42"),
                    TmuxRequest.from_args(
                        "show-options",
                        "-g",
                        "-v",
                        "@ctl_k",
                    ),
                    TmuxRequest.from_args("display-message", "-p", "tail-ok"),
                ]
            )
            assert batch[0].returncode == 0
            assert batch[1].stdout == b"42\n"
            assert batch[2].stdout == b"tail-ok\n"
    finally:
        srv.cmd("set-hook", "-gu", "after-set-option")


def test_fetch_objs_and_new_session_survive_c_locale(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FORMAT_SEPARATOR survives LC_ALL=C on the tmux daemon and client."""
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    sock = tmp_path / "clocale.sock"  # type: ignore[operator]
    srv = Server(socket_path=str(sock), config_file=os.devnull)
    try:
        created = srv.new_session(session_name="c_locale_sess")
        assert created.session_name == "c_locale_sess"
        listed = srv.sessions
        assert [s.session_name for s in listed] == ["c_locale_sess"]
    finally:
        if srv.is_alive():
            srv.kill(wait=True)


def test_server_kill_wait_polls_until_daemon_exits(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Server.kill(wait=True) waits until the tmux server PID is gone."""
    sock = tmp_path / "killwait.sock"  # type: ignore[operator]
    srv = Server(socket_path=str(sock), config_file=os.devnull)
    srv.new_session(session_name="doomed")
    pid = srv.capabilities().pid

    srv.kill(wait=True)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
