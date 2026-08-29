"""Tests for headless tmux-continuum style autosave helpers."""

from __future__ import annotations

import datetime
import pathlib
import typing as t

from libtmux.formats import FORMAT_SEPARATOR
from libtmux.resurrect.archives import WorkspaceArchive, write_archive
from libtmux.resurrect.continuum import (
    DEFAULT_AUTOSAVE_INTERVAL,
    AutosavePaths,
    AutosaveState,
    StartupRestoreDecision,
    autosave_once,
    default_autosave_paths,
    next_autosave_at,
    read_autosave_state,
    should_autosave,
    should_restore_on_startup,
    startup_restore_once,
    write_autosave_state,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server


class _Cmd:
    """Small command result test double."""

    def __init__(self, stdout: list[str] | None = None) -> None:
        self.stdout = stdout or []
        self.stderr: list[str] = []
        self.returncode = 0


class _FakeServer:
    """Server double that returns one captured pane."""

    def __init__(
        self,
        *,
        sessions: list[object] | None = None,
        socket_name: str | None = None,
        socket_path: pathlib.Path | None = None,
    ) -> None:
        self.sessions = sessions or []
        self.socket_name = socket_name
        self.socket_path = socket_path
        self.stdout = [
            FORMAT_SEPARATOR.join(
                [
                    "alpha",
                    "0",
                    "editor",
                    "tiled",
                    "1",
                    "0",
                    "1",
                    "vim",
                    "/workspace",
                ],
            ),
        ]
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def cmd(self, cmd: str, *args: object, **kwargs: object) -> _Cmd:
        """Record tmux commands."""
        self.calls.append((cmd, args, kwargs))
        return _Cmd(self.stdout if cmd == "list-panes" else [])


def test_should_autosave_without_previous_timestamp() -> None:
    """should_autosave() saves when there is no previous timestamp."""
    assert should_autosave(last_saved_at=None)


def test_should_autosave_after_interval_elapsed() -> None:
    """should_autosave() saves only after the interval has elapsed."""
    last_saved_at = datetime.datetime(
        2026,
        7,
        4,
        12,
        tzinfo=datetime.timezone.utc,
    )
    now = last_saved_at + DEFAULT_AUTOSAVE_INTERVAL

    assert should_autosave(last_saved_at=last_saved_at, now=now)
    assert not should_autosave(
        last_saved_at=last_saved_at,
        now=now - datetime.timedelta(seconds=1),
    )


def test_next_autosave_at_adds_interval() -> None:
    """next_autosave_at() returns the next due timestamp."""
    last_saved_at = datetime.datetime(
        2026,
        7,
        4,
        12,
        tzinfo=datetime.timezone.utc,
    )

    assert next_autosave_at(last_saved_at) == (
        last_saved_at + DEFAULT_AUTOSAVE_INTERVAL
    )
    assert next_autosave_at(None) is None


def test_read_write_autosave_state_round_trips(tmp_path: pathlib.Path) -> None:
    """write_autosave_state() persists state read_autosave_state() loads."""
    state_path = tmp_path / "state.json"
    state = AutosaveState(
        last_saved_at=datetime.datetime(
            2026,
            7,
            4,
            12,
            tzinfo=datetime.timezone.utc,
        ),
        last_archive_path=tmp_path / "archive.json",
        save_count=2,
    )

    assert write_autosave_state(state, state_path) == state_path
    assert read_autosave_state(state_path) == state


def test_default_autosave_paths_are_socket_aware(tmp_path: pathlib.Path) -> None:
    """default_autosave_paths() keeps independent tmux servers separate."""
    alpha = default_autosave_paths(
        t.cast("Server", _FakeServer(socket_name="alpha")),
        tmp_path,
    )
    beta = default_autosave_paths(
        t.cast("Server", _FakeServer(socket_name="beta")),
        tmp_path,
    )

    assert isinstance(alpha, AutosavePaths)
    assert alpha.archive_path.parent == tmp_path
    assert alpha.state_path.parent == tmp_path
    assert alpha.archive_path != alpha.state_path
    assert alpha.archive_path != beta.archive_path
    assert alpha.state_path != beta.state_path


def test_default_autosave_paths_hash_socket_paths(tmp_path: pathlib.Path) -> None:
    """default_autosave_paths() does not embed raw socket paths in filenames."""
    socket_path = pathlib.Path("/tmp/tmux-user/private.sock")

    paths = default_autosave_paths(
        t.cast("Server", _FakeServer(socket_path=socket_path)),
        tmp_path,
    )

    assert "private.sock" not in paths.archive_path.name
    assert "tmux-user" not in paths.archive_path.name
    assert paths.archive_path.suffix == ".json"
    assert paths.state_path.name.endswith(".state.json")


def test_autosave_once_skips_until_interval_elapses(tmp_path: pathlib.Path) -> None:
    """autosave_once() skips before the configured interval has elapsed."""
    now = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)
    state_path = tmp_path / "state.json"
    archive_path = tmp_path / "archive.json"
    write_autosave_state(
        AutosaveState(
            last_saved_at=now - datetime.timedelta(minutes=1),
            last_archive_path=archive_path,
            save_count=1,
        ),
        state_path,
    )
    server = _FakeServer()

    result = autosave_once(
        t.cast("Server", server),
        archive_path=archive_path,
        state_path=state_path,
        now=now,
    )

    assert not result.saved
    assert result.reason == "interval_not_elapsed"
    assert not archive_path.exists()
    assert server.calls == []


