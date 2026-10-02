"""Tests for :class:`libtmux.engines.control.sync.ControlModeEngine`."""

from __future__ import annotations

import contextlib
import os
import pathlib
import signal
import stat
import subprocess
import sys
import textwrap
import threading
import time
import typing as t

import pytest

from libtmux import exc
from libtmux.engines import (
    CommandRequest,
    CommandSeparator,
    ControlModeEngine,
    SubprocessEngine,
)
from libtmux.server import Server

if t.TYPE_CHECKING:
    from collections.abc import Iterator

    from libtmux.session import Session

WATCHDOG_SECONDS = 20


@pytest.fixture(autouse=True)
def _watchdog() -> Iterator[None]:
    """Fail a test that would otherwise hang on a lost reply."""

    def expire(signum: int, frame: object) -> t.NoReturn:
        msg = f"no progress within {WATCHDOG_SECONDS} s"
        raise TimeoutError(msg)

    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(WATCHDOG_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def req(*args: str) -> CommandRequest:
    """Build a request."""
    return CommandRequest.from_args(*args)


def client_count(server: Server) -> int:
    """Return how many clients are attached to *server*."""
    return len(server.cmd("list-clients", "-F", "#{client_pid}").stdout)


def pid_alive(pid: int) -> bool:
    """Return whether *pid* still exists (a reaped child does not)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def engine(session: Session) -> Iterator[ControlModeEngine]:
    """Yield a control engine bound to the test server, then close it."""
    control = ControlModeEngine.for_server(session.server)
    try:
        yield control
    finally:
        control.close()


def test_attaches_to_the_existing_session_without_a_phantom(
    session: Session,
    engine: ControlModeEngine,
) -> None:
    """The client joins a session that exists; the server gains none."""
    server = session.server
    before = sorted(s.session_id or "" for s in server.sessions)

    result = engine.run(req("display-message", "-p", "hi"))

    assert result.stdout == ("hi",)
    assert engine.generation == 1
    assert client_count(server) == 1
    assert sorted(s.session_id or "" for s in server.sessions) == before


def test_without_a_session_nothing_is_created(server: Server) -> None:
    """With no session to attach to, requests run in a subprocess."""
    with ControlModeEngine.for_server(server) as engine:
        result = engine.run(req("list-sessions"))

        assert result.returncode != 0
        assert engine.generation == 0
    assert not server.is_alive()


def test_first_session_is_made_by_a_subprocess_then_control_takes_over(
    server: Server,
) -> None:
    """``new-session`` runs in a subprocess; the next command rides control."""
    with ControlModeEngine.for_server(server) as engine:
        made = engine.run(
            req("new-session", "-d", "-s", "boot", "-P", "-F#{session_id}")
        )
        assert made.process is not None  # a subprocess ran it
        assert engine.generation == 0

        result = engine.run(req("display-message", "-p", "ok"))

        assert result.process is None
        assert engine.generation == 1


def test_a_session_that_destroys_when_unattached_is_never_the_target(
    server: Server,
) -> None:
    """The target is chosen from options already off; none are written."""
    doomed = server.new_session("doomed")
    safe = server.new_session("safe")
    server.cmd("set-option", "-t", "safe", "destroy-unattached", "off")
    # A held client keeps `doomed` alive once the option is on.
    holder = subprocess.Popen(
        SubprocessEngine.for_server(server).connection.argv(
            "-C", "attach-session", "-t", doomed.session_id or ""
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().startswith(b"%begin")  # attached
        server.cmd("set-option", "-t", "doomed", "destroy-unattached", "on")
        with ControlModeEngine.for_server(server) as engine:
            engine.run(req("display-message", "-p", "x"))
            pid = engine._proc.pid  # type: ignore[union-attr]
            rows = server.cmd(
                "list-clients", "-F", "#{client_pid} #{client_session}"
            ).stdout

            assert f"{pid} safe" in rows
            shown = server.cmd(
                "show-options", "-t", "doomed", "-v", "destroy-unattached"
            )
            assert shown.stdout == ["on"]  # untouched
    finally:
        assert holder.stdin is not None
        holder.stdin.close()
        holder.wait(timeout=5)
    assert safe.session_id is not None


def test_results_match_the_subprocess_engine(
    session: Session,
    engine: ControlModeEngine,
) -> None:
    """Same requests, same stdout, stderr and return code."""
    reference = SubprocessEngine.for_server(session.server)
    requests = [
        req("display-message", "-p", "#{session_id}"),
        req("list-windows", "-F", "#{window_id}"),
        req("show-options", "-g", "base-index"),
        req("kill-window", "-t", "@9999"),
        req("has-session", "-t", "no-such-session"),
        req("display-message", "-p", "a b it's q\"x"),
        req("display-message", "-p", "too", "many"),
        req("no-such-command"),
        req("display-message", "-p", "multi\nline"),
    ]

    for request in requests:
        over_control = engine.run(request)
        over_fork = reference.run(request)
        assert over_control.cmd == over_fork.cmd
        assert over_control.stdout == over_fork.stdout, request.args
        assert over_control.stderr == over_fork.stderr, request.args
        assert over_control.returncode == over_fork.returncode, request.args


def test_a_command_group_is_one_result_and_stops_at_the_first_error(
    engine: ControlModeEngine,
    session: Session,
) -> None:
    """Replies merge per request; tmux drops the commands after an error."""
    sep = CommandSeparator(";")
    good = engine.run(
        req("display-message", "-p", "one", sep, "display-message", "-p", "two"),
    )
    assert good.stdout == ("one", "two")
    assert good.ok

    aborted = engine.run(
        req("kill-window", "-t", "@9999", sep, "display-message", "-p", "never"),
    )
    assert not aborted.ok
    assert aborted.stdout == ()
    assert aborted.stderr == ("can't find window: @9999",)
    # The reply stream is still aligned for the next request.
    assert engine.run(req("display-message", "-p", "after")).stdout == ("after",)


def test_a_batch_is_pipelined_and_returned_in_order(
    engine: ControlModeEngine,
    session: Session,
) -> None:
    """Replies are attributed to their requests, not to arrival order."""
    requests = [req("display-message", "-p", f"v{index}") for index in range(60)]

    results = engine.run_batch(requests)

    assert [result.stdout for result in results] == [(f"v{i}",) for i in range(60)]


def test_a_batch_larger_than_the_pipe_completes(
    engine: ControlModeEngine,
    session: Session,
) -> None:
    """A megabyte each way crosses the 64 KiB pipe without stalling.

    This guards the decision to write the whole batch before reading: it holds
    only while tmux buffers its replies, so a tmux that stopped doing so would
    hang here.
    """
    blob = "x" * 2000
    requests = [req("display-message", "-p", f"{index}{blob}") for index in range(500)]

    results = engine.run_batch(requests)

    assert [result.stdout[0][:3] for result in results[:3]] == ["0xx", "1xx", "2xx"]
    assert len(results) == 500


def test_a_refused_argument_sends_nothing(
    engine: ControlModeEngine,
    session: Session,
) -> None:
    """Encoding precedes writing: a refused batch runs none of its requests."""
    engine.run(req("display-message", "-p", "warm"))
    bad = CommandRequest(args=("display-message", "-p", "\ud800"))

    with pytest.raises(ValueError, match="surrogate"):
        engine.run_batch([req("set-option", "-g", "@refused", "yes"), bad])

    shown = engine.run(req("show-options", "-gqv", "@refused"))
    assert shown.stdout == ()  # the first request never ran
    assert engine.run(req("display-message", "-p", "next")).stdout == ("next",)


def test_a_hook_command_does_not_steal_a_reply(
    engine: ControlModeEngine,
    session: Session,
) -> None:
    """Tmux writes a block for the hook's own command; no request owns it."""
    session.server.cmd("set-hook", "-g", "after-rename-window", "set -g @hooked yes")

    renamed = engine.run(
        req("rename-window", "-t", session.active_window.window_id or "", "w2")
    )
    shown = engine.run(req("display-message", "-p", "#{window_name}"))

    assert renamed.ok
    assert renamed.stdout == ()
    assert shown.stdout == ("w2",)


def test_commands_that_wait_do_not_block_the_connection(
    session: Session,
    engine: ControlModeEngine,
) -> None:
    """``wait-for`` runs in a subprocess; control commands go on meanwhile."""
    engine.run(req("display-message", "-p", "warm"))
    waiting: list[bool] = []

    def wait() -> None:
        waiting.append(engine.run(req("wait-for", "chan")).ok)

    waiter = threading.Thread(target=wait, daemon=True)
    waiter.start()
    try:
        # With the waiter on the connection this would queue behind it forever.
        answered: list[str] = []

        def ask() -> None:
            answered.append(engine.run(req("display-message", "-p", "free")).stdout[0])

        asker = threading.Thread(target=ask, daemon=True)
        asker.start()
        asker.join(5)
        assert answered == ["free"]
    finally:
        session.server.cmd("wait-for", "-S", "chan")
    waiter.join(5)
    assert waiting == [True]


def test_a_blocking_command_inside_a_batch_keeps_its_place(
    session: Session,
    engine: ControlModeEngine,
) -> None:
    """A routed request splits the pipeline without reordering results."""
    results = engine.run_batch(
        [
            req("display-message", "-p", "a"),
            req("if-shell", "-F", "1", "display-message -p b"),
            req("display-message", "-p", "c"),
        ],
    )

    assert [result.stdout for result in results] == [("a",), ("b",), ("c",)]


def test_pane_output_never_stalls_an_idle_engine(
    session: Session,
    engine: ControlModeEngine,
) -> None:
    """The client asks for no pane output, so a flooding pane is not held up."""
    engine.run(req("display-message", "-p", "warm"))
    server = session.server
    pane = session.new_window(window_shell="sh", attach=False).active_pane
    assert pane is not None
    command = (
        "seq 1 400000 | tr '\\n' x >/dev/null; seq 1 600000; "
        f"tmux -L{server.socket_name} wait-for -S flooded"
    )
    pane.send_keys(command)

    finished = subprocess.run(
        server.engine.command_line(req("wait-for", "flooded")),  # type: ignore[attr-defined]
        timeout=15,
        check=False,
    )

    assert finished.returncode == 0


def test_the_object_api_runs_over_control_mode(server: Server) -> None:
    """``Server(engine=ControlModeEngine())`` drives the classic objects."""
    controlled = Server(
        socket_name=server.socket_name,
        engine=ControlModeEngine(),
    )
    try:
        session = controlled.new_session("objects", window_name="first")
        window = session.new_window(window_name="second", attach=False)
        pane = window.split()
        pane.send_keys("echo over-control", enter=True)
        assert controlled.has_session("objects")
        assert not controlled.has_session("missing")
        assert sorted(w.window_name or "" for w in session.windows) == [
            "first",
            "second",
        ]
        assert len(window.panes) == 2
        assert [s.session_name for s in controlled.sessions] == ["objects"]
        assert isinstance(controlled.engine, ControlModeEngine)
        assert controlled.engine.generation == 1
        window.kill()
    finally:
        controlled.engine.close()  # type: ignore[attr-defined]
    assert client_count(server) == 0


def test_close_detaches_and_reaps_the_client(
    session: Session,
) -> None:
    """After :meth:`close` the client is gone, and the engine refuses work."""
    engine = ControlModeEngine.for_server(session.server)
    engine.run(req("display-message", "-p", "x"))
    proc = engine._proc
    assert proc is not None
    pid = proc.pid
    assert client_count(session.server) == 1

    engine.close()
    engine.close()

    assert not pid_alive(pid)
    assert client_count(session.server) == 0
    with pytest.raises(exc.EngineClosed):
        engine.run(req("display-message", "-p", "x"))
    with pytest.raises(exc.EngineClosed):
        engine.run(req("run-shell", "true"))


def test_a_killed_client_is_replaced_on_the_next_call(
    session: Session,
    engine: ControlModeEngine,
) -> None:
    """A client that died between calls costs a reconnect, not an error."""
    engine.run(req("display-message", "-p", "x"))
    proc = engine._proc
    assert proc is not None
    proc.kill()
    proc.wait()

    result = engine.run(req("display-message", "-p", "again"))

    assert result.stdout == ("again",)
    assert engine.generation == 2
    assert not pid_alive(proc.pid)
    assert client_count(session.server) == 1


def test_a_session_killed_under_the_client_moves_it_to_another(
    server: Server,
) -> None:
    """The client detaches when its session dies; the next call re-attaches."""
    first = server.new_session("one")
    server.new_session("two")
    with ControlModeEngine.for_server(server) as engine:
        engine.run(req("display-message", "-p", "x"))
        attached = engine.run(req("display-message", "-p", "#{session_name}"))
        assert attached.ok
        doomed = server.cmd("list-clients", "-F", "#{client_session}").stdout[0]
        engine.run(req("kill-session", "-t", f"={doomed}"))
        proc = engine._proc
        assert proc is not None
        proc.wait(timeout=5)  # tmux detaches the client behind the reply

        result = engine.run(req("display-message", "-p", "alive"))

        assert result.stdout == ("alive",)
        assert engine.generation == 2
    assert first.session_id is not None


FAKE_TMUX = textwrap.dedent(
    """\
    #!{python}
    import os, sys, time
    mode = open(os.environ["FAKE_TMUX_MODE"]).read().strip()
    args = sys.argv[1:]
    if "list-sessions" in args:
        print("$0 off")
        sys.exit(0)
    if "attach-session" not in args:
        sys.exit(0)
    out = sys.stdout
    def send(text):
        out.write(text)
        out.flush()
    send("%begin 1 10 0\\n%end 1 10 0\\n")
    number = 10
    for index, line in enumerate(sys.stdin, 1):
        number += 1
        if mode == "die" and index == 3:
            sys.stderr.write("server exited unexpectedly\\n")
            sys.stderr.flush()
            os._exit(1)
        if mode == "garbage" and index == 3:
            send("%begin not a guard\\n")
            continue
        if mode == "backwards" and index == 3:
            send("%begin 1 5 1\\n%end 1 5 1\\n")
            continue
        body = line.rstrip("\\n") if mode == "delay" else "ok"
        if mode == "delay" and index == 3:
            time.sleep(0.6)
        send(f"%begin 1 {number} 1\\n{body}\\n%end 1 {number} 1\\n")
    """,
)


@pytest.fixture
def fake_tmux(
    tmp_path: pathlib.Path,
) -> Iterator[t.Callable[[str], ControlModeEngine]]:
    """Build engines over a scripted tmux that misbehaves on its second command."""
    script = tmp_path / "fake-tmux"
    script.write_text(FAKE_TMUX.replace("{python}", sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    engines: list[ControlModeEngine] = []

    def build(mode: str) -> ControlModeEngine:
        (tmp_path / "mode").write_text(mode)
        os.environ["FAKE_TMUX_MODE"] = str(tmp_path / "mode")
        engine = ControlModeEngine(str(script))
        engines.append(engine)
        return engine

    try:
        yield build
    finally:
        for engine in engines:
            engine.close()
        os.environ.pop("FAKE_TMUX_MODE", None)


def test_a_client_that_dies_mid_request_raises_with_its_stderr(
    fake_tmux: t.Callable[[str], ControlModeEngine],
) -> None:
    """The pending call fails loudly, the client is reaped, a retry reconnects."""
    engine = fake_tmux("die")
    assert engine.run(req("display-message", "-p", "ok")).stdout == ("ok",)
    proc = engine._proc
    assert proc is not None

    with pytest.raises(exc.ControlConnectionLost, match="server exited unexpectedly"):
        engine.run(req("display-message", "-p", "dies"))

    assert not pid_alive(proc.pid)
    assert engine._proc is None


@pytest.mark.parametrize("mode", ["garbage", "backwards"])
def test_a_protocol_error_discards_the_connection(
    fake_tmux: t.Callable[[str], ControlModeEngine],
    mode: str,
) -> None:
    """Malformed or out-of-sequence framing is never resynchronised."""
    engine = fake_tmux(mode)
    engine.run(req("display-message", "-p", "ok"))
    proc = engine._proc
    assert proc is not None

    with pytest.raises(exc.ControlProtocolError):
        engine.run(req("display-message", "-p", "bad"))

    assert not pid_alive(proc.pid)
    assert engine._proc is None


def test_a_missing_binary_raises_the_usual_exception(tmp_path: pathlib.Path) -> None:
    """The error matches the subprocess engine's."""
    with (
        ControlModeEngine(str(tmp_path / "nope")) as engine,
        pytest.raises(exc.TmuxCommandNotFound),
    ):
        engine.run(req("list-sessions"))


def test_with_connection_binds_a_server_without_sharing_state(
    session: Session,
) -> None:
    """``Server(engine=...)`` adopts the server's flags on a fresh engine."""
    template = ControlModeEngine()
    server = Server(socket_name=session.server.socket_name, engine=template)

    try:
        assert server.engine is not template
        assert server.engine.server_args == (f"-L{session.server.socket_name}",)  # type: ignore[attr-defined]
        assert template.generation == 0
    finally:
        with contextlib.suppress(Exception):
            server.engine.close()  # type: ignore[attr-defined]


def test_a_control_timeout_abandons_the_reply_and_keeps_the_connection(
    fake_tmux: t.Callable[[str], ControlModeEngine],
) -> None:
    """A late reply is consumed and dropped; the next request gets its own."""
    engine = fake_tmux("delay")
    engine.run(req("display-message", "-p", "first"))
    proc = engine._proc
    generation = engine.generation

    started = time.monotonic()
    with pytest.raises(exc.TmuxTimeout) as excinfo:
        engine.run(
            CommandRequest.from_args("display-message", "-p", "slow", timeout=0.2)
        )

    assert time.monotonic() - started < 0.55  # gave up before the reply came
    assert excinfo.value.timeout == 0.2
    assert engine._proc is proc  # the connection is kept
    follow = engine.run(req("display-message", "-p", "next"))
    assert follow.stdout == ("'display-message' '-p' 'next'",)
    assert engine.generation == generation


def test_a_control_timeout_in_a_batch_abandons_every_owed_reply(
    fake_tmux: t.Callable[[str], ControlModeEngine],
) -> None:
    """Requests queued behind the timed-out one are dropped too."""
    engine = fake_tmux("delay")
    engine.run(req("display-message", "-p", "first"))

    with pytest.raises(exc.TmuxTimeout):
        engine.run_batch(
            [
                CommandRequest.from_args("display-message", "-p", "slow", timeout=0.2),
                req("display-message", "-p", "queued"),
            ],
        )

    follow = engine.run(req("display-message", "-p", "after"))
    assert follow.stdout == ("'display-message' '-p' 'after'",)


def test_a_control_timeout_on_a_command_group_rebuilds_the_connection(
    fake_tmux: t.Callable[[str], ControlModeEngine],
) -> None:
    """A group owes an unknown number of blocks, so the connection is dropped."""
    engine = fake_tmux("delay")
    engine.run(req("display-message", "-p", "first"))
    proc = engine._proc
    assert proc is not None
    sep = CommandSeparator(";")

    with pytest.raises(exc.TmuxTimeout):
        engine.run(
            CommandRequest.from_args(
                "display-message",
                "-p",
                "a",
                sep,
                "display-message",
                "-p",
                "b",
                timeout=0.2,
            ),
        )

    assert engine._proc is None
    assert not pid_alive(proc.pid)


def test_input_and_blocking_commands_keep_their_subprocess_semantics(
    session: Session,
    engine: ControlModeEngine,
) -> None:
    """``input`` and a timeout on a waiting command run in a subprocess."""
    engine.run(req("display-message", "-p", "warm"))
    generation = engine.generation

    loaded = engine.run(
        CommandRequest.from_args("load-buffer", "-b", "ctl", "-", input=b"from stdin"),
    )
    shown = engine.run(req("show-buffer", "-b", "ctl"))
    with pytest.raises(exc.TmuxTimeout):
        engine.run(CommandRequest.from_args("wait-for", "never", timeout=0.3))

    assert loaded.process is not None  # a subprocess carried the stdin
    assert shown.stdout == ("from stdin",)
    assert engine.run(req("display-message", "-p", "alive")).stdout == ("alive",)
    assert engine.generation == generation
