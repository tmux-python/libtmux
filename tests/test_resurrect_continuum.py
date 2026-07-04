"""Tests for headless tmux-continuum style autosave helpers."""

from __future__ import annotations

import datetime
import pathlib
import typing as t

from libtmux.resurrect.continuum import (
    DEFAULT_AUTOSAVE_INTERVAL,
    AutosaveState,
    autosave_once,
    next_autosave_at,
    read_autosave_state,
    should_autosave,
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

    def __init__(self) -> None:
        separator = "\x1f"
        self.stdout = [
            separator.join(
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
