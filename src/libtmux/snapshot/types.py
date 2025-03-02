"""Type definitions for the snapshot module.

This module centralizes type definitions for the snapshot package, including
type variables, forward references, and the SnapshotType union.
"""

from __future__ import annotations

import typing as t

from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

# Type variables for generic typing
PaneT = t.TypeVar("PaneT", bound=Pane, covariant=True)
WindowT = t.TypeVar("WindowT", bound=Window, covariant=True)
SessionT = t.TypeVar("SessionT", bound=Session, covariant=True)
ServerT = t.TypeVar("ServerT", bound=Server, covariant=True)

# Forward references for snapshot classes
if t.TYPE_CHECKING:
    from libtmux.snapshot.models.pane import PaneSnapshot
    from libtmux.snapshot.models.server import ServerSnapshot
    from libtmux.snapshot.models.session import SessionSnapshot
    from libtmux.snapshot.models.window import WindowSnapshot

    # Union type for snapshot classes
    SnapshotType = t.Union[
        ServerSnapshot, SessionSnapshot, WindowSnapshot, PaneSnapshot
    ]
else:
    # Runtime placeholder - will be properly defined after imports
    SnapshotType = t.Any
