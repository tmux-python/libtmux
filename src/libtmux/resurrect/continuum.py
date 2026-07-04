"""Headless tmux-continuum style autosave helpers."""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import typing as t
from dataclasses import dataclass

from libtmux._internal.types import StrPath
from libtmux.resurrect.archives import capture_archive, write_archive

if t.TYPE_CHECKING:
    from libtmux.server import Server

STATE_FORMAT_VERSION = "libtmux.resurrect.autosave-state.v1"
"""Autosave state format identifier."""

DEFAULT_AUTOSAVE_INTERVAL = datetime.timedelta(minutes=15)
"""Default interval between autosaves."""


@dataclass(frozen=True, slots=True)
class AutosaveState:
    """Persisted autosave state."""

    last_saved_at: datetime.datetime | None = None
    last_archive_path: pathlib.Path | None = None
    save_count: int = 0
    format_version: str = STATE_FORMAT_VERSION


@dataclass(frozen=True, slots=True)
class AutosaveResult:
    """Result returned by :func:`autosave_once`."""

    saved: bool
    reason: str
    archive_path: pathlib.Path
    state: AutosaveState
    state_path: pathlib.Path | None = None


def next_autosave_at(
    last_saved_at: datetime.datetime | None,
    *,
    interval: datetime.timedelta = DEFAULT_AUTOSAVE_INTERVAL,
) -> datetime.datetime | None:
    """Return when the next autosave is due.

    Examples
    --------
    >>> import datetime
    >>> saved = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)
    >>> next_autosave_at(saved)
    datetime.datetime(2026, 7, 4, 12, 15, tzinfo=datetime.timezone.utc)
    >>> next_autosave_at(None) is None
    True
    """
    if last_saved_at is None:
        return None
    return _coerce_datetime(last_saved_at) + interval


def should_autosave(
    *,
    last_saved_at: datetime.datetime | None,
    now: datetime.datetime | None = None,
    interval: datetime.timedelta = DEFAULT_AUTOSAVE_INTERVAL,
) -> bool:
    """Return True when an autosave should run.

    Examples
    --------
    >>> should_autosave(last_saved_at=None)
    True
    """
    if last_saved_at is None:
        return True

    due_at = next_autosave_at(last_saved_at, interval=interval)
    return due_at is not None and _coerce_datetime(now) >= due_at


def read_autosave_state(path: StrPath) -> AutosaveState:
    """Read persisted autosave state, returning an empty state if missing.

    Examples
    --------
    >>> import pathlib
    >>> target = pathlib.Path(request.getfixturevalue("tmp_path")) / "state.json"
    >>> read_autosave_state(target).save_count
    0
    """
    source = pathlib.Path(path)
    if not source.exists():
        return AutosaveState()
    return _state_from_dict(json.loads(source.read_text(encoding="utf-8")))


def write_autosave_state(state: AutosaveState, path: StrPath) -> pathlib.Path:
    """Write autosave state using an atomic replace.

    Examples
    --------
    >>> import pathlib
    >>> target = pathlib.Path(request.getfixturevalue("tmp_path")) / "state.json"
    >>> saved = write_autosave_state(AutosaveState(save_count=1), target)
    >>> saved == target
    True
    """
    destination = pathlib.Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        json.dumps(_state_to_dict(state), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(destination)
    return destination


def autosave_once(
    server: Server,
    *,
    archive_path: StrPath,
    state_path: StrPath | None = None,
    now: datetime.datetime | None = None,
    interval: datetime.timedelta = DEFAULT_AUTOSAVE_INTERVAL,
    force: bool = False,
) -> AutosaveResult:
    """Capture and write one archive if autosave is due.

    Examples
    --------
    >>> import pathlib
    >>> target = pathlib.Path(request.getfixturevalue("tmp_path")) / "tmux.json"
    >>> result = autosave_once(server, archive_path=target, force=True)
    >>> result.saved
    True
    """
    resolved_archive_path = pathlib.Path(archive_path)
    resolved_state_path = pathlib.Path(state_path) if state_path is not None else None
    previous_state = (
        read_autosave_state(resolved_state_path)
        if resolved_state_path is not None
        else AutosaveState()
    )
    resolved_now = _coerce_datetime(now)

    if not force and not should_autosave(
        last_saved_at=previous_state.last_saved_at,
        now=resolved_now,
        interval=interval,
    ):
        return AutosaveResult(
            saved=False,
            reason="interval_not_elapsed",
            archive_path=resolved_archive_path,
            state=previous_state,
            state_path=resolved_state_path,
        )

    archive = capture_archive(server, saved_at=resolved_now)
    write_archive(archive, resolved_archive_path)
    next_state = AutosaveState(
        last_saved_at=resolved_now,
        last_archive_path=resolved_archive_path,
        save_count=previous_state.save_count + 1,
    )
    if resolved_state_path is not None:
        write_autosave_state(next_state, resolved_state_path)

    return AutosaveResult(
        saved=True,
        reason="saved",
        archive_path=resolved_archive_path,
        state=next_state,
        state_path=resolved_state_path,
    )


def _coerce_datetime(value: datetime.datetime | None) -> datetime.datetime:
    if value is None:
        return datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _state_to_dict(state: AutosaveState) -> dict[str, object]:
    return {
        "format_version": state.format_version,
        "last_archive_path": (
            str(state.last_archive_path) if state.last_archive_path else None
        ),
        "last_saved_at": (
            _coerce_datetime(state.last_saved_at).isoformat()
            if state.last_saved_at is not None
            else None
        ),
        "save_count": state.save_count,
    }


def _state_from_dict(data: object) -> AutosaveState:
    state_data = _expect_mapping(data, "state")
    format_version = _expect_str(state_data, "format_version")
    if format_version != STATE_FORMAT_VERSION:
        msg = f"unsupported autosave state format: {format_version}"
        raise ValueError(msg)

    return AutosaveState(
        format_version=format_version,
        last_archive_path=_optional_path(state_data, "last_archive_path"),
        last_saved_at=_optional_datetime(state_data, "last_saved_at"),
        save_count=_expect_int(state_data, "save_count"),
    )


def _optional_path(data: t.Mapping[str, object], key: str) -> pathlib.Path | None:
    value = data[key]
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{key} must be a string or null"
        raise TypeError(msg)
    return pathlib.Path(value)


def _optional_datetime(
    data: t.Mapping[str, object],
    key: str,
) -> datetime.datetime | None:
    value = data[key]
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{key} must be a string or null"
        raise TypeError(msg)
    return _coerce_datetime(datetime.datetime.fromisoformat(value))


def _expect_mapping(data: object, name: str) -> t.Mapping[str, object]:
    if not isinstance(data, dict):
        msg = f"{name} must be an object"
        raise TypeError(msg)
    return t.cast("t.Mapping[str, object]", data)


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
