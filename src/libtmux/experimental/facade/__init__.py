"""Engine-typed facades over the operation spine.

The execution mode lives in the facade *type* (eager vs lazy vs async), so each
method has one statically-known return type, while the operation definitions stay
shared. The facades form a small matrix over scope x mode:

==========  ===========  ==========  ===========
scope       eager        lazy        async
==========  ===========  ==========  ===========
server      EagerServer  --          --
session     EagerSession --          --
window      EagerWindow  LazyWindow  AsyncWindow
pane        EagerPane    LazyPane    AsyncPane
==========  ===========  ==========  ===========

Eager handles execute immediately and return live handles; lazy handles record
into a :class:`~..ops.plan.LazyPlan`; async handles await an
:class:`~..engines.base.AsyncTmuxEngine`. "Control mode" is not a separate family
-- any eager/async facade bound to a ``ControlModeEngine`` already uses it. See
issue 689 for the full matrix.
"""

from __future__ import annotations

from libtmux.experimental.facade.pane import AsyncPane, EagerPane, LazyPane
from libtmux.experimental.facade.server import EagerServer
from libtmux.experimental.facade.session import EagerSession
from libtmux.experimental.facade.window import AsyncWindow, EagerWindow, LazyWindow

__all__ = (
    "AsyncPane",
    "AsyncWindow",
    "EagerPane",
    "EagerServer",
    "EagerSession",
    "EagerWindow",
    "LazyPane",
    "LazyWindow",
)
