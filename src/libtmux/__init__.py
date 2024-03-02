"""libtmux, a typed, pythonic API wrapper for the tmux terminal multiplexer."""

from .__about__ import (
    __author__,
    __copyright__,
    __description__,
    __email__,
    __license__,
    __package_name__,
    __title__,
    __version__,
)
from .pane import Pane
from .server import Server
from .session import Session
from .window import Window

__all__ = (
    "Pane",
    "Server",
    "Session",
    "Window",
    "__author__",
    "__copyright__",
    "__description__",
    "__email__",
    "__license__",
    "__package_name__",
    "__title__",
    "__version__",
)
