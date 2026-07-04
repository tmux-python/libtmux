"""Archive history, rotation, and last-pointer helpers."""

from __future__ import annotations

import pathlib
import typing as t
from dataclasses import dataclass

from libtmux._internal.types import StrPath
from libtmux.resurrect.archives import WorkspaceArchive, write_archive

LastPointerKind: t.TypeAlias = t.Literal["copy", "symlink"]
"""How the ``last`` pointer was written."""


@dataclass(frozen=True, slots=True)
class ArchiveSnapshot:
    """Paths touched while writing an archive snapshot."""

    archive_path: pathlib.Path
    last_path: pathlib.Path
    last_kind: LastPointerKind
    removed_paths: tuple[pathlib.Path, ...]


def write_archive_snapshot(
    archive: WorkspaceArchive,
    directory: StrPath,
    *,
    basename: str = "workspace",
    keep: int = 5,
    portable_last: bool = False,
) -> ArchiveSnapshot:
    """Write a timestamped archive, rotate old copies, and update ``last``.

    Examples
    --------
    >>> import datetime
    >>> import pathlib
    >>> from libtmux.resurrect.archives import WorkspaceArchive
    >>> archive = WorkspaceArchive(
    ...     saved_at=datetime.datetime(2026, 7, 4, tzinfo=datetime.timezone.utc),
    ...     sessions=(),
    ... )
    >>> target = pathlib.Path(request.getfixturevalue("tmp_path"))
    >>> snapshot = write_archive_snapshot(archive, target, portable_last=True)
    >>> snapshot.archive_path.name
    'workspace-20260704T000000Z.json'
    >>> snapshot.last_kind
    'copy'
    """
    base_dir = pathlib.Path(directory)
    base_dir.mkdir(parents=True, exist_ok=True)
    timestamp = archive.saved_at.strftime("%Y%m%dT%H%M%SZ")
    archive_path = write_archive(archive, base_dir / f"{basename}-{timestamp}.json")
    last_path = base_dir / "last.json"
    last_kind = _write_last_pointer(
        archive,
        archive_path=archive_path,
        last_path=last_path,
        portable_last=portable_last,
    )
    removed = _rotate(base_dir, basename=basename, keep=keep)
    return ArchiveSnapshot(
        archive_path=archive_path,
        last_path=last_path,
        last_kind=last_kind,
        removed_paths=removed,
    )


def _write_last_pointer(
    archive: WorkspaceArchive,
    *,
    archive_path: pathlib.Path,
    last_path: pathlib.Path,
    portable_last: bool,
) -> LastPointerKind:
    if portable_last:
        write_archive(archive, last_path)
        return "copy"

    try:
        _replace_relative_symlink(archive_path, last_path)
    except OSError:
        write_archive(archive, last_path)
        return "copy"
    return "symlink"


def _replace_relative_symlink(source: pathlib.Path, link: pathlib.Path) -> None:
    tmp_link = link.with_name(f".{link.name}.tmp")
    tmp_link.unlink(missing_ok=True)
    tmp_link.symlink_to(source.name)
    tmp_link.replace(link)


def _rotate(
    directory: pathlib.Path,
    *,
    basename: str,
    keep: int,
) -> tuple[pathlib.Path, ...]:
    if keep <= 0:
        return ()
    archives = sorted(directory.glob(f"{basename}-*.json"))
    expired = archives[:-keep]
    for path in expired:
        path.unlink(missing_ok=True)
    return tuple(expired)
