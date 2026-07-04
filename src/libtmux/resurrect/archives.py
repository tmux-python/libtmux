"""Pure Python tmux workspace archive helpers.

This module intentionally does not depend on tmux plugin manager state. It
captures tmux state through the libtmux ``Server`` API and stores a typed JSON
archive that can be restored headlessly.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import typing as t
from dataclasses import dataclass

from libtmux._internal.types import StrPath
from libtmux.common import raise_if_stderr

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

FORMAT_VERSION = "libtmux.resurrect.archive.v1"
"""Archive format identifier."""

DEFAULT_SHELL_COMMANDS = frozenset({"bash", "dash", "fish", "ksh", "sh", "zsh"})
"""Commands treated as shells during restore."""

RestorePolicy: t.TypeAlias = t.Literal["error", "replace", "reuse"]
"""How restore handles sessions that already exist."""

_FIELD_SEPARATOR = "\x1f"
_PANE_FORMAT = _FIELD_SEPARATOR.join(
    (
        "#{session_name}",
        "#{window_index}",
        "#{window_name}",
        "#{window_layout}",
        "#{window_active}",
        "#{pane_index}",
        "#{pane_active}",
        "#{pane_current_command}",
        "#{pane_current_path}",
    ),
)


@dataclass(frozen=True, slots=True)
class PaneArchive:
    """Serialized tmux pane state."""

    index: int
    active: bool
    current_command: str
    current_path: str


@dataclass(frozen=True, slots=True)
class WindowArchive:
    """Serialized tmux window state."""

    index: int
    name: str
    layout: str
    active: bool
    panes: tuple[PaneArchive, ...]


@dataclass(frozen=True, slots=True)
class SessionArchive:
    """Serialized tmux session state."""

    name: str
    windows: tuple[WindowArchive, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceArchive:
    """Serialized tmux workspace state."""

    saved_at: datetime.datetime
    sessions: tuple[SessionArchive, ...]
    format_version: str = FORMAT_VERSION


@dataclass(frozen=True, slots=True)
class _PaneRow:
    """Flattened list-panes row before grouping."""

    session_name: str
    window_index: int
    window_name: str
    window_layout: str
    window_active: bool
    pane_index: int
    pane_active: bool
    pane_current_command: str
    pane_current_path: str


def capture_archive(
    server: Server,
    *,
    saved_at: datetime.datetime | None = None,
) -> WorkspaceArchive:
    """Capture all panes from a tmux server into a workspace archive.

    Examples
    --------
    >>> archive = capture_archive(server)
    >>> archive.format_version
    'libtmux.resurrect.archive.v1'
    """
    proc = server.cmd("list-panes", "-a", "-F", _PANE_FORMAT)
    raise_if_stderr(proc, "list-panes")

    rows = tuple(_parse_pane_row(line) for line in proc.stdout)
    return _archive_from_rows(rows, saved_at=saved_at)


def write_archive(archive: WorkspaceArchive, path: StrPath) -> pathlib.Path:
    """Write an archive as stable JSON using an atomic replace.

    Examples
    --------
    >>> import pathlib
    >>> target = pathlib.Path(request.getfixturevalue("tmp_path")) / "tmux.json"
    >>> saved = write_archive(capture_archive(server), target)
    >>> saved == target
    True
    """
    destination = pathlib.Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        json.dumps(_archive_to_dict(archive), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(destination)
    return destination


def read_archive(path: StrPath) -> WorkspaceArchive:
    """Read an archive written by :func:`write_archive`.

    Examples
    --------
    >>> import pathlib
    >>> target = pathlib.Path(request.getfixturevalue("tmp_path")) / "tmux.json"
    >>> _ = write_archive(capture_archive(server), target)
    >>> read_archive(target).format_version
    'libtmux.resurrect.archive.v1'
    """
    source = pathlib.Path(path)
    return _archive_from_dict(json.loads(source.read_text(encoding="utf-8")))


def restore_archive(
    archive: WorkspaceArchive | StrPath,
    server: Server,
    *,
    on_exists: RestorePolicy = "error",
    shell_commands: t.Collection[str] = DEFAULT_SHELL_COMMANDS,
) -> list[Session]:
    """Restore sessions from an archive into a tmux server.

    Shell panes are recreated at their recorded working directory. Non-shell
    panes are started with their recorded command.

    Examples
    --------
    >>> archive = capture_archive(server)
    >>> restored = restore_archive(archive, server, on_exists="replace")
    >>> isinstance(restored, list)
    True
    """
    if on_exists not in {"error", "replace", "reuse"}:
        msg = f"unknown restore policy: {on_exists!r}"
        raise ValueError(msg)

    resolved_archive = (
        archive if isinstance(archive, WorkspaceArchive) else read_archive(archive)
    )
    sessions: list[Session] = []

    for session_archive in resolved_archive.sessions:
        if server.has_session(session_archive.name):
            if on_exists == "reuse":
                continue
            if on_exists == "error":
                msg = f"session already exists: {session_archive.name}"
                raise FileExistsError(msg)
            proc = server.cmd("kill-session", target=session_archive.name)
            raise_if_stderr(proc, "kill-session")

        sessions.append(
            _restore_session(
                server,
                session_archive,
                shell_commands=shell_commands,
            ),
        )

    return sessions


def _archive_from_rows(
    rows: tuple[_PaneRow, ...],
    *,
    saved_at: datetime.datetime | None = None,
) -> WorkspaceArchive:
    grouped: dict[str, dict[int, list[_PaneRow]]] = {}
    for row in sorted(rows, key=lambda item: (item.session_name, item.window_index)):
        grouped.setdefault(row.session_name, {}).setdefault(
            row.window_index, []
        ).append(
            row,
        )

    sessions: list[SessionArchive] = []
    for session_name, windows_by_index in grouped.items():
        windows: list[WindowArchive] = []
        for window_index, pane_rows in sorted(windows_by_index.items()):
            first = pane_rows[0]
            panes = tuple(
                PaneArchive(
                    index=row.pane_index,
                    active=row.pane_active,
                    current_command=row.pane_current_command,
                    current_path=row.pane_current_path,
                )
                for row in sorted(pane_rows, key=lambda item: item.pane_index)
            )
            windows.append(
                WindowArchive(
                    index=window_index,
                    name=first.window_name,
                    layout=first.window_layout,
                    active=first.window_active,
                    panes=panes,
                ),
            )
        sessions.append(SessionArchive(name=session_name, windows=tuple(windows)))

    return WorkspaceArchive(
        saved_at=_coerce_saved_at(saved_at),
        sessions=tuple(sessions),
    )


def _restore_session(
    server: Server,
    session_archive: SessionArchive,
    *,
    shell_commands: t.Collection[str],
) -> Session:
    first_window = session_archive.windows[0] if session_archive.windows else None
    first_pane = first_window.panes[0] if first_window and first_window.panes else None

    session = server.new_session(
        session_name=session_archive.name,
        start_directory=_pane_path(first_pane),
        window_name=_name_or_none(first_window.name) if first_window else None,
        window_command=_pane_command(first_pane, shell_commands=shell_commands),
    )

    if first_window is not None:
        active_window = session.active_window
        _move_initial_window(
            server,
            session_archive=session_archive,
            window=active_window,
            window_archive=first_window,
        )
        _restore_window(
            server,
            session_archive=session_archive,
            window=active_window,
            window_archive=first_window,
            shell_commands=shell_commands,
            skip_first_pane=True,
        )

    for window_archive in session_archive.windows[1:]:
        first_window_pane = window_archive.panes[0] if window_archive.panes else None
        window = session.new_window(
            window_name=_name_or_none(window_archive.name),
            start_directory=_pane_path(first_window_pane),
            window_index=str(window_archive.index),
            window_shell=_pane_command(
                first_window_pane,
                shell_commands=shell_commands,
            ),
            attach=False,
        )
        _restore_window(
            server,
            session_archive=session_archive,
            window=window,
            window_archive=window_archive,
            shell_commands=shell_commands,
            skip_first_pane=True,
        )

    active_window_archive = _active_window(session_archive)
    if active_window_archive is not None:
        session.select_window(active_window_archive.index)

    return session


def _restore_window(
    server: Server,
    *,
    session_archive: SessionArchive,
    window: Window,
    window_archive: WindowArchive,
    shell_commands: t.Collection[str],
    skip_first_pane: bool,
) -> None:
    pane_archives = (
        window_archive.panes[1:] if skip_first_pane else window_archive.panes
    )
    for pane_archive in pane_archives:
        window.split(
            start_directory=_path_or_none(pane_archive.current_path),
            shell=_pane_command(pane_archive, shell_commands=shell_commands),
            attach=pane_archive.active,
        )

    if window_archive.layout:
        window.select_layout(window_archive.layout)

    active_pane_archive = _active_pane(window_archive)
    if active_pane_archive is not None:
        proc = server.cmd(
            "select-pane",
            target=(
                f"{session_archive.name}:"
                f"{window_archive.index}.{active_pane_archive.index}"
            ),
        )
        raise_if_stderr(proc, "select-pane")


def _move_initial_window(
    server: Server,
    *,
    session_archive: SessionArchive,
    window: Window,
    window_archive: WindowArchive,
) -> None:
    current_index = str(window.window_index)
    if current_index == str(window_archive.index):
        return

    proc = server.cmd(
        "move-window",
        "-s",
        f"{session_archive.name}:{current_index}",
        "-t",
        f"{session_archive.name}:{window_archive.index}",
    )
    raise_if_stderr(proc, "move-window")


def _active_window(session: SessionArchive) -> WindowArchive | None:
    return next((window for window in session.windows if window.active), None)


def _active_pane(window: WindowArchive) -> PaneArchive | None:
    return next((pane for pane in window.panes if pane.active), None)


def _pane_path(pane: PaneArchive | None) -> str | None:
    if pane is None:
        return None
    return _path_or_none(pane.current_path)


def _path_or_none(path: str) -> str | None:
    return path or None


def _name_or_none(name: str) -> str | None:
    return name or None


def _pane_command(
    pane: PaneArchive | None,
    *,
    shell_commands: t.Collection[str],
) -> str | None:
    if pane is None:
        return None
    if not pane.current_command or pane.current_command in shell_commands:
        return None
    return pane.current_command


def _parse_pane_row(row: str) -> _PaneRow:
    parts = row.split(_FIELD_SEPARATOR)
    if len(parts) != 9:
        msg = f"expected 9 list-panes fields, got {len(parts)}"
        raise ValueError(msg)

    return _PaneRow(
        session_name=parts[0],
        window_index=int(parts[1]),
        window_name=parts[2],
        window_layout=parts[3],
        window_active=_tmux_bool(parts[4]),
        pane_index=int(parts[5]),
        pane_active=_tmux_bool(parts[6]),
        pane_current_command=parts[7],
        pane_current_path=parts[8],
    )


def _tmux_bool(value: str) -> bool:
    return value == "1"


def _coerce_saved_at(value: datetime.datetime | None) -> datetime.datetime:
    if value is None:
        return datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _archive_to_dict(archive: WorkspaceArchive) -> dict[str, object]:
    return {
        "format_version": archive.format_version,
        "saved_at": _coerce_saved_at(archive.saved_at).isoformat(),
        "sessions": [
            {
                "name": session.name,
                "windows": [
                    {
                        "active": window.active,
                        "index": window.index,
                        "layout": window.layout,
                        "name": window.name,
                        "panes": [
                            {
                                "active": pane.active,
                                "current_command": pane.current_command,
                                "current_path": pane.current_path,
                                "index": pane.index,
                            }
                            for pane in window.panes
                        ],
                    }
                    for window in session.windows
                ],
            }
            for session in archive.sessions
        ],
    }


def _archive_from_dict(data: object) -> WorkspaceArchive:
    archive_data = _expect_mapping(data, "archive")
    format_version = _expect_str(archive_data, "format_version")
    if format_version != FORMAT_VERSION:
        msg = f"unsupported archive format: {format_version}"
        raise ValueError(msg)

    return WorkspaceArchive(
        format_version=format_version,
        saved_at=datetime.datetime.fromisoformat(_expect_str(archive_data, "saved_at")),
        sessions=tuple(
            _session_from_dict(session)
            for session in _expect_list(archive_data, "sessions")
        ),
    )


def _session_from_dict(data: object) -> SessionArchive:
    session_data = _expect_mapping(data, "session")
    return SessionArchive(
        name=_expect_str(session_data, "name"),
        windows=tuple(
            _window_from_dict(window)
            for window in _expect_list(session_data, "windows")
        ),
    )


def _window_from_dict(data: object) -> WindowArchive:
    window_data = _expect_mapping(data, "window")
    return WindowArchive(
        index=_expect_int(window_data, "index"),
        name=_expect_str(window_data, "name"),
        layout=_expect_str(window_data, "layout"),
        active=_expect_bool(window_data, "active"),
        panes=tuple(
            _pane_from_dict(pane) for pane in _expect_list(window_data, "panes")
        ),
    )


def _pane_from_dict(data: object) -> PaneArchive:
    pane_data = _expect_mapping(data, "pane")
    return PaneArchive(
        index=_expect_int(pane_data, "index"),
        active=_expect_bool(pane_data, "active"),
        current_command=_expect_str(pane_data, "current_command"),
        current_path=_expect_str(pane_data, "current_path"),
    )


def _expect_mapping(data: object, name: str) -> t.Mapping[str, object]:
    if not isinstance(data, dict):
        msg = f"{name} must be an object"
        raise TypeError(msg)
    return t.cast("t.Mapping[str, object]", data)


def _expect_list(data: t.Mapping[str, object], key: str) -> list[object]:
    value = data[key]
    if not isinstance(value, list):
        msg = f"{key} must be a list"
        raise TypeError(msg)
    return value


def _expect_str(data: t.Mapping[str, object], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        msg = f"{key} must be a string"
        raise TypeError(msg)
    return value


def _expect_int(data: t.Mapping[str, object], key: str) -> int:
    value = data[key]
    if not isinstance(value, int):
        msg = f"{key} must be an integer"
        raise TypeError(msg)
    return value


def _expect_bool(data: t.Mapping[str, object], key: str) -> bool:
    value = data[key]
    if not isinstance(value, bool):
        msg = f"{key} must be a boolean"
        raise TypeError(msg)
    return value