def test_autosave_once_writes_archive_and_state(tmp_path: pathlib.Path) -> None:
    """autosave_once() captures an archive and advances state when due."""
    now = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)
    state_path = tmp_path / "state.json"
    archive_path = tmp_path / "archive.json"
    server = _FakeServer()

    result = autosave_once(
        t.cast("Server", server),
        archive_path=archive_path,
        state_path=state_path,
        now=now,
    )

    assert result.saved
    assert result.reason == "saved"
    assert archive_path.exists()
    assert read_autosave_state(state_path) == AutosaveState(
        last_saved_at=now,
        last_archive_path=archive_path,
        save_count=1,
    )
    assert server.calls[0][0] == "list-panes"


def test_should_restore_on_startup_allows_fresh_opt_in_restore(
    tmp_path: pathlib.Path,
) -> None:
    """should_restore_on_startup() allows fresh, explicit startup restore."""
    now = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)

    decision = should_restore_on_startup(
        enabled=True,
        halt_file=tmp_path / "halt",
        session_count=0,
        another_server_running=False,
        tmux_started_at=now - datetime.timedelta(seconds=2),
        now=now,
    )

    assert decision == StartupRestoreDecision(allowed=True, reason="restore_allowed")


def test_should_restore_on_startup_reports_specific_vetoes(
    tmp_path: pathlib.Path,
) -> None:
    """should_restore_on_startup() reports why restore is skipped."""
    now = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)
    halt_file = tmp_path / "halt"
    halt_file.write_text("", encoding="utf-8")

    assert (
        should_restore_on_startup(
            enabled=False,
            halt_file=tmp_path / "missing",
            session_count=0,
            another_server_running=False,
            tmux_started_at=now,
            now=now,
        ).reason
        == "restore_disabled"
    )
    assert (
        should_restore_on_startup(
            enabled=True,
            halt_file=halt_file,
            session_count=0,
            another_server_running=False,
            tmux_started_at=now,
            now=now,
        ).reason
        == "halt_file_present"
    )
    assert (
        should_restore_on_startup(
            enabled=True,
            halt_file=None,
            session_count=0,
            another_server_running=True,
            tmux_started_at=now,
            now=now,
        ).reason
        == "another_server_running"
    )
    assert (
        should_restore_on_startup(
            enabled=True,
            halt_file=None,
            session_count=1,
            another_server_running=False,
            tmux_started_at=now,
            now=now,
        ).reason
        == "sessions_exist"
    )
    assert (
        should_restore_on_startup(
            enabled=True,
            halt_file=None,
            session_count=0,
            another_server_running=False,
            tmux_started_at=now - datetime.timedelta(minutes=1),
            now=now,
        ).reason
        == "startup_window_elapsed"
    )


def test_startup_restore_once_restores_when_allowed(
    tmp_path: pathlib.Path,
) -> None:
    """startup_restore_once() restores only after startup guards pass."""
    now = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)
    archive_path = tmp_path / "workspace.json"
    write_archive(WorkspaceArchive(saved_at=now, sessions=()), archive_path)

    result = startup_restore_once(
        t.cast("Server", _FakeServer()),
        archive_path,
        enabled=True,
        tmux_started_at=now,
        now=now,
    )

    assert result.restored
    assert result.reason == "restored"
    assert result.decision == StartupRestoreDecision(
        allowed=True,
        reason="restore_allowed",
    )


def test_startup_restore_once_skips_when_guard_vetoes(
    tmp_path: pathlib.Path,
) -> None:
    """startup_restore_once() returns the guard reason without reading archive."""
    result = startup_restore_once(
        t.cast("Server", _FakeServer(sessions=[object()])),
        tmp_path / "missing.json",
        enabled=True,
    )

    assert not result.restored
    assert result.reason == "sessions_exist"
