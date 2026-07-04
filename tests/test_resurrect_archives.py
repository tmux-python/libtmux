"""Tests for tmux-resurrect style workspace archives."""

from __future__ import annotations

import datetime
import pathlib
import typing as t

from libtmux.formats import FORMAT_SEPARATOR
from libtmux.resurrect.archives import (
    PaneArchive,
    SessionArchive,
    WindowArchive,
    WorkspaceArchive,
    capture_archive,
    read_archive,
    restore_archive,
    write_archive,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server


class _Cmd:
    """Small command result test double."""

    def __init__(self, stdout: list[str] | None = None) -> None:
        self.stdout = stdout or []
        self.stderr: list[str] = []
        self.returncode = 0


class _FakePane:
    """Pane double used by restore tests."""

    def __init__(self, calls: list[tuple[str, tuple[object, ...], dict[str, object]]]):
        self._calls = calls

    def split(
        self,
        *,
        start_directory: str | None = None,
        shell: str | None = None,
        attach: bool = False,
    ) -> _FakePane:
        """Record pane splits."""
        self._calls.append(
            (
                "pane.split",
                (),
                {
                    "attach": attach,
                    "shell": shell,
                    "start_directory": start_directory,
                },
            ),
        )
        return _FakePane(self._calls)


class _FakeWindow:
    """Window double used by restore tests."""

    def __init__(
        self,
        calls: list[tuple[str, tuple[object, ...], dict[str, object]]],
        *,
        window_index: str = "0",
    ) -> None:
        self._calls = calls
        self.window_index = window_index
        self.active_pane = _FakePane(calls)

    def split(
        self,
        *,
        start_directory: str | None = None,
        shell: str | None = None,
        attach: bool = False,
    ) -> _FakePane:
        """Record window splits."""
        self._calls.append(
            (
                "window.split",
                (),
                {
                    "attach": attach,
                    "shell": shell,
                    "start_directory": start_directory,
                },
            ),
        )
        return _FakePane(self._calls)

    def select_layout(self, layout: str) -> _FakeWindow:
        """Record layout selection."""
        self._calls.append(("window.select_layout", (layout,), {}))
        return self


class _FakeSession:
    """Session double used by restore tests."""

    def __init__(
        self,
        calls: list[tuple[str, tuple[object, ...], dict[str, object]]],
    ) -> None:
        self._calls = calls
        self.active_window = _FakeWindow(calls)

    def new_window(
        self,
        *,
        window_name: str | None = None,
        start_directory: str | None = None,
        window_index: str = "",
        window_shell: str | None = None,
        attach: bool = False,
    ) -> _FakeWindow:
        """Record window creation."""
        self._calls.append(
            (
                "session.new_window",
                (),
                {
                    "attach": attach,
                    "start_directory": start_directory,
                    "window_index": window_index,
                    "window_name": window_name,
                    "window_shell": window_shell,
                },
            ),
        )
        return _FakeWindow(self._calls, window_index=window_index)

    def select_window(self, target_window: str | int) -> _FakeWindow:
        """Record active window selection."""
        self._calls.append(("session.select_window", (target_window,), {}))
        return _FakeWindow(self._calls, window_index=str(target_window))


class _FakeServer:
    """Server double used by archive tests."""

    def __init__(self, stdout: list[str] | None = None) -> None:
        self.stdout = stdout or []
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.existing_sessions: set[str] = set()

    def cmd(self, cmd: str, *args: object, **kwargs: object) -> _Cmd:
        """Record tmux commands."""
        self.calls.append((cmd, args, kwargs))
        return _Cmd(self.stdout if cmd == "list-panes" else [])

    def has_session(self, target_session: str) -> bool:
        """Return configured session existence."""
        self.calls.append(("has_session", (target_session,), {}))
        return target_session in self.existing_sessions

    def new_session(
        self,
        *,
        session_name: str | None = None,
        start_directory: str | None = None,
        window_name: str | None = None,
        window_command: str | None = None,
    ) -> _FakeSession:
        """Record session creation."""
        self.calls.append(
            (
                "new_session",
                (),
                {
                    "session_name": session_name,
                    "start_directory": start_directory,
                    "window_command": window_command,
                    "window_name": window_name,
                },
            ),
        )
        return _FakeSession(self.calls)


def test_capture_archive_groups_tmux_pane_rows() -> None:
    """capture_archive() groups list-panes rows by session and window."""
    saved_at = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)
    server = _FakeServer(
        [
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
            FORMAT_SEPARATOR.join(
                [
                    "alpha",
                    "0",
                    "editor",
                    "tiled",
                    "1",
                    "1",
                    "0",
                    "bash",
                    "/workspace",
                ],
            ),
        ],
    )

    archive = capture_archive(t.cast("Server", server), saved_at=saved_at)

    assert archive.saved_at == saved_at
    assert len(archive.sessions) == 1
    assert archive.sessions[0].name == "alpha"
    assert archive.sessions[0].windows[0].name == "editor"
    assert archive.sessions[0].windows[0].panes == (
        PaneArchive(
            index=0,
            active=True,
            current_command="vim",
            current_path="/workspace",
        ),
        PaneArchive(
            index=1,
            active=False,
            current_command="bash",
            current_path="/workspace",
        ),
    )
    assert server.calls[0][0] == "list-panes"


