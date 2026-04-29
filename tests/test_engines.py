"""Tests for libtmux engine resolution and protocol registry helpers."""

from __future__ import annotations

from libtmux.common import resolve_engine, resolve_engine_spec
from libtmux.engines import (
    EngineKind,
    EngineSpec,
    ImsgProtocolVersion,
    available_engines,
    available_imsg_protocol_versions,
    create_engine,
    create_imsg_protocol,
)
from libtmux.engines.imsg import ImsgEngine
from libtmux.engines.subprocess import SubprocessEngine


def test_engine_spec_subprocess_constructor() -> None:
    """Typed subprocess specs have no protocol version."""
    assert EngineSpec.subprocess() == EngineSpec(kind=EngineKind.SUBPROCESS)


def test_engine_spec_imsg_constructor() -> None:
    """Typed imsg specs preserve the requested protocol version."""
    assert EngineSpec.imsg(ImsgProtocolVersion.V8) == EngineSpec(
        kind=EngineKind.IMSG,
        protocol_version=8,
    )


def test_available_engines_lists_registered_backends() -> None:
    """The engine registry exposes the installed backend names."""
    assert available_engines() == ("imsg", "subprocess")


def test_create_subprocess_engine() -> None:
    """Named engine creation returns the subprocess backend."""
    engine = create_engine("subprocess")
    assert isinstance(engine, SubprocessEngine)


def test_create_imsg_engine_with_protocol_version() -> None:
    """Named engine creation returns the imsg backend with the requested version."""
    engine = create_engine("imsg", protocol_version="8")
    assert isinstance(engine, ImsgEngine)
    assert engine.protocol_version == "8"


def test_imsg_protocol_registry_defaults_to_latest() -> None:
    """The imsg protocol registry resolves to the highest registered version."""
    protocol = create_imsg_protocol()
    assert protocol.version == available_imsg_protocol_versions()[-1]


def test_imsg_protocol_registry_resolves_v8() -> None:
    """Protocol version 8 is available through the typed registry."""
    protocol = create_imsg_protocol("8")
    assert protocol.version == "8"


def test_resolve_engine_from_engine_spec() -> None:
    """Typed engine specs resolve to concrete backend instances."""
    engine = resolve_engine(EngineSpec.imsg(ImsgProtocolVersion.V8))
    assert isinstance(engine, ImsgEngine)
    assert engine.protocol_version == "8"


def test_resolve_engine_spec_from_engine_spec() -> None:
    """Typed engine specs round-trip through normalization unchanged."""
    spec = EngineSpec.imsg(ImsgProtocolVersion.V8)
    assert resolve_engine_spec(spec) == spec
