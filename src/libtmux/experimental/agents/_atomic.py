"""Crash-safe file writes for the agent store and the hook installers.

Everything the agents layer persists -- the state store, an agent's settings JSON,
an agent's config TOML -- is a file another process (the agent itself) reads
concurrently. A partial write would hand that reader a truncated document, so
every write goes through :func:`atomic_write_text`: a sibling temp file, an
``fsync``, and an ``os.replace`` (atomic within a filesystem).
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import tempfile


def atomic_write_text(path: pathlib.Path, content: str) -> None:
    """Write *content* to *path* atomically, creating parent directories.

    No partial file ever survives a crash: the bytes land in a sibling temp file
    that is flushed and ``fsync``'d, then renamed over *path* in one step. The
    temp file is removed if anything raises.

    Parameters
    ----------
    path : pathlib.Path
        Destination file.
    content : str
        Full UTF-8 text to write.

    Examples
    --------
    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     target = pathlib.Path(d) / "nested" / "state.json"
    ...     atomic_write_text(target, '{"agents": {}}')
    ...     target.read_text()
    '{"agents": {}}'
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        pathlib.Path(tmp).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            pathlib.Path(tmp).unlink()
        raise
