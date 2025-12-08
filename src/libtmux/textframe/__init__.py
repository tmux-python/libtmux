"""TextFrame - ASCII terminal frame simulator with pytest/syrupy integration."""

from __future__ import annotations

from libtmux.textframe.core import ContentOverflowError, TextFrame

__all__ = ["ContentOverflowError", "TextFrame"]

# Conditionally export TextFrameExtension when syrupy is available
try:
    from libtmux.textframe.plugin import TextFrameExtension

    __all__.append("TextFrameExtension")
except ImportError:
    pass
