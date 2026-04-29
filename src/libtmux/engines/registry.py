"""Engine and protocol registries for libtmux."""

from __future__ import annotations

import typing as t

from libtmux import exc
from libtmux.engines.base import EngineKind, TmuxEngine

if t.TYPE_CHECKING:
    from libtmux.engines.imsg.base import ImsgProtocolCodec

EngineFactory = t.Callable[..., TmuxEngine]
ProtocolFactory = t.Callable[[], "ImsgProtocolCodec"]

_engine_registry: dict[str, EngineFactory] = {}
_imsg_protocol_registry: dict[str, ProtocolFactory] = {}


def register_engine(name: str, factory: EngineFactory) -> None:
    """Register an engine factory by name."""
    _engine_registry[name] = factory


def available_engines() -> tuple[str, ...]:
    """Return registered engine names sorted alphabetically."""
    return tuple(sorted(_engine_registry))


def create_engine(
    name: str | EngineKind,
    *,
    protocol_version: str | int | None = None,
) -> TmuxEngine:
    """Instantiate a named engine from the registry."""
    engine_name = name.value if isinstance(name, EngineKind) else name
    try:
        factory = _engine_registry[engine_name]
    except KeyError as error:
        msg = f"Unknown tmux engine: {engine_name}"
        raise exc.LibTmuxException(msg) from error
    if engine_name == EngineKind.IMSG.value:
        return factory(protocol_version=protocol_version)
    return factory()


def register_imsg_protocol(version: str | int, factory: ProtocolFactory) -> None:
    """Register an imsg protocol implementation."""
    _imsg_protocol_registry[str(version)] = factory


def available_imsg_protocol_versions() -> tuple[str, ...]:
    """Return registered imsg protocol versions sorted numerically."""
    return tuple(sorted(_imsg_protocol_registry, key=int))


def create_imsg_protocol(version: str | int | None = None) -> ImsgProtocolCodec:
    """Instantiate a registered imsg protocol implementation."""
    if not _imsg_protocol_registry:
        engine_name = "imsg"
        raise exc.UnsupportedProtocolVersion(engine_name, "none")

    resolved = (
        str(version) if version is not None else available_imsg_protocol_versions()[-1]
    )
    try:
        factory = _imsg_protocol_registry[resolved]
    except KeyError as error:
        engine_name = "imsg"
        raise exc.UnsupportedProtocolVersion(engine_name, resolved) from error
    return factory()
