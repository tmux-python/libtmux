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
from libtmux.formats import FORMAT_SEPARATOR
from libtmux.resurrect.processes import (
    DEFAULT_PROCESS_RESTORE_POLICY,
    ProcessCommandProvider,
    ProcessRestorePolicy,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

FORMAT_VERSION = "libtmux.resurrect.archive.v1"
"""Archive format identifier."""

CAPTURED_CAPABILITIES = (
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
"""tmux-resurrect parity features captured by :func:`capture_archive`."""

DEFAULT_SHELL_COMMANDS = frozenset({"bash", "dash", "fish", "ksh", "sh", "zsh"})
"""Commands treated as shells during restore."""

RestorePolicy: t.TypeAlias = t.Literal["error", "replace", "reuse"]
"""How restore handles sessions that already exist."""

_FIELD_SEPARATOR = FORMAT_SEPARATOR
_PANE_FIELDS = (
    "#{session_name}",
    "#{window_index}",
    "#{window_name}",
    "#{window_layout}",
    "#{window_active}",
    "#{window_flags}",
    "#{pane_index}",
    "#{pane_active}",
    "#{pane_pid}",
    "#{pane_current_command}",
    "#{pane_current_path}",
    "#{pane_title}",
    "#{history_size}",
)
_PANE_FORMAT = "".join(f"{field}{_FIELD_SEPARATOR}" for field in _PANE_FIELDS)
_SESSION_FORMAT = "".join(
    f"{field}{_FIELD_SEPARATOR}"
    for field in (
        "#{session_name}",
        "#{session_grouped}",
        "#{session_group}",
    )
)
_CLIENT_FORMAT = "".join(
    f"{field}{_FIELD_SEPARATOR}"
    for field in (
        "#{client_session}",
        "#{client_last_session}",
    )
)


@dataclass(frozen=True, slots=True)
class PaneArchive:
    """Serialized tmux pane state."""

    index: int
    active: bool
    current_command: str
    current_path: str
    title: str = ""
    full_command: str = ""
    history_size: int = 0
    contents: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WindowArchive:
    """Serialized tmux window state."""

    index: int
    name: str
    layout: str
    active: bool
    panes: tuple[PaneArchive, ...]
    flags: str = ""
    automatic_rename: bool | None = None


@dataclass(frozen=True, slots=True)
class SessionArchive:
    """Serialized tmux session state."""

    name: str
    windows: tuple[WindowArchive, ...]
    group_name: str | None = None
    active_window_index: int | None = None
    alternate_window_index: int | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceArchive:
    """Serialized tmux workspace state."""

    saved_at: datetime.datetime
    sessions: tuple[SessionArchive, ...]
    format_version: str = FORMAT_VERSION
    capabilities: tuple[str, ...] = CAPTURED_CAPABILITIES
    active_session_name: str | None = None
    alternate_session_name: str | None = None


@dataclass(frozen=True, slots=True)
class _PaneRow:
    """Flattened list-panes row before grouping."""

    session_name: str
    window_index: int
    window_name: str
    window_layout: str
    window_active: bool
    window_flags: str
    pane_index: int
    pane_active: bool
    pane_pid: int
    pane_current_command: str
    pane_current_path: str
    pane_title: str
    history_size: int


def capture_archive(
    server: Server,
    *,
    process_provider: ProcessCommandProvider | None = None,
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
    active_session_name, alternate_session_name = _capture_client_state(server)
    return _archive_from_rows(
        rows,
        active_session_name=active_session_name,
        alternate_session_name=alternate_session_name,
        automatic_renames=_capture_automatic_renames(server, rows),
        process_commands=_capture_process_commands(rows, process_provider),
        saved_at=saved_at,
        session_groups=_capture_session_groups(server),
    )


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
    process_policy: ProcessRestorePolicy | None = DEFAULT_PROCESS_RESTORE_POLICY,
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
    group_representatives = _group_representatives(resolved_archive.sessions)

    for session_archive in _ordered_session_archives(
        resolved_archive.sessions,
        group_representatives=group_representatives,
    ):
        group_target = _group_target(session_archive, group_representatives)
        if server.has_session(session_archive.name):
            if on_exists == "reuse":
                _restore_missing_session_topology(
                    server,
                    session_archive,
                    process_policy=process_policy,
                    shell_commands=shell_commands,
                )
                _restore_session_focus(server, session_archive)
                continue
            if on_exists == "error":
                msg = f"session already exists: {session_archive.name}"
                raise FileExistsError(msg)
            proc = server.cmd("kill-session", target=session_archive.name)
            raise_if_stderr(proc, "kill-session")

        if group_target is not None and server.has_session(group_target):
            session = _restore_grouped_session(
                server,
                session_archive,
                target_session=group_target,
            )
            if session is not None:
                sessions.append(session)
            continue

        session = _restore_session(
            server,
            session_archive,
            process_policy=process_policy,
            shell_commands=shell_commands,
        )
        sessions.append(session)

    _restore_workspace_focus(server, resolved_archive)

    return sessions


def _archive_from_rows(
    rows: tuple[_PaneRow, ...],
    *,
    active_session_name: str | None = None,
    alternate_session_name: str | None = None,
    automatic_renames: t.Mapping[tuple[str, int], bool | None] | None = None,
    process_commands: t.Mapping[int, str] | None = None,
    saved_at: datetime.datetime | None = None,
    session_groups: t.Mapping[str, str] | None = None,
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
                    full_command=(process_commands or {}).get(row.pane_pid, ""),
                    title=row.pane_title,
                    history_size=row.history_size,
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
                    flags=first.window_flags,
                    automatic_rename=(automatic_renames or {}).get(
                        (first.session_name, first.window_index)
                    ),
                ),
            )
        active_window_index = next(
            (window.index for window in windows if window.active),
            None,
        )
        alternate_window_index = next(
            (window.index for window in windows if "-" in window.flags),
            None,
        )
        sessions.append(
            SessionArchive(
                name=session_name,
                windows=tuple(windows),
                group_name=(session_groups or {}).get(session_name),
                active_window_index=active_window_index,
                alternate_window_index=alternate_window_index,
            ),
        )

    return WorkspaceArchive(
        active_session_name=active_session_name,
        alternate_session_name=alternate_session_name,
        saved_at=_coerce_saved_at(saved_at),
        sessions=tuple(sessions),
    )


def _restore_session(
    server: Server,
    session_archive: SessionArchive,
    *,
    process_policy: ProcessRestorePolicy | None,
    shell_commands: t.Collection[str],
) -> Session:
    first_window = session_archive.windows[0] if session_archive.windows else None
    first_pane = first_window.panes[0] if first_window and first_window.panes else None

    session = server.new_session(
        session_name=session_archive.name,
        start_directory=_pane_path(first_pane),
        window_name=_name_or_none(first_window.name) if first_window else None,
        window_command=_pane_command(
            first_pane,
            process_policy=process_policy,
            shell_commands=shell_commands,
        ),
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
            process_policy=process_policy,
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
                process_policy=process_policy,
                shell_commands=shell_commands,
            ),
            attach=False,
        )
        _restore_window(
            server,
            session_archive=session_archive,
            window=window,
            window_archive=window_archive,
            process_policy=process_policy,
            shell_commands=shell_commands,
            skip_first_pane=True,
        )

    _restore_session_focus(server, session_archive, session=session)

    return session


def _restore_grouped_session(
    server: Server,
    session_archive: SessionArchive,
    *,
    target_session: str,
) -> Session | None:
    proc = server.cmd(
        "new-session",
        "-d",
        "-s",
        session_archive.name,
        "-t",
        target_session,
    )
    raise_if_stderr(proc, "new-session")
    _restore_session_focus(server, session_archive)
    return _resolve_session(server, session_archive.name)


def _restore_missing_session_topology(
    server: Server,
    session_archive: SessionArchive,
    *,
    process_policy: ProcessRestorePolicy | None,
    shell_commands: t.Collection[str],
) -> None:
    existing_windows = _existing_window_indexes(server, session_archive.name)
    for window_archive in session_archive.windows:
        if window_archive.index not in existing_windows:
            _create_missing_window(
                server,
                session_archive=session_archive,
                window_archive=window_archive,
                process_policy=process_policy,
                shell_commands=shell_commands,
            )
            continue

        existing_panes = _existing_pane_indexes(
            server,
            session_archive.name,
            window_archive.index,
        )
        for pane_archive in window_archive.panes:
            if pane_archive.index in existing_panes:
                continue
            _create_missing_pane(
                server,
                session_archive=session_archive,
                window_archive=window_archive,
                pane_archive=pane_archive,
                process_policy=process_policy,
                shell_commands=shell_commands,
            )
        _restore_reused_window_state(
            server,
            session_archive=session_archive,
            window_archive=window_archive,
        )


def _create_missing_window(
    server: Server,
    *,
    session_archive: SessionArchive,
    window_archive: WindowArchive,
    process_policy: ProcessRestorePolicy | None,
    shell_commands: t.Collection[str],
) -> None:
    first_pane = window_archive.panes[0] if window_archive.panes else None
    args = [
        "-d",
        "-t",
        f"{session_archive.name}:{window_archive.index}",
        "-n",
        window_archive.name,
    ]
    path = _pane_path(first_pane)
    if path is not None:
        args.extend(("-c", path))
    command = _pane_command(
        first_pane,
        process_policy=process_policy,
        shell_commands=shell_commands,
    )
    if command is not None:
        args.append(command)

    proc = server.cmd("new-window", *args)
    raise_if_stderr(proc, "new-window")


def _create_missing_pane(
    server: Server,
    *,
    session_archive: SessionArchive,
    window_archive: WindowArchive,
    pane_archive: PaneArchive,
    process_policy: ProcessRestorePolicy | None,
    shell_commands: t.Collection[str],
) -> None:
    args = ["-d", "-t", f"{session_archive.name}:{window_archive.index}"]
    path = _path_or_none(pane_archive.current_path)
    if path is not None:
        args.extend(("-c", path))
    command = _pane_command(
        pane_archive,
        process_policy=process_policy,
        shell_commands=shell_commands,
    )
    if command is not None:
        args.append(command)

    proc = server.cmd("split-window", *args)
    raise_if_stderr(proc, "split-window")


def _existing_window_indexes(server: Server, session_name: str) -> set[int]:
    proc = server.cmd("list-windows", "-t", session_name, "-F", "#{window_index}")
    if proc.stderr:
        return set()
    return {_tmux_int(line) for line in proc.stdout}


def _existing_pane_indexes(
    server: Server,
    session_name: str,
    window_index: int,
) -> set[int]:
    proc = server.cmd(
        "list-panes",
        "-t",
        f"{session_name}:{window_index}",
        "-F",
        "#{pane_index}",
    )
    if proc.stderr:
        return set()
    return {_tmux_int(line) for line in proc.stdout}


def _restore_window(
    server: Server,
    *,
    session_archive: SessionArchive,
    window: Window,
    window_archive: WindowArchive,
    process_policy: ProcessRestorePolicy | None,
    shell_commands: t.Collection[str],
    skip_first_pane: bool,
) -> None:
    pane_archives = (
        window_archive.panes[1:] if skip_first_pane else window_archive.panes
    )
    for pane_archive in pane_archives:
        window.split(
            start_directory=_path_or_none(pane_archive.current_path),
            shell=_pane_command(
                pane_archive,
                process_policy=process_policy,
                shell_commands=shell_commands,
            ),
            attach=pane_archive.active,
        )

    if window_archive.layout:
        window.select_layout(window_archive.layout)

    _restore_window_metadata(
        server,
        session_archive=session_archive,
        window_archive=window_archive,
    )
    _restore_active_pane(
        server,
        session_archive=session_archive,
        window_archive=window_archive,
    )


def _restore_reused_window_state(
    server: Server,
    *,
    session_archive: SessionArchive,
    window_archive: WindowArchive,
) -> None:
    target_window = _target_window(session_archive, window_archive)
    if window_archive.layout:
        proc = server.cmd("select-layout", "-t", target_window, window_archive.layout)
        raise_if_stderr(proc, "select-layout")

    _restore_window_metadata(
        server,
        session_archive=session_archive,
        window_archive=window_archive,
    )
    _restore_active_pane(
        server,
        session_archive=session_archive,
        window_archive=window_archive,
    )


def _restore_window_metadata(
    server: Server,
    *,
    session_archive: SessionArchive,
    window_archive: WindowArchive,
) -> None:
    target_window = _target_window(session_archive, window_archive)
    if window_archive.automatic_rename is not None:
        proc = server.cmd(
            "set-window-option",
            "-t",
            target_window,
            "automatic-rename",
            "on" if window_archive.automatic_rename else "off",
        )
        raise_if_stderr(proc, "set-window-option")

    for pane_archive in window_archive.panes:
        if not pane_archive.title:
            continue
        proc = server.cmd(
            "select-pane",
            "-T",
            pane_archive.title,
            target=f"{target_window}.{pane_archive.index}",
        )
        raise_if_stderr(proc, "select-pane")

    if "Z" in window_archive.flags:
        proc = server.cmd("resize-pane", "-Z", target=target_window)
        raise_if_stderr(proc, "resize-pane")


def _restore_active_pane(
    server: Server,
    *,
    session_archive: SessionArchive,
    window_archive: WindowArchive,
) -> None:
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


def _restore_session_focus(
    server: Server,
    session_archive: SessionArchive,
    *,
    session: Session | None = None,
) -> None:
    if session_archive.alternate_window_index is not None:
        proc = server.cmd(
            "select-window",
            "-t",
            f"{session_archive.name}:{session_archive.alternate_window_index}",
        )
        raise_if_stderr(proc, "select-window")

    active_window_index = session_archive.active_window_index
    if active_window_index is None:
        active_window_archive = _active_window(session_archive)
        active_window_index = (
            active_window_archive.index if active_window_archive is not None else None
        )

    if active_window_index is None:
        return

    if session is not None:
        session.select_window(active_window_index)
        return

    proc = server.cmd(
        "select-window",
        "-t",
        f"{session_archive.name}:{active_window_index}",
    )
    raise_if_stderr(proc, "select-window")


def _restore_workspace_focus(server: Server, archive: WorkspaceArchive) -> None:
    for session_name in (
        archive.alternate_session_name,
        archive.active_session_name,
    ):
        if session_name is None:
            continue
        server.cmd("switch-client", "-t", session_name)


def _target_window(
    session_archive: SessionArchive,
    window_archive: WindowArchive,
) -> str:
    return f"{session_archive.name}:{window_archive.index}"


def _group_representatives(
    sessions: t.Iterable[SessionArchive],
) -> dict[str, str]:
    members_by_group: dict[str, list[str]] = {}
    for session_archive in sessions:
        if session_archive.group_name is None:
            continue
        members_by_group.setdefault(session_archive.group_name, []).append(
            session_archive.name,
        )

    return {
        group_name: group_name if group_name in members else members[0]
        for group_name, members in members_by_group.items()
    }


def _ordered_session_archives(
    sessions: tuple[SessionArchive, ...],
    *,
    group_representatives: t.Mapping[str, str],
) -> tuple[SessionArchive, ...]:
    return tuple(
        session_archive
        for _, session_archive in sorted(
            enumerate(sessions),
            key=lambda item: (
                _is_group_follower(item[1], group_representatives),
                item[0],
            ),
        )
    )


def _is_group_follower(
    session_archive: SessionArchive,
    group_representatives: t.Mapping[str, str],
) -> bool:
    if session_archive.group_name is None:
        return False
    return group_representatives.get(session_archive.group_name) != session_archive.name


def _group_target(
    session_archive: SessionArchive,
    group_representatives: t.Mapping[str, str],
) -> str | None:
    if not _is_group_follower(session_archive, group_representatives):
        return None
    return group_representatives[session_archive.group_name or ""]


def _resolve_session(server: Server, session_name: str) -> Session | None:
    try:
        return server.sessions.get(default=None, session_name=session_name)
    except AttributeError:
        return None


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
    process_policy: ProcessRestorePolicy | None,
    shell_commands: t.Collection[str],
) -> str | None:
    if pane is None:
        return None
    if not pane.current_command or pane.current_command in shell_commands:
        return None
    if process_policy is None:
        return None
    return process_policy.resolve_command(pane.full_command or pane.current_command)


