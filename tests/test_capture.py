"""Counter-aligned captures of retained main-grid history."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import shutil
import subprocess
import sys
import typing as t

import pytest

from libtmux import Pane, Server, capture, exc
from libtmux.formats import FORMAT_SEPARATOR

if t.TYPE_CHECKING:
    from libtmux.common import tmux_cmd
    from libtmux.session import Session


@pytest.fixture
def history_pane(session: Session) -> Pane:
    """Use an empty pane so native input completion needs no polling."""
    version = session.cmd("display-message", "-p", "#{version}").stdout[0]
    if version.startswith(("3.2", "3.3", "3.4", "3.5", "3.6", "3.7")):
        pytest.skip("history counters require tmux 3.8")
    session.set_option("history-limit", 5)
    pane_id = session.cmd("new-window", "-d", "-P", "-F#{pane_id}", "").stdout[0]
    pane = Pane.from_pane_id(session.server, pane_id)
    pane.window.resize(width=20, height=5)
    return pane


def _write(pane: Pane, text: str) -> None:
    """Feed an owned empty pane; the client exits after native input parsing."""
    socket = pane.cmd("display-message", "-p", "#{socket_path}").stdout[0]
    binary = pane.server.tmux_bin or shutil.which("tmux")
    assert binary is not None
    assert pane.pane_id is not None
    subprocess.run(
        [binary, "-S", socket, "display-message", "-I", "-t", pane.pane_id],
        input=text,
        text=True,
        capture_output=True,
        check=True,
        timeout=0.5,
        env={k: v for k, v in os.environ.items() if k not in {"TMUX", "TMUX_PANE"}},
    )


def test_repeated_history_distinguishes_eviction_from_gap(history_pane: Pane) -> None:
    """Equal text must still expose both newly retained rows and lost rows."""
    _write(history_pane, "same\r\n" * 64)
    first = history_pane.capture_since()
    assert first.status == "reset"
    assert first.reason == "initial"
    assert first.lines == ("same",) * 5

    _write(history_pane, "same\r\n" * 2)
    second = history_pane.capture_since(first.cursor)
    assert second.status == "continuous"
    assert second.lines == ("same",) * 2
    assert second.text == "same\nsame"
    assert second.cursor is not first.cursor

    _write(history_pane, "same\r\n" * 64)
    third = history_pane.capture_since(second.cursor)
    assert third.status == "gap"
    assert third.lines == ("same",) * 5
    assert history_pane.capture_since(third.cursor).lines == ()


def test_capture_since_rejects_unsupported_daemon(session: Session) -> None:
    """The connected daemon determines support, including the core floor."""
    pane = session.active_pane
    assert pane is not None
    version = pane.cmd("display-message", "-p", "#{version}").stdout[0]
    if version.startswith(("3.2", "3.3", "3.4", "3.5", "3.6", "3.7")):
        with pytest.raises(exc.VersionTooLow, match=r"connected.*3\.8"):
            pane.capture_since()
    else:
        assert pane.capture_since().status == "reset"


def test_history_excludes_viewport_and_preserves_blank_rows(history_pane: Pane) -> None:
    """History framing must distinguish empty history from retained blank rows."""
    _write(history_pane, "visible")
    first = history_pane.capture_since()
    assert first.lines == ()
    assert first.status == "reset"
    unchanged = history_pane.capture_since(first.cursor)
    assert unchanged.status == "continuous"
    assert unchanged.lines == ()
    _write(history_pane, "\r\n" * 10)
    blank = history_pane.capture_since(unchanged.cursor)
    assert blank.lines == ("",) * 5
    assert blank.status == "gap"


@pytest.mark.parametrize(
    ("command", "arguments", "status", "reason"),
    [
        ("clear-history", (), "reset", "generation-changed"),
        ("resize-window", ("-x", "18"), "reset", "geometry-changed"),
        ("resize-window", ("-y", "7"), "reset", "geometry-changed"),
        ("resize-pane", ("-T",), "unknown", "counter-mismatch"),
    ],
)
def test_history_changes_invalidate_alignment(
    history_pane: Pane,
    command: str,
    arguments: tuple[str, ...],
    status: str,
    reason: str,
) -> None:
    """Clear, reflow, height change, and bottom deletion cannot form a delta."""
    _write(history_pane, "same\r\n" * 20 + "\x1b[1;1H")
    first = history_pane.capture_since()
    result = history_pane.cmd(command, *arguments)
    assert not result.stderr
    changed = history_pane.capture_since(first.cursor)
    assert (changed.status, changed.reason) == (status, reason)


def test_alternate_screen_does_not_qualify_history(history_pane: Pane) -> None:
    """An observed alternate screen invalidates its cursor without reading -a."""
    _write(history_pane, "main\r\n" * 20)
    first = history_pane.capture_since()
    _write(history_pane, "\x1b[?1049h" + "alternate\r\n" * 20)
    alternate = history_pane.capture_since(first.cursor)
    assert alternate.status == "unknown"
    assert alternate.reason == "alternate-screen"
    assert alternate.lines == first.lines
    _write(history_pane, "\x1b[?1049l")
    restored = history_pane.capture_since(alternate.cursor)
    assert (restored.status, restored.reason) == ("reset", "unqualified-cursor")
    assert restored.lines == first.lines


@pytest.mark.parametrize("counter", ["added", "collected", "generation"])
def test_missing_counters_never_qualify_empty_delta(
    history_pane: Pane,
    monkeypatch: pytest.MonkeyPatch,
    counter: str,
) -> None:
    """Fault injection models unavailable formats on an otherwise reachable daemon."""
    first = history_pane.capture_since()
    check = capture._check

    def missing(proc: tmux_cmd, command: str) -> None:
        check(proc, command)
        if command == "display-message":
            fields = proc.stdout[0].split(FORMAT_SEPARATOR)
            fields[capture._FIELDS.index(f"history_{counter}")] = ""
            proc.stdout[:] = [FORMAT_SEPARATOR.join(fields)]

    monkeypatch.setattr(capture, "_check", missing)
    result = history_pane.capture_since(first.cursor)
    assert (result.status, result.reason) == ("unknown", "missing-counters")
    assert result.lines == ()
    assert result.cursor._snapshot is None


def test_capture_race_returns_unknown(
    history_pane: Pane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deterministic metadata interleave models output during separate commands."""
    _write(history_pane, "same\r\n" * 20)
    first = history_pane.capture_since()
    read = capture._read_metadata
    calls = 0

    def interleave(pane: Pane) -> capture._Snapshot | None:
        nonlocal calls
        sample = read(pane)
        calls += 1
        if calls == 1:
            _write(pane, "same\r\n")
        return sample

    monkeypatch.setattr(capture, "_read_metadata", interleave)
    result = history_pane.capture_since(first.cursor)
    assert (result.status, result.reason) == ("unknown", "changed-during-capture")
    assert result.cursor._snapshot is None


