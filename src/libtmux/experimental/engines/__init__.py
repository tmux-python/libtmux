"""Execution engines for :mod:`libtmux.experimental.ops`.

An *engine* executes a rendered tmux command and returns a structured result.
Engines are interchangeable behind the :class:`~.base.TmuxEngine` /
:class:`~.base.AsyncTmuxEngine` protocols, so the same typed operation can run
through a subprocess, a persistent ``tmux -C`` control connection, an async
transport, an in-memory simulator, or (as an easter egg) tmux's native binary
peer protocol -- and return the *same* typed result.

See the operationalization plan (``tmux-python/libtmux`` issue 689).
"""

from __future__ import annotations

from libtmux.experimental.engines.base import (
    AsyncTmuxEngine,
    CommandRequest,
    CommandResult,
    EngineKind,
    EngineSpec,
    TmuxEngine,
)

__all__ = (
    "AsyncTmuxEngine",
    "CommandRequest",
    "CommandResult",
    "EngineKind",
    "EngineSpec",
    "TmuxEngine",
)
