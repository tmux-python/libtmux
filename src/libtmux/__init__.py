"""libtmux, a typed, pythonic API wrapper for the tmux terminal multiplexer."""

from __future__ import annotations

import logging

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
from .client import Client
from .discovery import DiscoveredServer, DiscoveryDiagnostic, DiscoveryResult
from .lifecycle import (
    AmbiguousMatch,
    CreationCleanupError,
    FoundOrCreated,
    Owned,
    OwnedIdentity,
    UnknownCreation,
)
from .pane import Pane
from .server import Server
from .session import Session
from .window import Window

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = (
    "AmbiguousMatch",
    "Client",
    "CreationCleanupError",
    "DiscoveredServer",
    "DiscoveryDiagnostic",
    "DiscoveryResult",
    "FoundOrCreated",
    "Owned",
    "OwnedIdentity",
    "Pane",
    "Server",
    "Session",
    "UnknownCreation",
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
