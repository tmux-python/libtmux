"""Tests for tmux-resurrect tab-file conversion."""

from __future__ import annotations

import datetime

from libtmux.resurrect.archives import (
    PaneArchive,
    SessionArchive,
    WindowArchive,
    WorkspaceArchive,
)
from libtmux.resurrect.resurrect_file import (
    archive_from_resurrect_file,
    archive_to_resurrect_file,
)


def test_resurrect_file_converter_round_trips_core_rows() -> None:
    """tmux-resurrect tab rows convert to and from native archives."""
    saved_at = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)
    archive = WorkspaceArchive(
        saved_at=saved_at,
        active_session_name="alpha",
        alternate_session_name="beta",
        sessions=(
            SessionArchive(
                name="alpha",
                active_window_index=0,
                windows=(
                    WindowArchive(
                        index=0,
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
                                current_path="/work space",
                                title="src",
                                full_command="vim pyproject.toml",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    text = archive_to_resurrect_file(archive)
    restored = archive_from_resurrect_file(text, saved_at=saved_at)

    assert "state\talpha\tbeta" in text
    assert "pane\talpha\t0\t1\t:*Z\t0\tsrc\t:/work\\ space" in text
    assert "window\talpha\t0\t:editor\t1\t:*Z\ttiled\toff" in text
    assert restored == archive


def test_resurrect_file_imports_upstream_grouped_rows() -> None:
    """tmux-resurrect grouped follower rows import without duplicated windows."""
    saved_at = datetime.datetime(2026, 7, 4, 12, tzinfo=datetime.timezone.utc)
    text = "\n".join(
        (
            "grouped_session\tbeta\talpha\t:0\t:1",
            (
                "pane\talpha\t1\t1\t:*Z\t0\tsrc\t:/work\\ space\t1\tvim"
                "\t:vim pyproject.toml"
            ),
            "window\talpha\t1\t:editor\t1\t:*Z\ttiled\toff",
            "state\talpha\tbeta",
            "",
        ),
    )

    archive = archive_from_resurrect_file(text, saved_at=saved_at)
    exported = archive_to_resurrect_file(archive)

    assert archive.active_session_name == "alpha"
    assert archive.alternate_session_name == "beta"
    alpha = archive.sessions[0]
    beta = archive.sessions[1]
    assert alpha.name == "alpha"
    assert alpha.group_name == "alpha"
    assert alpha.windows[0].name == "editor"
    assert alpha.windows[0].panes[0].current_path == "/work space"
    assert alpha.windows[0].panes[0].full_command == "vim pyproject.toml"
    assert beta.name == "beta"
    assert beta.group_name == "alpha"
    assert beta.alternate_window_index == 0
    assert beta.active_window_index == 1
    assert beta.windows == ()
    assert "grouped_session\tbeta\talpha\t:0\t:1" in exported
    assert "pane\tbeta" not in exported