def _parse_pane_row(row: str) -> _PaneRow:
    parts = row.split(_FIELD_SEPARATOR)
    if parts and parts[-1] == "":
        parts.pop()

    if len(parts) not in {9, 12, 13}:
        msg = f"expected 9, 12, or 13 list-panes fields, got {len(parts)}"
        raise ValueError(msg)

    if len(parts) == 9:
        parts = [
            *parts[:5],
            "",
            parts[5],
            parts[6],
            "0",
            parts[7],
            parts[8],
            "",
            "0",
        ]
    elif len(parts) == 12:
        parts = [
            *parts[:8],
            "0",
            *parts[8:],
        ]

    return _PaneRow(
        session_name=parts[0],
        window_index=_tmux_int(parts[1]),
        window_name=parts[2],
        window_layout=parts[3],
        window_active=_tmux_bool(parts[4]),
        window_flags=parts[5],
        pane_index=_tmux_int(parts[6]),
        pane_active=_tmux_bool(parts[7]),
        pane_pid=_tmux_int(parts[8]),
        pane_current_command=parts[9],
        pane_current_path=parts[10],
        pane_title=parts[11],
        history_size=_tmux_int(parts[12]),
    )


def _tmux_bool(value: str) -> bool:
    return value == "1"


def _tmux_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def _capture_session_groups(server: Server) -> dict[str, str]:
    proc = server.cmd("list-sessions", "-F", _SESSION_FORMAT)
    if proc.stderr:
        return {}

    groups: dict[str, str] = {}
    for line in proc.stdout:
        parts = _split_tmux_row(line)
        if len(parts) != 3:
            continue
        session_name, session_grouped, session_group = parts
        if _tmux_bool(session_grouped) and session_group:
            groups[session_name] = session_group
    return groups


