"""Engine-typed facades over the operation spine.

The execution mode lives in the facade *type* (eager vs lazy vs async), so each
method has one statically-known return type, while the operation definitions stay
shared. The matrix over scope x mode:

==========  ============  ============  ============
scope       eager         lazy          async
==========  ============  ============  ============
server      EagerServer   LazyServer    AsyncServer
session     EagerSession  LazySession   AsyncSession
window      EagerWindow   LazyWindow    AsyncWindow
pane        EagerPane     LazyPane      AsyncPane
client      EagerClient   LazyClient    AsyncClient
==========  ============  ============  ============

Eager handles execute immediately and return live handles; lazy handles record
into a :class:`~..ops.plan.LazyPlan`; async handles await an
:class:`~..engines.base.AsyncTmuxEngine`. "Control mode" is not a separate family
-- any eager/async facade bound to a ``ControlModeEngine`` already uses it.
"""

from __future__ import annotations

from libtmux.experimental.facade.client import AsyncClient, EagerClient, LazyClient
from libtmux.experimental.facade.pane import AsyncPane, EagerPane, LazyPane
from libtmux.experimental.facade.server import AsyncServer, EagerServer, LazyServer
from libtmux.experimental.facade.session import (
    AsyncSession,
    EagerSession,
    LazySession,
)
from libtmux.experimental.facade.window import AsyncWindow, EagerWindow, LazyWindow

__all__ = (
    "AsyncClient",
    "AsyncPane",
    "AsyncServer",
    "AsyncSession",
    "AsyncWindow",
    "EagerClient",
    "EagerPane",
    "EagerServer",
    "EagerSession",
    "EagerWindow",
    "LazyClient",
    "LazyPane",
    "LazyServer",
    "LazySession",
    "LazyWindow",
)