def test_custom_route_retains_history_without_qualifying_it(
    history_pane: Pane,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route to another endpoint without borrowing local identity evidence."""
    _write(history_pane, "local\r\n" * 20)
    other = Server(socket_path=tmp_path / "other.sock", config_file="/dev/null")
    commands = []
    try:
        session = other.new_session(session_name="routed", window_command="cat")
        session.set_option("history-limit", 5)
        pane = session.active_pane
        assert pane is not None
        while pane.pane_id != history_pane.pane_id:
            pane_id = session.cmd("new-window", "-d", "-P", "-F#{pane_id}", "").stdout[
                0
            ]
            pane = Pane.from_pane_id(other, pane_id)
        pane.window.resize(width=20, height=5)
        _write(pane, "routed\r\n" * 20)

        def routed(command: str, *args: t.Any, **kwargs: t.Any) -> t.Any:
            commands.append(command)
            return pane.cmd(command, *args, **kwargs)

        monkeypatch.setattr(history_pane, "cmd", routed)
        result = history_pane.capture_since()
        assert (result.status, result.reason) == ("unknown", "unverified-endpoint")
        assert result.lines == ("routed",) * 5
        assert commands == ["display-message", "capture-pane", "display-message"]
    finally:
        other.kill()


def test_removed_pane_raises_but_retained_result_survives(history_pane: Pane) -> None:
    """Removal cannot erase frozen text or become a successful empty delta."""
    _write(history_pane, "retained\r\n" * 20)
    result = history_pane.capture_since()
    history_pane.kill()
    with pytest.raises(exc.LibTmuxException):
        history_pane.capture_since(result.cursor)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.cursor.grid = "history"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.reason = "changed"  # type: ignore[misc]
    assert result.lines == ("retained",) * 5


@pytest.mark.parametrize("returncode", [1, None, False])
def test_failed_capture_with_empty_stderr_raises(
    history_pane: Pane,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int | None,
) -> None:
    """A dispatcher fault without diagnostics must not become empty history."""
    _write(history_pane, "same\r\n" * 20)
    dispatch = history_pane.cmd

    def failed(command: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        proc = dispatch(command, *args, **kwargs)
        if command == "capture-pane":
            proc.stdout = []
            proc.stderr = []
            proc.returncode = returncode
        return proc

    monkeypatch.setattr(history_pane, "cmd", failed)
    with pytest.raises(exc.LibTmuxException, match="status"):
        history_pane.capture_since()


@pytest.mark.parametrize("attribute", ["_engine", "engine"])
def test_injected_engine_cannot_qualify_local_identity(
    history_pane: Pane,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
) -> None:
    """An opaque backend injection cannot borrow native socket evidence."""
    monkeypatch.setattr(history_pane.server, attribute, object(), raising=False)
    result = history_pane.capture_since()
    assert (result.status, result.reason) == ("unknown", "unverified-endpoint")


@pytest.mark.parametrize("mutation", ["handle", "environment"])
def test_native_capture_pins_one_route(
    history_pane: Pane,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    """Interleave same-ID endpoints so a mixed-route capture would falsely align."""
    _write(history_pane, "alpha\r\n" * 20)
    first = history_pane.capture_since()
    _write(history_pane, "alpha\r\n" * 5)
    native_path = history_pane.cmd("display-message", "-p", "#{socket_path}").stdout[0]
    directory = tmp_path / f"tmux-{os.getuid()}"
    directory.mkdir(mode=0o700)
    other = Server(
        socket_path=directory / pathlib.Path(native_path).name, config_file="/dev/null"
    )
    server = history_pane.server
    old_name, old_path = server.socket_name, server.socket_path
    old_tmpdir = os.environ.get("TMUX_TMPDIR")
    try:
        session = other.new_session(session_name="other", window_command="cat")
        session.set_option("history-limit", 5)
        pane = session.active_pane
        assert pane is not None
        while pane.pane_id != history_pane.pane_id:
            pane_id = session.cmd("new-window", "-d", "-P", "-F#{pane_id}", "").stdout[
                0
            ]
            pane = Pane.from_pane_id(other, pane_id)
        pane.window.resize(width=20, height=5)
        _write(pane, "beta\r\n" * 20)
        read = capture._read_metadata
        calls = 0

        def interleave(target: Pane) -> capture._Snapshot | None:
            nonlocal calls
            if calls:
                server.socket_name, server.socket_path = old_name, old_path
                if old_tmpdir is None:
                    monkeypatch.delenv("TMUX_TMPDIR", raising=False)
                else:
                    monkeypatch.setenv("TMUX_TMPDIR", old_tmpdir)
            sample = read(target)
            if not calls:
                if mutation == "handle":
                    server.socket_name = None
                    server.socket_path = other.socket_path
                else:
                    monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path))
            calls += 1
            return sample

        monkeypatch.setattr(capture, "_read_metadata", interleave)
        result = history_pane.capture_since(first.cursor)
        assert result.status == "continuous"
        assert result.lines == ("alpha",) * 5
    finally:
        server.socket_name, server.socket_path = old_name, old_path
        other.kill()


def test_endpoint_replacement_resets_same_pane_id(history_pane: Pane) -> None:
    """A new daemon on the same socket must not inherit an old pane's cursor."""
    first = history_pane.capture_since()
    server = history_pane.server
    server.kill()
    with pytest.raises(exc.LibTmuxException):
        history_pane.capture_since(first.cursor)
    replacement = server.new_session(session_name="replacement", window_command="cat")
    pane = replacement.active_pane
    assert pane is not None
    while pane.pane_id != history_pane.pane_id:
        pane_id = replacement.cmd("new-window", "-d", "-P", "-F#{pane_id}", "").stdout[
            0
        ]
        pane = Pane.from_pane_id(server, pane_id)
    pane.window.resize(width=20, height=5)
    result = pane.capture_since(first.cursor)
    assert (result.status, result.reason) == ("reset", "scope-changed")

    # Actual PID reuse is nondeterministic. Preserve the real old/new socket
    # identities while making all native format fields equal deliberately.
    previous = first.cursor._snapshot
    current = result.cursor._snapshot
    assert previous is not None and current is not None
    same_pid = dataclasses.replace(
        first.cursor,
        _snapshot=dataclasses.replace(current, scope=previous.scope),
    )
    assert pane.capture_since(same_pid).status == "reset"


def test_height_round_trip_with_changed_history_is_unknown(history_pane: Pane) -> None:
    """Height ABA can preserve counters; retained-row comparison must still bite."""
    _write(history_pane, "same\r\n" * 20)
    first = history_pane.capture_since()
    history_pane.window.resize(height=7)
    _write(history_pane, "\x1b[1;1Hchanged\x1b[7;1H")
    history_pane.window.resize(height=5)
    result = history_pane.capture_since(first.cursor)
    assert (result.status, result.reason) == ("unknown", "history-changed")


def test_counter_regression_is_unknown(history_pane: Pane) -> None:
    """A constructed pre-wrap cursor avoids emitting billions of native rows."""
    first = history_pane.capture_since()
    snapshot = first.cursor._snapshot
    assert snapshot is not None
    wrapped = dataclasses.replace(
        first.cursor,
        _snapshot=dataclasses.replace(snapshot, added=0xFFFFFFFF),
    )
    result = history_pane.capture_since(wrapped)
    assert (result.status, result.reason) == ("unknown", "counter-regression")


def test_invalid_grid_does_not_dispatch(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dispatcher sentinel proves unsupported selectors fail before effects."""
    pane = session.active_pane
    assert pane is not None

    def forbidden(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("unsupported selector dispatched a command")

    monkeypatch.setattr(pane, "cmd", forbidden)
    with pytest.raises(ValueError, match="history"):
        pane.capture_since(grid="alternate")  # type: ignore[arg-type]


def test_history_example_runs_unchanged_twice(
    history_pane: Pane, tmp_path: pathlib.Path
) -> None:
    """Execute the published program and preserve an unrelated live session."""
    session = history_pane.session
    unrelated = session.active_pane
    assert unrelated is not None
    pid = unrelated.pane_pid
    assert pid is not None
    example = pathlib.Path(__file__).parents[1] / "examples" / "history_delta.py"
    env = {k: v for k, v in os.environ.items() if k not in {"TMUX", "TMUX_PANE"}}
    env["TMPDIR"] = str(tmp_path)
    for _ in range(2):
        try:
            proc = subprocess.run(
                [sys.executable, str(example)],
                env=env,
                text=True,
                capture_output=True,
                timeout=1,
                check=True,
            )
            assert proc.stdout == "continuous: 2 rows; gap: 5 retained rows\n"
            assert not list(tmp_path.iterdir())
        finally:
            for socket in tmp_path.glob("lt-history-*/tmux.sock"):
                if socket.is_socket():
                    Server(
                        socket_path=socket, tmux_bin=history_pane.server.tmux_bin
                    ).kill()
    unrelated.refresh()
    assert unrelated.pane_pid == pid
    os.kill(int(pid), 0)