def _capture_client_state(server: Server) -> tuple[str | None, str | None]:
    proc = server.cmd("list-clients", "-F", _CLIENT_FORMAT)
    if proc.stderr or not proc.stdout:
        return None, None

    parts = _split_tmux_row(proc.stdout[0])
    if len(parts) != 2:
        return None, None
    return parts[0] or None, parts[1] or None


def _capture_automatic_renames(
    server: Server,
    rows: tuple[_PaneRow, ...],
) -> dict[tuple[str, int], bool | None]:
    window_keys = sorted({(row.session_name, row.window_index) for row in rows})
    return {
        window_key: _capture_automatic_rename(server, *window_key)
        for window_key in window_keys
    }


def _capture_automatic_rename(
    server: Server,
    session_name: str,
    window_index: int,
) -> bool | None:
    proc = server.cmd(
        "show-window-options",
        "-v",
        "-t",
        f"{session_name}:{window_index}",
        "automatic-rename",
    )
    if proc.stderr or not proc.stdout:
        return None
    value = proc.stdout[0]
    if value == "on":
        return True
    if value == "off":
        return False
    return None


def _capture_process_commands(
    rows: tuple[_PaneRow, ...],
    process_provider: ProcessCommandProvider | None,
) -> dict[int, str]:
    if process_provider is None:
        return {}

    commands: dict[int, str] = {}
    for pane_pid in sorted({row.pane_pid for row in rows if row.pane_pid > 0}):
        command = process_provider.capture(pane_pid)
        if command:
            commands[pane_pid] = command
    return commands


