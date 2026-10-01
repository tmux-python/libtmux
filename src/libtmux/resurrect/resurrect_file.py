"""tmux-resurrect tab-file import and export helpers."""

from __future__ import annotations

import datetime
import typing as t

from libtmux.resurrect.archives import (
    PaneArchive,
    SessionArchive,
    WindowArchive,
    WorkspaceArchive,
)

_DELIMITER = "\t"


def archive_to_resurrect_file(archive: WorkspaceArchive) -> str:
    """Export a native archive to tmux-resurrect-style rows.

    Examples
    --------
    >>> archive = WorkspaceArchive(
    ...     saved_at=datetime.datetime(2026, 7, 4, tzinfo=datetime.timezone.utc),
    ...     sessions=(),
    ... )
    >>> archive_to_resurrect_file(archive)
    ''
    """
    rows: list[str] = []
    group_representatives = _group_representatives(archive.sessions)

    for session in archive.sessions:
        group_target = _group_target(session, group_representatives)
        if group_target is None:
            continue
        rows.append(_grouped_session_row(session, group_target))

    for session in archive.sessions:
        if _group_target(session, group_representatives) is not None:
            continue
        for window in session.windows:
            rows.extend(_pane_row(session, window, pane) for pane in window.panes)

    for session in archive.sessions:
        if _group_target(session, group_representatives) is not None:
            continue
        rows.extend(_window_row(session, window) for window in session.windows)

    if archive.active_session_name or archive.alternate_session_name:
        rows.append(
            _DELIMITER.join(
                (
                    "state",
                    archive.active_session_name or "",
                    archive.alternate_session_name or "",
                ),
            ),
        )

    return "\n".join(rows) + ("\n" if rows else "")


def archive_from_resurrect_file(
    text: str,
    *,
    saved_at: datetime.datetime | None = None,
) -> WorkspaceArchive:
    r"""Import tmux-resurrect-style rows into a native archive.

    Examples
    --------
    >>> text = "window\talpha\t0\t:editor\t1\t:*\ttiled\ton\n"
    >>> archive = archive_from_resurrect_file(
    ...     text,
    ...     saved_at=datetime.datetime(2026, 7, 4, tzinfo=datetime.timezone.utc),
    ... )
    >>> archive.sessions[0].windows[0].name
    'editor'
    """
    active_session_name: str | None = None
    alternate_session_name: str | None = None
    grouped_sessions: dict[str, tuple[str, int | None, int | None]] = {}
    panes: dict[tuple[str, int], list[PaneArchive]] = {}
    windows: dict[tuple[str, int], WindowArchive] = {}

    for raw_line in text.splitlines():
        if not raw_line:
            continue
        fields = raw_line.split(_DELIMITER)
        line_type = _field(fields, 0)
        if line_type == "grouped_session":
            grouped_sessions[_field(fields, 1)] = (
                _field(fields, 2),
                _unprefixed_int(_field(fields, 3)),
                _unprefixed_int(_field(fields, 4)),
            )
        elif line_type == "pane":
            session_name = _field(fields, 1)
            window_index = _int_field(fields, 2)
            panes.setdefault((session_name, window_index), []).append(
                _pane_from_row(fields),
            )
        elif line_type == "window":
            session_name = _field(fields, 1)
            window = _window_from_row(fields)
            windows[(session_name, window.index)] = window
        elif line_type == "state":
            active_session_name = _empty_to_none(_field(fields, 1))
            alternate_session_name = _empty_to_none(_field(fields, 2))

    session_names = (
        {session_name for session_name, _ in windows}
        | {session_name for session_name, _ in panes}
        | set(grouped_sessions)
        | {target for target, _, _ in grouped_sessions.values() if target}
    )
    grouped_targets = {target for target, _, _ in grouped_sessions.values() if target}

    sessions = tuple(
        _session_from_rows(
            session_name,
            grouped_sessions=grouped_sessions,
            grouped_targets=grouped_targets,
            panes=panes,
            windows=windows,
        )
        for session_name in sorted(session_names)
    )

    return WorkspaceArchive(
        active_session_name=active_session_name,
        alternate_session_name=alternate_session_name,
        saved_at=saved_at or datetime.datetime.now(datetime.timezone.utc),
        sessions=sessions,
    )


