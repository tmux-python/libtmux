"""Engine-typed tmux objects over the operation spine.

Each class binds an engine + a tmux id and exposes a curated, ergonomic method
set. The objects are the domain-shaped layer over the Core ``Operation``/engine
spine: the same server/session/window/pane/client nouns as tmux, with the
execution mode carried by the class.

The execution mode lives in the object *type* (eager vs lazy vs async), so each
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

Eager objects execute immediately and return live objects; lazy objects record
into a :class:`~..ops.plan.LazyPlan`; async objects await an
:class:`~..engines.base.AsyncTmuxEngine`. "Control mode" is not a separate family
-- any eager/async object bound to a ``ControlModeEngine`` already uses it.
"""

from __future__ import annotations

from libtmux.experimental.objects.client import AsyncClient, EagerClient, LazyClient
from libtmux.experimental.objects.pane import AsyncPane, EagerPane, LazyPane
from libtmux.experimental.objects.server import AsyncServer, EagerServer, LazyServer
from libtmux.experimental.objects.session import (
    AsyncSession,
    EagerSession,
    LazySession,
)
from libtmux.experimental.objects.window import AsyncWindow, EagerWindow, LazyWindow

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
