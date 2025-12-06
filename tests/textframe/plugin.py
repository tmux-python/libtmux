"""Syrupy snapshot extension for TextFrame objects.

This module provides a custom serializer that renders TextFrame objects
and ContentOverflowError exceptions as ASCII art in snapshot files.
"""

from __future__ import annotations

import typing as t

from syrupy.extensions.amber import AmberSnapshotExtension
from syrupy.extensions.amber.serializer import AmberDataSerializer

from .core import ContentOverflowError, TextFrame


class TextFrameSerializer(AmberDataSerializer):
    """Custom serializer that renders TextFrame objects as ASCII frames.

    This serializer intercepts TextFrame and ContentOverflowError objects,
    converting them to their ASCII representation before passing them
    to the base serializer for formatting.

    Notes
    -----
    By subclassing AmberDataSerializer, we ensure TextFrame objects are
    correctly rendered even when nested inside lists, dicts, or other
    data structures.
    """

    @classmethod
    def _serialize(
        cls,
        data: t.Any,
        *,
        depth: int = 0,
        **kwargs: t.Any,
    ) -> str:
        """Serialize data, converting TextFrame objects to ASCII.

        Parameters
        ----------
        data : Any
            The data to serialize.
        depth : int
            Current indentation depth.
        **kwargs : Any
            Additional serialization options.

        Returns
        -------
        str
            Serialized representation.
        """
        # Intercept TextFrame: Render it to ASCII
        if isinstance(data, TextFrame):
            return super()._serialize(data.render(), depth=depth, **kwargs)

        # Intercept ContentOverflowError: Render the visual diff
        if isinstance(data, ContentOverflowError):
            return super()._serialize(data.overflow_visual, depth=depth, **kwargs)

        # Default behavior for all other types
        return super()._serialize(data, depth=depth, **kwargs)


class TextFrameExtension(AmberSnapshotExtension):
    """Syrupy extension that uses the TextFrameSerializer."""

    serializer_class = TextFrameSerializer
