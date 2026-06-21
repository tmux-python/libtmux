"""A name-keyed registry of engine factories.

Lets engines be created by name (or :class:`~.base.EngineSpec`) so downstream
code and the contract suite can select a transport without importing its class.
Fails closed on an unknown name. Adapted from the ``libtmux-protocol-engines``
prototype.
"""

from __future__ import annotations

import typing as t

from libtmux import exc
from libtmux.experimental.engines.base import EngineKind
from libtmux.experimental.engines.concrete import ConcreteEngine
from libtmux.experimental.engines.subprocess import SubprocessEngine

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import TmuxEngine

EngineFactory = t.Callable[..., "TmuxEngine"]

_engine_registry: dict[str, EngineFactory] = {}


def register_engine(name: str, factory: EngineFactory) -> None:
    """Register an engine factory under a name."""
    _engine_registry[name] = factory


def available_engines() -> tuple[str, ...]:
    """Return registered engine names, sorted.

    Examples
    --------
    >>> from libtmux.experimental.engines import available_engines
    >>> "concrete" in available_engines()
    True
    >>> "subprocess" in available_engines()
    True
    """
    return tuple(sorted(_engine_registry))


def create_engine(name: str | EngineKind, **kwargs: t.Any) -> TmuxEngine:
    """Instantiate a registered engine by name (fail closed).

    Examples
    --------
    >>> from libtmux.experimental.engines import create_engine
    >>> create_engine("concrete")
    <libtmux.experimental.engines.concrete.ConcreteEngine object at ...>
    >>> create_engine("nope")
    Traceback (most recent call last):
    ...
    libtmux.exc.LibTmuxException: unknown tmux engine: nope
    """
    engine_name = name.value if isinstance(name, EngineKind) else name
    try:
        factory = _engine_registry[engine_name]
    except KeyError as error:
        msg = f"unknown tmux engine: {engine_name}"
        raise exc.LibTmuxException(msg) from error
    return factory(**kwargs)


register_engine(EngineKind.SUBPROCESS.value, SubprocessEngine)
register_engine(EngineKind.CONCRETE.value, ConcreteEngine)
