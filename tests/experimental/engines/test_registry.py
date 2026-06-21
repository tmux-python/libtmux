"""Tests for the engine registry and EngineKind/EngineSpec."""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc
from libtmux.experimental.engines import (
    EngineKind,
    EngineSpec,
    available_engines,
    create_engine,
)


def test_available_engines_are_registered() -> None:
    """The registry exposes exactly the constructable (sync) engine kinds."""
    assert set(available_engines()) == {
        "subprocess",
        "concrete",
        "control_mode",
        "imsg",
    }


def test_asyncio_kind_removed() -> None:
    """The unwired ``asyncio`` kind/spec is gone; async engines are direct-ctor."""
    assert "asyncio" not in {kind.value for kind in EngineKind}
    assert not hasattr(EngineSpec, "asyncio")


class CreateCase(t.NamedTuple):
    """A registered engine name that ``create_engine`` should build."""

    test_id: str
    name: str


CREATE_CASES = (
    CreateCase("subprocess", "subprocess"),
    CreateCase("concrete", "concrete"),
    CreateCase("control_mode", "control_mode"),
)


@pytest.mark.parametrize(
    list(CreateCase._fields),
    CREATE_CASES,
    ids=[c.test_id for c in CREATE_CASES],
)
def test_create_engine_builds_registered(test_id: str, name: str) -> None:
    """create_engine returns an engine with the run/run_batch protocol."""
    engine = create_engine(name)
    assert hasattr(engine, "run")
    assert hasattr(engine, "run_batch")


def test_create_engine_unknown_fails() -> None:
    """An unregistered name (incl. the removed 'asyncio') fails closed."""
    with pytest.raises(exc.LibTmuxException, match="unknown tmux engine"):
        create_engine("asyncio")