def _session_from_rows(
    session_name: str,
    *,
    grouped_sessions: t.Mapping[str, tuple[str, int | None, int | None]],
    grouped_targets: set[str],
    panes: t.Mapping[tuple[str, int], list[PaneArchive]],
    windows: t.Mapping[tuple[str, int], WindowArchive],
) -> SessionArchive:
    session_windows = tuple(
        WindowArchive(
            active=window.active,
            automatic_rename=window.automatic_rename,
            flags=window.flags,
            index=window.index,
            layout=window.layout,
            name=window.name,
            panes=tuple(
                sorted(
                    panes.get((session_name, window_index), ()),
                    key=lambda pane: pane.index,
                ),
            ),
        )
        for (window_session_name, window_index), window in sorted(windows.items())
        if window_session_name == session_name
    )
    group_name: str | None = None
    alternate_window_index: int | None = None
    active_window_index: int | None = _active_window_index(session_windows)
    if session_name in grouped_sessions:
        group_name, alternate_window_index, active_window_index = grouped_sessions[
            session_name
        ]
    elif session_name in grouped_targets:
        group_name = session_name

    return SessionArchive(
        name=session_name,
        group_name=group_name,
        alternate_window_index=alternate_window_index,
        active_window_index=active_window_index,
        windows=session_windows,
    )


def _grouped_session_row(session: SessionArchive, group_target: str) -> str:
    return _DELIMITER.join(
        (
            "grouped_session",
            session.name,
            group_target,
            _prefixed(session.alternate_window_index),
            _prefixed(_session_active_window_index(session)),
        ),
    )


def _window_row(session: SessionArchive, window: WindowArchive) -> str:
    if window.automatic_rename is None:
        automatic_rename = ":"
    else:
        automatic_rename = "on" if window.automatic_rename else "off"
    return _DELIMITER.join(
        (
            "window",
            session.name,
            str(window.index),
            f":{window.name}",
            _bool_field(window.active),
            f":{window.flags}",
            window.layout,
            automatic_rename,
        ),
    )


def _pane_row(
    session: SessionArchive,
    window: WindowArchive,
    pane: PaneArchive,
) -> str:
    return _DELIMITER.join(
        (
            "pane",
            session.name,
            str(window.index),
            _bool_field(window.active),
            f":{window.flags}",
            str(pane.index),
            pane.title,
            f":{_escape_path(pane.current_path)}",
            _bool_field(pane.active),
            pane.current_command,
            f":{pane.full_command}",
        ),
    )


def _window_from_row(fields: list[str]) -> WindowArchive:
    return WindowArchive(
        active=_bool_value(_field(fields, 4)),
        automatic_rename=_auto_rename_value(_field(fields, 7)),
        flags=_remove_prefix(_field(fields, 5)),
        index=_int_field(fields, 2),
        layout=_field(fields, 6),
        name=_remove_prefix(_field(fields, 3)),
        panes=(),
    )


def _pane_from_row(fields: list[str]) -> PaneArchive:
    return PaneArchive(
        active=_bool_value(_field(fields, 8)),
        current_command=_field(fields, 9),
        current_path=_unescape_path(_remove_prefix(_field(fields, 7))),
        full_command=_remove_prefix(_field(fields, 10)),
        index=_int_field(fields, 5),
        title=_field(fields, 6),
    )


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


def _group_target(
    session: SessionArchive,
    group_representatives: t.Mapping[str, str],
) -> str | None:
    if session.group_name is None:
        return None
    group_target = group_representatives.get(session.group_name)
    if group_target is None or group_target == session.name:
        return None
    return group_target


def _bool_field(value: bool) -> str:
    return "1" if value else "0"


def _bool_value(value: str) -> bool:
    return value == "1"


def _prefixed(value: int | None) -> str:
    return ":" if value is None else f":{value}"


def _unprefixed_int(value: str) -> int | None:
    raw = _remove_prefix(value)
    return int(raw) if raw else None


def _remove_prefix(value: str) -> str:
    return value[1:] if value.startswith(":") else value


def _empty_to_none(value: str) -> str | None:
    return value or None


def _auto_rename_value(value: str) -> bool | None:
    if value == "on":
        return True
    if value == "off":
        return False
    return None


def _active_window_index(windows: t.Sequence[WindowArchive]) -> int | None:
    active = next((window for window in windows if window.active), None)
    return active.index if active else None


def _session_active_window_index(session: SessionArchive) -> int | None:
    if session.active_window_index is not None:
        return session.active_window_index
    return _active_window_index(session.windows)


def _field(fields: list[str], index: int, default: str = "") -> str:
    try:
        return fields[index]
    except IndexError:
        return default


def _int_field(fields: list[str], index: int) -> int:
    value = _field(fields, index)
    return int(value) if value else 0


def _escape_path(value: str) -> str:
    return value.replace(" ", "\\ ")


def _unescape_path(value: str) -> str:
    return value.replace("\\ ", " ")
