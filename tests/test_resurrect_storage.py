"""Tests for archive snapshot storage helpers."""

from __future__ import annotations

import datetime
import pathlib

from libtmux.resurrect.archives import WorkspaceArchive, read_archive
from libtmux.resurrect.storage import (
    ArchiveSnapshot,
    write_archive_snapshot,
)


def _archive(minute: int) -> WorkspaceArchive:
    return WorkspaceArchive(
        saved_at=datetime.datetime(
            2026,
            7,
            4,
            12,
            minute,
            tzinfo=datetime.timezone.utc,
        ),
        sessions=(),
    )


def test_write_archive_snapshot_updates_portable_last(
    tmp_path: pathlib.Path,
) -> None:
    """write_archive_snapshot() can write last.json as a portable copy."""
    archive = _archive(0)

    snapshot = write_archive_snapshot(archive, tmp_path, portable_last=True)

    assert isinstance(snapshot, ArchiveSnapshot)
    assert snapshot.archive_path.name == "workspace-20260704T120000Z.json"
    assert snapshot.archive_path.exists()
    assert snapshot.last_path == tmp_path / "last.json"
    assert snapshot.last_kind == "copy"
    assert not snapshot.last_path.is_symlink()
    assert read_archive(snapshot.last_path) == archive


def test_write_archive_snapshot_updates_last_pointer(
    tmp_path: pathlib.Path,
) -> None:
    """write_archive_snapshot() writes a relative symlink or portable fallback."""
    archive = _archive(1)

    snapshot = write_archive_snapshot(archive, tmp_path)

    assert snapshot.archive_path.exists()
    assert snapshot.last_path.exists()
    if snapshot.last_kind == "symlink":
        assert snapshot.last_path.is_symlink()
        assert snapshot.last_path.readlink() == pathlib.Path(snapshot.archive_path.name)
    else:
        assert read_archive(snapshot.last_path) == archive


def test_write_archive_snapshot_rotates_old_archives(
    tmp_path: pathlib.Path,
) -> None:
    """write_archive_snapshot() removes older timestamped snapshots."""
    first = write_archive_snapshot(_archive(0), tmp_path, keep=2, portable_last=True)
    second = write_archive_snapshot(_archive(1), tmp_path, keep=2, portable_last=True)
    third = write_archive_snapshot(_archive(2), tmp_path, keep=2, portable_last=True)

    assert first.archive_path in third.removed_paths
    assert not first.archive_path.exists()
    assert second.archive_path.exists()
    assert third.archive_path.exists()
    assert sorted(path.name for path in tmp_path.glob("workspace-*.json")) == [
        "workspace-20260704T120100Z.json",
        "workspace-20260704T120200Z.json",
    ]