def _split_tmux_row(row: str) -> list[str]:
    parts = row.split(_FIELD_SEPARATOR)
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def _coerce_saved_at(value: datetime.datetime | None) -> datetime.datetime:
    if value is None:
        return datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _archive_to_dict(archive: WorkspaceArchive) -> dict[str, object]:
    return {
        "active_session_name": archive.active_session_name,
        "alternate_session_name": archive.alternate_session_name,
        "capabilities": list(archive.capabilities),
        "format_version": archive.format_version,
        "saved_at": _coerce_saved_at(archive.saved_at).isoformat(),
        "sessions": [
            {
                "active_window_index": session.active_window_index,
                "alternate_window_index": session.alternate_window_index,
                "group_name": session.group_name,
                "name": session.name,
                "windows": [
                    {
                        "active": window.active,
                        "automatic_rename": window.automatic_rename,
                        "flags": window.flags,
                        "index": window.index,
                        "layout": window.layout,
                        "name": window.name,
                        "panes": [
                            {
                                "active": pane.active,
                                "contents": list(pane.contents),
                                "current_command": pane.current_command,
                                "current_path": pane.current_path,
                                "full_command": pane.full_command,
                                "history_size": pane.history_size,
                                "index": pane.index,
                                "title": pane.title,
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
        active_session_name=_optional_str(archive_data, "active_session_name"),
        alternate_session_name=_optional_str(archive_data, "alternate_session_name"),
        capabilities=_optional_str_tuple(
            archive_data,
            "capabilities",
            default=CAPTURED_CAPABILITIES,
        ),
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
        active_window_index=_optional_int(session_data, "active_window_index"),
        alternate_window_index=_optional_int(session_data, "alternate_window_index"),
        group_name=_optional_str(session_data, "group_name"),
        name=_expect_str(session_data, "name"),
        windows=tuple(
            _window_from_dict(window)
            for window in _expect_list(session_data, "windows")
        ),
    )


def _window_from_dict(data: object) -> WindowArchive:
    window_data = _expect_mapping(data, "window")
    return WindowArchive(
        active=_expect_bool(window_data, "active"),
        automatic_rename=_optional_bool(window_data, "automatic_rename"),
        flags=_optional_str(window_data, "flags") or "",
        index=_expect_int(window_data, "index"),
        layout=_expect_str(window_data, "layout"),
        name=_expect_str(window_data, "name"),
        panes=tuple(
            _pane_from_dict(pane) for pane in _expect_list(window_data, "panes")
        ),
    )


def _pane_from_dict(data: object) -> PaneArchive:
    pane_data = _expect_mapping(data, "pane")
    return PaneArchive(
        active=_expect_bool(pane_data, "active"),
        contents=_optional_str_tuple(pane_data, "contents", default=()),
        current_command=_expect_str(pane_data, "current_command"),
        current_path=_expect_str(pane_data, "current_path"),
        full_command=_optional_str(pane_data, "full_command") or "",
        history_size=_optional_int(pane_data, "history_size") or 0,
        index=_expect_int(pane_data, "index"),
        title=_optional_str(pane_data, "title") or "",
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


def _optional_str_tuple(
    data: t.Mapping[str, object],
    key: str,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f"{key} must be a list of strings"
        raise TypeError(msg)
    return tuple(value)


def _optional_str(data: t.Mapping[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{key} must be a string or null"
        raise TypeError(msg)
    return value


def _optional_int(data: t.Mapping[str, object], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        msg = f"{key} must be an integer or null"
        raise TypeError(msg)
    return value


def _optional_bool(data: t.Mapping[str, object], key: str) -> bool | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        msg = f"{key} must be a boolean or null"
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
