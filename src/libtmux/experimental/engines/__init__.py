"""Execution engines for :mod:`libtmux.experimental.ops`.

An *engine* executes a rendered tmux command and returns a structured result.
Engines are interchangeable behind the :class:`~.base.TmuxEngine` /
:class:`~.base.AsyncTmuxEngine` protocols, so the same typed operation can run
through a subprocess (classic), an in-memory simulator (concrete), a persistent
``tmux -C`` control connection, an async transport, or (as an easter egg) tmux's
native binary peer protocol -- and return the *same* typed result.

See the operationalization plan (``tmux-python/libtmux`` issue 689).
"""

from __future__ import annotations

from libtmux.experimental.engines.asyncio import AsyncSubprocessEngine
from libtmux.experimental.engines.base import (
    AsyncTmuxEngine,
    CommandRequest,
    CommandResult,
    EngineKind,
    EngineSpec,
    TmuxEngine,
)
from libtmux.experimental.engines.concrete import ConcreteEngine
from libtmux.experimental.engines.registry import (
    available_engines,
    create_engine,
    register_engine,
)
from libtmux.experimental.engines.subprocess import SubprocessEngine

__all__ = (
    "AsyncSubprocessEngine",
    "AsyncTmuxEngine",
    "CommandRequest",
    "CommandResult",
    "ConcreteEngine",
    "EngineKind",
    "EngineSpec",
    "SubprocessEngine",
    "TmuxEngine",
    "available_engines",
    "create_engine",
    "register_engine",
)
