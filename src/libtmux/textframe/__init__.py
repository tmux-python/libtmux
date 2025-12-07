"""TextFrame - ASCII terminal frame simulator with pytest/syrupy integration."""

from __future__ import annotations

from libtmux.textframe.core import ContentOverflowError, TextFrame
from libtmux.textframe.plugin import TextFrameExtension

__all__ = ["ContentOverflowError", "TextFrame", "TextFrameExtension"]
