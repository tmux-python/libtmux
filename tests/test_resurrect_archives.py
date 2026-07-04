"""Tests for tmux-resurrect style workspace archives."""

from __future__ import annotations

import datetime
import pathlib
import typing as t

import pytest

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
from libtmux.resurrect.processes import ProcessRestorePolicy

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

    def __init__(
        self,
        stdout: list[str] | None = None,
        stdout_by_cmd: dict[str, list[str]] | None = None,
    ) -> None:
        self.stdout = stdout or []
        self.stdout_by_cmd = stdout_by_cmd or {}
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.existing_sessions: set[str] = set()

    def cmd(self, cmd: str, *args: object, **kwargs: object) -> _Cmd:
        """Record tmux commands."""
        self.calls.append((cmd, args, kwargs))
        if cmd == "new-session":
            session_name = _arg_after(args, "-s")
            if session_name is not None:
                self.existing_sessions.add(session_name)
        if cmd in self.stdout_by_cmd:
            return _Cmd(self.stdout_by_cmd[cmd])
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
        if session_name is not None:
            self.existing_sessions.add(session_name)
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


class _ProcessProvider:
    """Process command provider test double."""

    def __init__(self, commands: dict[int, str]) -> None:
        self.commands = commands
        self.captured_pids: list[int] = []

    def capture(self, pid: int) -> str | None:
        """Record pid capture and return a configured command."""
        self.captured_pids.append(pid)
        return self.commands.get(pid)


class RestoreReuseMissingWindowCase(t.NamedTuple):
    """Case for restoring an archived window missing from a reused session."""

    test_id: str
    panes: tuple[PaneArchive, ...]
    expected_split_count: int
    expected_active_target: str


RESTORE_REUSE_MISSING_WINDOW_CASES = (
    RestoreReuseMissingWindowCase(
        test_id="single_pane",
        panes=(
            PaneArchive(
                index=0,
                active=True,
                current_command="tail",
                current_path="/logs",
                title="main",
            ),
        ),
        expected_split_count=0,
        expected_active_target="alpha:2.0",
    ),
    RestoreReuseMissingWindowCase(
        test_id="multi_pane",
        panes=(
            PaneArchive(
                index=0,
                active=False,
                current_command="tail",
                current_path="/logs",
                title="main",
            ),
            PaneArchive(
                index=1,
                active=True,
                current_command="less",
                current_path="/logs",
                full_command="less error.log",
                title="secondary",
            ),
        ),
        expected_split_count=1,
        expected_active_target="alpha:2.1",
    ),
)


def _arg_after(args: tuple[object, ...], flag: str) -> str | None:
    try:
        value = args[args.index(flag) + 1]
    except (ValueError, IndexError):
        return None
    return str(value)


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
        "pane-full-command",
        "pane-titles",
        "window-flags",
        "automatic-rename",
        "grouped-sessions",
        "alternate-windows",
        "active-sessions",
        "alternate-sessions",
        "history-size",
    )


def test_capture_archive_uses_configured_libtmux_separator() -> None:
    """capture_archive() uses a tmux-version-safe separator."""
    server = _FakeServer()

    capture_archive(t.cast("Server", server))

    format_arg = server.calls[0][1][2]
    assert isinstance(format_arg, str)
    assert server.calls[0] == ("list-panes", ("-a", "-F", format_arg), {})
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


def test_capture_archive_records_focus_and_window_metadata() -> None:
    """capture_archive() records focus, grouping, pane, and window metadata."""
    saved_at = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)
    server = _FakeServer(
        stdout_by_cmd={
            "list-clients": [
                FORMAT_SEPARATOR.join(["alpha", "beta", ""]),
            ],
            "list-panes": [
                FORMAT_SEPARATOR.join(
                    [
                        "alpha",
                        "1",
                        "editor",
                        "tiled",
                        "1",
                        "*Z",
                        "0",
                        "1",
                        "vim",
                        "/workspace",
                        "src",
                        "42",
                        "",
                    ],
                ),
            ],
            "list-sessions": [
                FORMAT_SEPARATOR.join(["alpha", "1", "work", ""]),
            ],
            "show-window-options": ["off"],
        },
    )

    archive = capture_archive(t.cast("Server", server), saved_at=saved_at)

    assert archive.active_session_name == "alpha"
    assert archive.alternate_session_name == "beta"
    session = archive.sessions[0]
    assert session.group_name == "work"
    assert session.active_window_index == 1
    assert session.alternate_window_index is None
    window = session.windows[0]
    assert window.flags == "*Z"
    assert window.automatic_rename is False
    pane = window.panes[0]
    assert pane.title == "src"
    assert pane.history_size == 42