def test_capture_archive_records_captured_capabilities() -> None:
    """capture_archive() declares the parity features captured in the archive."""
    archive = capture_archive(t.cast("Server", _FakeServer()))

    assert archive.capabilities == (
        "sessions",
        "windows",
        "panes",
        "window-order",
        "pane-order",
        "working-directories",
        "layouts",
        "active-windows",
        "active-panes",
        "pane-current-command",
    )


def test_capture_archive_uses_configured_libtmux_separator() -> None:
    """capture_archive() uses a tmux-version-safe separator."""
    server = _FakeServer()

    capture_archive(t.cast("Server", server))

    format_arg = server.calls[0][1][2]
    assert isinstance(format_arg, str)
    assert server.calls == [("list-panes", ("-a", "-F", format_arg), {})]
    assert FORMAT_SEPARATOR in format_arg
    if FORMAT_SEPARATOR != "\x1f":
        assert "\x1f" not in format_arg


def test_capture_archive_accepts_trailing_format_separator() -> None:
    """capture_archive() accepts the output shape used by neo format strings."""
    saved_at = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)
    server = _FakeServer(
        [
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
                    "",
                ],
            ),
        ],
    )

    archive = capture_archive(t.cast("Server", server), saved_at=saved_at)

    assert archive.sessions[0].windows[0].panes == (
        PaneArchive(
            index=0,
            active=True,
            current_command="vim",
            current_path="/workspace",
        ),
    )


def test_write_read_archive_round_trips_json(tmp_path: pathlib.Path) -> None:
    """write_archive() persists JSON that read_archive() loads back."""
    archive = WorkspaceArchive(
        saved_at=datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc),
        sessions=(
            SessionArchive(
                name="alpha",
                windows=(
                    WindowArchive(
                        index=0,
                        name="editor",
                        layout="tiled",
                        active=True,
                        panes=(
                            PaneArchive(
                                index=0,
                                active=True,
                                current_command="vim",
                                current_path="/workspace",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    archive_path = tmp_path / "workspace.json"

    assert write_archive(archive, archive_path) == archive_path
    assert read_archive(archive_path) == archive


def test_restore_archive_recreates_windows_panes_and_layout() -> None:
    """restore_archive() recreates sessions, windows, panes, and selections."""
    archive = WorkspaceArchive(
        saved_at=datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc),
        sessions=(
            SessionArchive(
                name="alpha",
                windows=(
                    WindowArchive(
                        index=0,
                        name="editor",
                        layout="tiled",
                        active=False,
                        panes=(
                            PaneArchive(
                                index=0,
                                active=True,
                                current_command="vim",
                                current_path="/workspace",
                            ),
                            PaneArchive(
                                index=1,
                                active=False,
                                current_command="bash",
                                current_path="/workspace",
                            ),
                        ),
                    ),
                    WindowArchive(
                        index=2,
                        name="logs",
                        layout="even-horizontal",
                        active=True,
                        panes=(
                            PaneArchive(
                                index=0,
                                active=True,
                                current_command="tail",
                                current_path="/logs",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    server = _FakeServer()

    restored = restore_archive(archive, t.cast("Server", server))

    assert len(restored) == 1
    assert (
        "new_session",
        (),
        {
            "session_name": "alpha",
            "start_directory": "/workspace",
            "window_command": "vim",
            "window_name": "editor",
        },
    ) in server.calls
    assert (
        "window.split",
        (),
        {
            "attach": False,
            "shell": None,
            "start_directory": "/workspace",
        },
    ) in server.calls
    assert (
        "session.new_window",
        (),
        {
            "attach": False,
            "start_directory": "/logs",
            "window_index": "2",
            "window_name": "logs",
            "window_shell": "tail",
        },
    ) in server.calls
    assert ("window.select_layout", ("tiled",), {}) in server.calls
    assert ("window.select_layout", ("even-horizontal",), {}) in server.calls
    assert ("select-pane", (), {"target": "alpha:0.0"}) in server.calls
    assert ("session.select_window", (2,), {}) in server.calls
