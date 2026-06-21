"""Engine-typed facades over the operation spine.

The execution mode lives in the facade *type* (eager vs lazy vs async vs
control), so each method has one statically-known return type, while the
operation definitions stay shared. This package currently ships the pane-scope
seed (:class:`EagerPane`, :class:`LazyPane`); the full Server/Session/Window/
Pane/Client matrix is described in issue 689.
"""

from __future__ import annotations

from libtmux.experimental.facade.pane import EagerPane, LazyPane

__all__ = (
    "EagerPane",
    "LazyPane",
)
