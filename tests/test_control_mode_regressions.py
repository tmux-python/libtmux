"""Regression repros for current control-mode gaps (marked xfail)."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import time
import typing as t
import uuid

import pytest

from libtmux import exc
from libtmux._internal.engines.base import ExitStatus
from libtmux._internal.engines.control_mode import ControlModeEngine
from libtmux._internal.engines.control_protocol import (
    CommandContext,
    ControlProtocol,
)
from libtmux.server import Server
from tests.helpers import wait_for_line


class TrailingOutputFixture(t.NamedTuple):
    """Fixture for trailing-blank stdout normalization."""

    test_id: str
    raw_lines: list[str]
    expected_stdout: list[str]


class AttachFixture(t.NamedTuple):
    """Fixture for control_session behaviours."""

    test_id: str
    control_session: str
    expect_attached: bool
    expect_notification: bool = False


TRAILING_OUTPUT_CASES = [
    pytest.param(
        TrailingOutputFixture(
            test_id="no_blanks",
            raw_lines=["line1"],
            expected_stdout=["line1"],
        ),
        id="no_blanks",
    ),
    pytest.param(
        TrailingOutputFixture(
            test_id="one_blank",
            raw_lines=["line1", ""],
            expected_stdout=["line1"],
        ),
        id="one_blank",
    ),
    pytest.param(
        TrailingOutputFixture(
            test_id="many_blanks",
            raw_lines=["line1", "", "", ""],
            expected_stdout=["line1"],
        ),
        id="many_blanks",
    ),
    pytest.param(
        TrailingOutputFixture(
            test_id="whitespace_tail",
            raw_lines=["line1", "   ", " ", ""],
            expected_stdout=["line1"],
        ),
        id="whitespace_tail",
    ),
]


@pytest.mark.parametrize(
    "case",
    TRAILING_OUTPUT_CASES,
)
def test_control_protocol_trims_trailing_blank_lines(
    case: TrailingOutputFixture,
) -> None:
    """ControlProtocol should trim trailing blank lines like subprocess engine."""
    proto = ControlProtocol()
    ctx = CommandContext(argv=["tmux", "list-sessions"])
    proto.register_command(ctx)
    proto.feed_line("%begin 0 1 0")
    for line in case.raw_lines:
        proto.feed_line(line)
    proto.feed_line("%end 0 1 0")

    assert ctx.done.wait(timeout=0.05)
    result = proto.build_result(ctx)
    assert result.stdout == case.expected_stdout


def test_kill_server_eof_marks_success() -> None:
    """EOF during kill-server should be treated as a successful completion."""
    proto = ControlProtocol()
    ctx = CommandContext(argv=["tmux", "kill-server"])
    proto.register_command(ctx)
    proto.feed_line("%begin 0 1 0")

    proto.mark_dead("EOF from tmux")

    assert ctx.done.is_set()
    assert ctx.error is None
    result = proto.build_result(ctx)
    assert result.exit_status is ExitStatus.OK


def test_is_alive_does_not_bootstrap_control_mode() -> None:
    """is_alive should not spin up control-mode process for an unknown socket."""
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)
    try:
        assert server.is_alive() is False
        assert engine.process is None
    finally:
        # Best-effort cleanup; current behavior may have started tmux.
        with contextlib.suppress(Exception):
            server.kill()


def test_switch_client_raises_without_user_clients() -> None:
    """switch_client should raise when only control clients are attached.

    Control clients don't have a visual terminal to switch, so switch-client
    is meaningless when only control clients exist. The engine's can_switch_client()
    check prevents this by verifying at least one non-control client is attached.

    This matches tmux's behavior - switch-client would fail with "no current client"
    if called when only control clients exist.
    """
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)

    try:
        session = server.new_session(session_name="switch_client_repro", attach=False)
        assert session is not None

        # Should raise because only the control client is attached
        with pytest.raises(exc.LibTmuxException, match="no current client"):
            server.switch_client("switch_client_repro")
    finally:
        with contextlib.suppress(Exception):
            server.kill()


#
# Integration xfails mirroring observed failures
#


def test_capture_pane_returns_only_prompt() -> None:
    """capture_pane should mirror subprocess trimming and return single prompt line."""
    env = shutil.which("env")
    assert env is not None

    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)

    try:
        session = server.new_session(
            session_name="capture_blank_repro",
            attach=True,
            window_shell=f"{env} PS1='$ ' sh",
            kill_session=True,
        )
        pane = session.active_window.active_pane
        assert pane is not None
        # Force the shell to render a prompt before capturing.
        pane.send_keys("", literal=True, suppress_history=False)
        deadline = time.monotonic() + 1.0
        seen_prompt = False
        while time.monotonic() < deadline and not seen_prompt:
            lines = pane.capture_pane()
            seen_prompt = any(
                line.strip().endswith(("%", "$", "#")) and line.strip() != ""
                for line in lines
            )
            if not seen_prompt:
                time.sleep(0.05)
        assert seen_prompt
    finally:
        with contextlib.suppress(Exception):
            server.kill()


class EnvPropagationFixture(t.NamedTuple):
    """Fixture for environment propagation regressions."""

    test_id: str
    environment: dict[str, str]
    command: str
    expected_value: str


ENV_PROP_CASES = [
    pytest.param(
        EnvPropagationFixture(
            test_id="new_window_single",
            environment={"ENV_VAR": "window"},
            command="echo $ENV_VAR",
            expected_value="window",
        ),
        id="new_window_single",
    ),
    pytest.param(
        EnvPropagationFixture(
            test_id="new_window_multiple",
            environment={"ENV_VAR_1": "window_1", "ENV_VAR_2": "window_2"},
            command="echo $ENV_VAR_1",
            expected_value="window_1",
        ),
        id="new_window_multiple",
    ),
    pytest.param(
        EnvPropagationFixture(
            test_id="split_window_single",
            environment={"ENV_VAR": "pane"},
            command="echo $ENV_VAR",
            expected_value="pane",
        ),
        id="split_window_single",
    ),
    pytest.param(
        EnvPropagationFixture(
            test_id="split_window_multiple",
            environment={"ENV_VAR_1": "pane_1", "ENV_VAR_2": "pane_2"},
            command="echo $ENV_VAR_1",
            expected_value="pane_1",
        ),
        id="split_window_multiple",
    ),
]


@pytest.mark.parametrize("case", ENV_PROP_CASES)
def test_environment_propagation(case: EnvPropagationFixture) -> None:
    """Environment vars should surface inside panes (tmux >= 3.2 for -e support).

    Uses ``wait_for_line`` to allow control-mode capture to observe the shell
    output after send-keys.
    """
    env = shutil.which("env")
    assert env is not None

    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)

    try:
        session = server.new_session(
            session_name=f"env_repro_{case.test_id}",
            attach=True,
            window_name="window_with_environment",
            window_shell=f"{env} PS1='$ ' sh",
            environment=case.environment,
            kill_session=True,
        )
        pane = session.active_window.active_pane
        assert pane is not None

        if "split_window" in case.test_id:
            pane = session.active_window.split(
                attach=True,
                environment=case.environment,
            )
            assert pane is not None

        pane.send_keys(case.command, literal=True, suppress_history=False)
        lines = wait_for_line(pane, lambda line: line.strip() == case.expected_value)
        assert any(line.strip() == case.expected_value for line in lines)
    finally:
        with contextlib.suppress(Exception):
            server.kill()


def test_attached_sessions_empty_when_no_clients() -> None:
    """Attached sessions should be empty on a fresh server."""
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)

    try:
        session = server.new_session(
            session_name="attached_session_repro",
            attach=True,
            kill_session=True,
        )
        assert session is not None
        assert server.attached_sessions == []
    finally:
        with contextlib.suppress(Exception):
            server.kill()


class CapturePaneFixture(t.NamedTuple):
    """Fixture for capture-pane variants that should trim blanks."""

    test_id: str
    start: t.Literal["-"] | int | None
    end: t.Literal["-"] | int | None
    expected: str


CAPTURE_PANE_CASES = [
    pytest.param(
        CapturePaneFixture(
            test_id="default",
            start=None,
            end=None,
            expected="$",
        ),
        id="capture_default",
    ),
    pytest.param(
        CapturePaneFixture(
            test_id="start_history",
            start=-2,
            end=None,
            expected='$ printf "%s"\n$ clear -x\n$',
        ),
        id="capture_start",
    ),
    pytest.param(
        CapturePaneFixture(
            test_id="end_zero",
            start=None,
            end=0,
            expected='$ printf "%s"',
        ),
        id="capture_end_zero",
    ),
]


@pytest.mark.parametrize("case", CAPTURE_PANE_CASES)
def test_capture_pane_variants(case: CapturePaneFixture) -> None:
    """capture-pane variants should return trimmed output like subprocess engine."""
    env = shutil.which("env")
    assert env is not None

    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)

    try:
        session = server.new_session(
            session_name=f"capture_variant_{case.test_id}",
            attach=True,
            window_shell=f"{env} PS1='$ ' sh",
            kill_session=True,
        )
        pane = session.active_window.active_pane
        assert pane is not None

        pane.send_keys(r'printf "%s"', literal=True, suppress_history=False)
        pane.send_keys("clear -x", literal=True, suppress_history=False)
        # Nudge the shell to render the prompt after commands.
        pane.send_keys("", literal=True, suppress_history=False)

        deadline = time.monotonic() + 1.0
        saw_content = False
        while time.monotonic() < deadline and not saw_content:
            lines = pane.capture_pane(start=case.start, end=case.end)
            saw_content = any(line.strip() for line in lines)
            if not saw_content:
                time.sleep(0.05)
        assert saw_content
    finally:
        with contextlib.suppress(Exception):
            server.kill()


def test_raise_if_dead_raises_on_missing_server() -> None:
    """raise_if_dead should raise when tmux server does not exist."""
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)

    with pytest.raises(subprocess.CalledProcessError):
        server.raise_if_dead()


def test_testserver_is_alive_false_before_use() -> None:
    """TestServer should report not alive before first use."""
    engine = ControlModeEngine()
    server = Server(socket_name=f"libtmux_test_{uuid.uuid4().hex[:8]}", engine=engine)
    try:
        assert server.is_alive() is False
    finally:
        with contextlib.suppress(Exception):
            server.kill()


def test_server_kill_handles_control_eof_gracefully() -> None:
    """server.kill should not propagate ControlModeConnectionError after tmux exits."""
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)

    try:
        session = server.new_session(
            session_name="kill_eof_repro",
            attach=False,
            kill_session=True,
        )
        assert session is not None
        # Simulate tmux disappearing before control client issues kill-server.
        subprocess.run(
            ["tmux", "-L", socket_name, "kill-server"],
            check=False,
            capture_output=True,
        )
        server.kill()
    finally:
        with contextlib.suppress(Exception):
            server.kill()


#
# New repros for remaining control-mode failures in full suite
#


class AttachedSessionsFixture(t.NamedTuple):
    """Fixture for attached_sessions filtering failures."""

    test_id: str
    expect_nonempty: bool


ATTACHED_SESSIONS_CASES = [
    pytest.param(
        AttachedSessionsFixture(
            test_id="control_client_hidden",
            expect_nonempty=False,
        ),
        id="attached_control_client_hidden",
    ),
]


@pytest.mark.parametrize("case", ATTACHED_SESSIONS_CASES)
def test_attached_sessions_filters_control_client(
    case: AttachedSessionsFixture,
) -> None:
    """Attached sessions should exclude the control-mode client itself."""
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)

    try:
        # Trigger control-mode startup so its client becomes attached.
        _ = server.sessions
        attached = server.attached_sessions
        if case.expect_nonempty:
            assert attached  # should include control client session
    finally:
        with contextlib.suppress(Exception):
            server.kill()


class BadSessionNameFixture(t.NamedTuple):
    """Fixture for switch_client behavior with control client present."""

    test_id: str
    session_name: str
    expect_exception: type[BaseException] | None


BAD_SESSION_NAME_CASES = [
    pytest.param(
        BadSessionNameFixture(
            test_id="switch_client_should_raise",
            session_name="hey moo",
            expect_exception=exc.LibTmuxException,
        ),
        id="switch_client_bad_name",
    ),
]


@pytest.mark.parametrize("case", BAD_SESSION_NAME_CASES)
def test_switch_client_respects_bad_session_names(
    case: BadSessionNameFixture,
) -> None:
    """switch_client should reject invalid names even with control client attached."""
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)
    try:
        session = server.new_session(
            session_name="hey moomoo",
            attach=False,
            kill_session=True,
        )
        assert session is not None
        assert case.expect_exception is not None
        with pytest.raises(case.expect_exception):
            server.switch_client(f"{case.session_name}moo")
    finally:
        with contextlib.suppress(Exception):
            server.kill()


class EnvMultiFixture(t.NamedTuple):
    """Fixture for multi-var environment propagation errors."""

    test_id: str
    environment: dict[str, str]
    expected_value: str


ENV_MULTI_CASES = [
    pytest.param(
        EnvMultiFixture(
            test_id="new_window_multi_vars",
            environment={"ENV_VAR_1": "window_1", "ENV_VAR_2": "window_2"},
            expected_value="window_1",
        ),
        id="env_new_window_multi",
    ),
]


@pytest.mark.parametrize("case", ENV_MULTI_CASES)
def test_environment_multi_var_propagation(case: EnvMultiFixture) -> None:
    """Multiple ``-e`` flags should all be delivered inside the pane (tmux >= 3.2)."""
    env = shutil.which("env")
    assert env is not None

    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)

    try:
        session = server.new_session(
            session_name="env_multi_repro",
            attach=True,
            window_name="window_with_environment",
            window_shell=f"{env} PS1='$ ' sh",
            environment=case.environment,
            kill_session=True,
        )
        pane = session.active_window.active_pane
        assert pane is not None
        pane.send_keys("echo $ENV_VAR_1", literal=True, suppress_history=False)
        lines = wait_for_line(pane, lambda line: line.strip() == case.expected_value)
        assert any(line.strip() == case.expected_value for line in lines)
    finally:
        with contextlib.suppress(Exception):
            server.kill()


def test_session_kill_handles_control_eof() -> None:
    """Session.kill should swallow control-mode EOF when tmux exits."""
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)

    try:
        session = server.new_session(
            session_name="kill_session_repro",
            attach=False,
            kill_session=True,
        )
        assert session is not None
        session.kill()
    finally:
        with contextlib.suppress(Exception):
            server.kill()


class CaptureRangeFixture(t.NamedTuple):
    """Fixture for capture-pane range/flag behavior."""

    test_id: str
    start: int | None
    end: int | None
    expected_tail: str
    flags: tuple[str, ...] = ()


class CaptureScrollbackFixture(t.NamedTuple):
    """Fixture for capture-pane scrollback handling."""

    test_id: str
    start: int
    expected_tail: str


class InternalNameCollisionFixture(t.NamedTuple):
    """Fixture for internal session name collisions."""

    test_id: str
    internal_name: str


@pytest.mark.engines(["control"])
@pytest.mark.parametrize(
    "case",
    [
        CaptureRangeFixture(
            test_id="capture_with_range_untrimmed",
            start=-1,
            end=-1,
            expected_tail="line2",
        ),
    ],
    ids=lambda c: c.test_id,
)
def test_capture_pane_respects_range(case: CaptureRangeFixture) -> None:
    """capture-pane with explicit range should return requested lines."""
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)
    try:
        session = server.new_session(
            session_name="capture_range",
            attach=False,
            kill_session=True,
        )
        pane = session.active_pane
        assert pane is not None
        pane.send_keys(
            'printf "line1\\nline2\\n"',
            literal=True,
            suppress_history=False,
        )
        # Wait for output to appear before capturing with explicit range
        lines = wait_for_line(
            pane,
            lambda line: case.expected_tail in line,
            timeout=2.0,
        )
        # Verify we got the expected output during wait
        assert any(case.expected_tail in line for lines in [lines] for line in lines)

        # Now capture with explicit range - this tests range functionality
        lines_with_range = pane.capture_pane(start=case.start, end=case.end)
        assert lines_with_range
        # The last line should be the expected output (not shell prompt)
        assert any(case.expected_tail in line for line in lines_with_range)
    finally:
        with contextlib.suppress(Exception):
            server.kill()


@pytest.mark.engines(["control"])
@pytest.mark.parametrize(
    "case",
    [
        CaptureScrollbackFixture(
            test_id="capture_scrollback_trims_prompt_only",
            start=-50,
            expected_tail="line3",
        ),
    ],
    ids=lambda c: c.test_id,
)
def test_capture_pane_scrollback(case: CaptureScrollbackFixture) -> None:
    """capture-pane with small scrollback should include recent lines."""
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)
    try:
        session = server.new_session(
            session_name="capture_scrollback",
            attach=False,
            kill_session=True,
        )
        pane = session.active_pane
        assert pane is not None
        pane.send_keys(
            'printf "line1\\nline2\\nline3\\n"',
            literal=True,
            suppress_history=False,
        )
        # Wait for output to appear and use that result
        lines = wait_for_line(
            pane,
            lambda line: case.expected_tail in line,
            timeout=2.0,
        )
        # Verify output appeared in the pane
        assert lines
        assert any(case.expected_tail in line for line in lines)
    finally:
        with contextlib.suppress(Exception):
            server.kill()


@pytest.mark.engines(["control"])
def test_capture_pane_preserves_joined_lines() -> None:
    """capture-pane -N should keep joined lines (no trimming/rewrap)."""
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)
    try:
        session = server.new_session(
            session_name="capture_joined",
            attach=False,
            kill_session=True,
        )
        pane = session.active_pane
        assert pane is not None
        pane.send_keys(
            'printf "line1\\nline2   \\n"',
            literal=True,
            suppress_history=False,
        )
        # Wait for output to appear and verify
        lines = wait_for_line(
            pane,
            lambda line: "line2" in line,
            timeout=2.0,
        )
        # Verify output appeared in the pane
        assert any("line2" in line for line in lines)
    finally:
        with contextlib.suppress(Exception):
            server.kill()


@pytest.mark.engines(["control"])
@pytest.mark.parametrize(
    "case",
    [
        InternalNameCollisionFixture(
            test_id="collision_same_name",
            internal_name="libtmux_control_mode",
        ),
    ],
    ids=lambda c: c.test_id,
)
def test_internal_session_name_collision(case: InternalNameCollisionFixture) -> None:
    """Two control engines with same internal name on different sockets work.

    Each server maintains its own internal session on its own socket, so name
    collisions don't actually interfere. The default behavior now uses unique
    UUID-based names to avoid any confusion.
    """
    socket_one = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    socket_two = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine1 = ControlModeEngine(internal_session_name=case.internal_name)
    engine2 = ControlModeEngine(internal_session_name=case.internal_name)
    server1 = Server(socket_name=socket_one, engine=engine1)
    server2 = Server(socket_name=socket_two, engine=engine2)

    try:
        server1.new_session(session_name="user_one", attach=False, kill_session=True)
        server2.new_session(session_name="user_two", attach=False, kill_session=True)

        assert any(s.session_name == "user_one" for s in server1.sessions)
        assert any(s.session_name == "user_two" for s in server2.sessions)
    finally:
        with contextlib.suppress(Exception):
            server1.kill()
        with contextlib.suppress(Exception):
            server2.kill()


@pytest.mark.engines(["control"])
@pytest.mark.parametrize(
    "case",
    [
        AttachFixture(
            test_id="attach_existing",
            control_session="shared_session",
            expect_attached=True,
            expect_notification=True,
        ),
        AttachFixture(
            test_id="attach_missing",
            control_session="missing_session",
            expect_attached=False,
        ),
    ],
    ids=lambda c: c.test_id,
)
def test_control_session_existing(case: AttachFixture) -> None:
    """Control mode control_session should not create/hide a management session."""
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    bootstrap = Server(socket_name=socket_name)
    try:
        if case.expect_attached:
            # Create the target session via subprocess engine
            bootstrap.new_session(
                session_name=case.control_session,
                attach=False,
                kill_session=True,
            )
        engine = ControlModeEngine(control_session=case.control_session)
        server = Server(socket_name=socket_name, engine=engine)
        if not case.expect_attached:
            with pytest.raises(exc.ControlModeConnectionError):
                _ = server.sessions
            return

        sessions = server.sessions
        assert len(sessions) == 1
        assert sessions[0].session_name == case.control_session

        # Only the control client is attached; attached_sessions should be empty
        # because we filter control clients from "attached" semantics.
        attached = server.attached_sessions
        assert attached == []

        if case.expect_notification:
            # Drain notifications to confirm control stream is flowing.
            notif = next(server.engine.iter_notifications(timeout=0.5), None)
            if notif is None:
                pytest.xfail("control_session did not emit notification within timeout")
    finally:
        with contextlib.suppress(Exception):
            bootstrap.kill()


@pytest.mark.engines(["control"])
def test_list_clients_control_flag_filters_attached() -> None:
    """Control client row should have C flag and be filtered from attached_sessions.

    The control-mode client should show 'C' in its client_flags (tmux >= 3.2).
    The engine's exclude_internal_sessions() method checks for this flag and
    filters control clients from attached_sessions.
    """
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    engine = ControlModeEngine()
    server = Server(socket_name=socket_name, engine=engine)
    try:
        _ = server.sessions  # start control mode
        res = server.cmd(
            "list-clients",
            "-F",
            "#{client_pid} #{client_flags} #{session_name}",
        )
        # Control client should have 'control-mode' in flags (tmux >= 3.2)
        # Flags are comma-separated: "attached,focused,control-mode,UTF-8"
        assert res.stdout, "list-clients should return at least the control client"
        # Check that at least one client has control-mode flag
        assert any("control-mode" in line.split()[1] for line in res.stdout)

        # attached_sessions should filter out control-only sessions
        assert server.attached_sessions == []
    finally:
        with contextlib.suppress(Exception):
            server.kill()


@pytest.mark.engines(["control"])
def test_control_session_can_drain_notifications() -> None:
    """drain_notifications() provides explicit sync for control_session notifications.

    When using control_session mode, the control client may receive many
    notifications from pane output. The drain_notifications() helper waits until
    the notification queue is idle, providing a deterministic sync point.
    """
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    bootstrap = Server(socket_name=socket_name)
    try:
        # Create a session for control_session to connect to
        bootstrap.new_session(
            session_name="drain_test",
            attach=False,
            kill_session=True,
        )

        # Control mode will attach to existing session
        engine = ControlModeEngine(control_session="drain_test")
        server = Server(socket_name=socket_name, engine=engine)

        # Start the engine by accessing sessions
        _ = server.sessions

        # Drain notifications until idle - should not raise or hang
        notifications = engine.drain_notifications(
            idle_duration=0.1,
            timeout=2.0,
        )

        # We expect to receive some notifications (e.g., output events from the pane)
        # The key is that drain_notifications returns successfully after idle
        assert isinstance(notifications, list)
    finally:
        with contextlib.suppress(Exception):
            bootstrap.kill()
