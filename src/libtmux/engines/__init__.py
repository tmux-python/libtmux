"""Engine implementations and registry helpers for libtmux."""

from __future__ import annotations

from libtmux.engines.base import (
    CommandRequest,
    CommandResult,
    EngineKind,
    EngineLike,
    EngineSpec,
    ImsgProtocolVersion,
    TmuxEngine,
)
from libtmux.engines.imsg import ImsgEngine
from libtmux.engines.registry import (
    available_engines,
    available_imsg_protocol_versions,
    create_engine,
    create_imsg_protocol,
    register_engine,
    register_imsg_protocol,
)
from libtmux.engines.subprocess import SubprocessEngine

__all__ = (
    "CommandRequest",
    "CommandResult",
    "EngineKind",
    "EngineLike",
    "EngineSpec",
    "ImsgEngine",
    "ImsgProtocolVersion",
    "SubprocessEngine",
    "TmuxEngine",
    "available_engines",
    "available_imsg_protocol_versions",
    "create_engine",
    "create_imsg_protocol",
    "register_engine",
    "register_imsg_protocol",
)