def test_capture_archive_uses_process_command_provider() -> None:
    """capture_archive() records provider-supplied full process commands."""
    saved_at = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)
    provider = _ProcessProvider({123: "vim pyproject.toml"})
    server = _FakeServer(
        stdout_by_cmd={
            "list-panes": [
                FORMAT_SEPARATOR.join(
                    [
                        "alpha",
                        "0",
                        "editor",
                        "tiled",
                        "1",
                        "*",
                        "0",
                        "1",
                        "123",
                        "vim",
                        "/workspace",
                        "src",
                        "42",
                        "",
                    ],
                ),
            ],
        },
    )

    archive = capture_archive(
        t.cast("Server", server),
        process_provider=provider,
        saved_at=saved_at,
    )

    pane = archive.sessions[0].windows[0].panes[0]
    assert pane.full_command == "vim pyproject.toml"
    assert provider.captured_pids == [123]


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


def test_read_archive_accepts_existing_minimal_json(tmp_path: pathlib.Path) -> None:
    """read_archive() remains compatible with pre-parity archive JSON."""
    archive_path = tmp_path / "minimal.json"
    archive_path.write_text(
        """{
  "capabilities": [
    "sessions",
    "windows",
    "panes"
  ],
  "format_version": "libtmux.resurrect.archive.v1",
  "saved_at": "2026-07-04T12:00:00+00:00",
  "sessions": [
    {
      "name": "alpha",
      "windows": [
        {
          "active": true,
          "index": 0,
          "layout": "tiled",
          "name": "editor",
          "panes": [
            {
              "active": true,
              "current_command": "vim",
              "current_path": "/workspace",
              "index": 0
            }
          ]
        }
      ]
    }
  ]
}
""",
        encoding="utf-8",
    )

    archive = read_archive(archive_path)

    assert archive.active_session_name is None
    assert archive.alternate_session_name is None
    assert archive.sessions[0].group_name is None
    assert archive.sessions[0].active_window_index is None
    assert archive.sessions[0].alternate_window_index is None
    assert archive.sessions[0].windows[0].flags == ""
    assert archive.sessions[0].windows[0].automatic_rename is None
    assert archive.sessions[0].windows[0].panes[0].title == ""
    assert archive.sessions[0].windows[0].panes[0].full_command == ""
    assert archive.sessions[0].windows[0].panes[0].history_size == 0
    assert archive.sessions[0].windows[0].panes[0].contents == ()


