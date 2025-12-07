"""Syrupy snapshot extension for TextFrame objects.

This module provides a single-file snapshot extension that renders TextFrame
objects and ContentOverflowError exceptions as ASCII art in .frame files.
"""

from __future__ import annotations

import typing as t

from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode

from .core import ContentOverflowError, TextFrame


class TextFrameExtension(SingleFileSnapshotExtension):
    """Single-file extension for TextFrame snapshots (.frame files).

    Each test snapshot is stored in its own .frame file, providing cleaner
    git diffs compared to the multi-snapshot .ambr format.

    Notes
    -----
    This extension serializes:
    - TextFrame objects → their render() output
    - ContentOverflowError → their overflow_visual attribute
    - Other types → str() representation
    """

    _write_mode = WriteMode.TEXT
    file_extension = "frame"

    def serialize(
        self,
        data: t.Any,
        *,
        exclude: t.Any = None,
        include: t.Any = None,
        matcher: t.Any = None,
    ) -> str:
        """Serialize data to ASCII frame representation.

        Parameters
        ----------
        data : Any
            The data to serialize.
        exclude : Any
            Properties to exclude (unused for TextFrame).
        include : Any
            Properties to include (unused for TextFrame).
        matcher : Any
            Custom matcher (unused for TextFrame).

        Returns
        -------
        str
            ASCII representation of the data.
        """
        if isinstance(data, TextFrame):
            return data.render()
        if isinstance(data, ContentOverflowError):
            return data.overflow_visual
        return str(data)
