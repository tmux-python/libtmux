"""Tests for libtmux engine resolution and protocol registry helpers."""

from __future__ import annotations

from libtmux.engines import (
    available_imsg_protocol_versions,
    create_engine,
    create_imsg_protocol,
)
from libtmux.engines.imsg import ImsgEngine
from libtmux.engines.subprocess import SubprocessEngine


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