def test_write_read_archive_preserves_extended_metadata(
    tmp_path: pathlib.Path,
) -> None:
    """write_archive() persists the richer parity metadata."""
    archive = WorkspaceArchive(
        saved_at=datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc),
        active_session_name="alpha",
        alternate_session_name="beta",
        sessions=(
            SessionArchive(
                name="alpha",
                group_name="work",
                active_window_index=1,
                alternate_window_index=0,
                windows=(
                    WindowArchive(
                        index=1,
                        name="editor",
                        layout="tiled",
                        active=True,
                        flags="*Z",
                        automatic_rename=False,
                        panes=(
                            PaneArchive(
                                index=0,
                                active=True,
                                current_command="vim",
                                current_path="/workspace",
                                title="src",
                                full_command="vim pyproject.toml",
                                history_size=42,
                                contents=("hello", "world"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    archive_path = tmp_path / "extended.json"

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


def test_restore_archive_reuses_existing_topology() -> None:
    """restore_archive(on_exists='reuse') creates only missing topology."""
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
                        active=False,
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
    server = _FakeServer(
        stdout_by_cmd={
            "list-panes": ["0"],
            "list-windows": ["0"],
        },
    )
    server.existing_sessions.add("alpha")

    assert restore_archive(archive, t.cast("Server", server), on_exists="reuse") == []

    assert not any(call[0] == "new_session" for call in server.calls)
    assert [call[0] for call in server.calls].count("new-window") == 1
    assert [call[0] for call in server.calls].count("split-window") == 1
    assert (
        "new-window",
        ("-d", "-t", "alpha:2", "-n", "logs", "-c", "/logs", "tail"),
        {},
    ) in server.calls
    assert (
        "split-window",
        ("-d", "-t", "alpha:0", "-c", "/workspace"),
        {},
    ) in server.calls


@pytest.mark.parametrize(
    "case",
    RESTORE_REUSE_MISSING_WINDOW_CASES,
    ids=[case.test_id for case in RESTORE_REUSE_MISSING_WINDOW_CASES],
)
def test_restore_archive_reuses_missing_window_state(
    case: RestoreReuseMissingWindowCase,
) -> None:
    """restore_archive(on_exists='reuse') restores newly created window state."""
    archive = WorkspaceArchive(
        saved_at=datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc),
        sessions=(
            SessionArchive(
                name="alpha",
                windows=(
                    WindowArchive(
                        index=2,
                        name="logs",
                        layout="even-horizontal",
                        active=True,
                        automatic_rename=False,
                        panes=case.panes,
                    ),
                ),
            ),
        ),
    )
    server = _FakeServer(stdout_by_cmd={"list-windows": ["0"]})
    server.existing_sessions.add("alpha")

    assert restore_archive(archive, t.cast("Server", server), on_exists="reuse") == []

    assert (
        "new-window",
        ("-d", "-t", "alpha:2", "-n", "logs", "-c", "/logs", "tail"),
        {},
    ) in server.calls
    assert (
        len(
            [
                call
                for call in server.calls
                if call[0] == "split-window" and call[1][0:3] == ("-d", "-t", "alpha:2")
            ],
        )
        == case.expected_split_count
    )
    assert (
        "select-layout",
        ("-t", "alpha:2", "even-horizontal"),
        {},
    ) in server.calls
    assert (
        "set-window-option",
        ("-t", "alpha:2", "automatic-rename", "off"),
        {},
    ) in server.calls
    for pane in case.panes:
        assert (
            "select-pane",
            ("-T", pane.title),
            {"target": f"alpha:2.{pane.index}"},
        ) in server.calls
    assert ("select-pane", (), {"target": case.expected_active_target}) in server.calls


def test_restore_archive_uses_process_restore_policy() -> None:
    """restore_archive() only replays pane commands allowed by policy."""
    archive = WorkspaceArchive(
        saved_at=datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc),
        sessions=(
            SessionArchive(
                name="alpha",
                windows=(
                    WindowArchive(
                        index=0,
                        name="server",
                        layout="",
                        active=True,
                        panes=(
                            PaneArchive(
                                index=0,
                                active=True,
                                current_command="node",
                                current_path="/workspace",
                                full_command="node server.js",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    default_server = _FakeServer()
    all_server = _FakeServer()

    restore_archive(archive, t.cast("Server", default_server))
    restore_archive(
        archive,
        t.cast("Server", all_server),
        process_policy=ProcessRestorePolicy.from_options(":all:"),
    )

    assert (
        "new_session",
        (),
        {
            "session_name": "alpha",
            "start_directory": "/workspace",
            "window_command": None,
            "window_name": "server",
        },
    ) in default_server.calls
    assert (
        "new_session",
        (),
        {
            "session_name": "alpha",
            "start_directory": "/workspace",
            "window_command": "node server.js",
            "window_name": "server",
        },
    ) in all_server.calls


def test_restore_archive_replays_focus_and_window_metadata() -> None:
    """restore_archive() replays focus, title, zoom, and window option metadata."""
    archive = WorkspaceArchive(
        saved_at=datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc),
        active_session_name="alpha",
        alternate_session_name="beta",
        sessions=(
            SessionArchive(
                name="alpha",
                active_window_index=2,
                alternate_window_index=0,
                windows=(
                    WindowArchive(
                        index=0,
                        name="editor",
                        layout="tiled",
                        active=False,
                        flags="-",
                        automatic_rename=True,
                        panes=(
                            PaneArchive(
                                index=0,
                                active=True,
                                current_command="vim",
                                current_path="/workspace",
                                title="src",
                            ),
                        ),
                    ),
                    WindowArchive(
                        index=2,
                        name="logs",
                        layout="even-horizontal",
                        active=True,
                        flags="*Z",
                        automatic_rename=False,
                        panes=(
                            PaneArchive(
                                index=0,
                                active=True,
                                current_command="tail",
                                current_path="/logs",
                                title="log",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    server = _FakeServer()

    restore_archive(archive, t.cast("Server", server))

    assert (
        "set-window-option",
        ("-t", "alpha:0", "automatic-rename", "on"),
        {},
    ) in server.calls
    assert (
        "set-window-option",
        ("-t", "alpha:2", "automatic-rename", "off"),
        {},
    ) in server.calls
    assert ("select-pane", ("-T", "src"), {"target": "alpha:0.0"}) in server.calls
    assert ("select-pane", ("-T", "log"), {"target": "alpha:2.0"}) in server.calls
    assert ("resize-pane", ("-Z",), {"target": "alpha:2"}) in server.calls
    assert ("select-window", ("-t", "alpha:0"), {}) in server.calls
    assert ("session.select_window", (2,), {}) in server.calls
    assert ("switch-client", ("-t", "beta"), {}) in server.calls
    assert ("switch-client", ("-t", "alpha"), {}) in server.calls


def test_restore_archive_recreates_grouped_sessions_once() -> None:
    """restore_archive() recreates grouped sessions without duplicating windows."""
    windows = (
        WindowArchive(
            index=1,
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
    )
    archive = WorkspaceArchive(
        saved_at=datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc),
        sessions=(
            SessionArchive(
                name="alpha",
                group_name="shared",
                active_window_index=1,
                windows=windows,
            ),
            SessionArchive(
                name="beta",
                group_name="shared",
                active_window_index=1,
                windows=windows,
            ),
        ),
    )
    server = _FakeServer()

    restore_archive(archive, t.cast("Server", server))

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
    assert ("new-session", ("-d", "-s", "beta", "-t", "alpha"), {}) in server.calls
    assert ("session.select_window", (1,), {}) in server.calls
    assert ("select-window", ("-t", "beta:1"), {}) in server.calls
    assert [
        call
        for call in server.calls
        if call[0] in {"new_session", "session.new_window"}
    ] == [
        (
            "new_session",
            (),
            {
                "session_name": "alpha",
                "start_directory": "/workspace",
                "window_command": "vim",
                "window_name": "editor",
            },
        ),
    ]
