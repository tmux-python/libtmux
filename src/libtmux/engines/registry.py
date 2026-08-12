"""Resolve engines by name, so a caller can pick one from configuration.

An application that reads its tmux transport from a config file or a CLI flag
should not have to import the class that implements it. :func:`create_engine`
maps a name to a factory, and the ``libtmux.engines`` entry-point group lets a
third-party distribution add a name without libtmux knowing about it -- the same
shape tmuxp uses for workspace builders.

Entry points are read on first use rather than at import. Scanning installed
distributions costs a few milliseconds, which is a meaningful fraction of
importing libtmux at all, and most programs never resolve an engine by name.
"""

from __future__ import annotations

import typing as t
from importlib import metadata

from libtmux import exc
from libtmux.engines.record import ReplayEngine
from libtmux.engines.subprocess import SubprocessEngine

if t.TYPE_CHECKING:
    from libtmux.engines.base import TmuxEngine

ENGINE_ENTRY_POINT_GROUP = "libtmux.engines"
"""Entry-point group a packaged engine registers under."""

EngineFactory = t.Callable[..., "TmuxEngine"]

_registry: dict[str, EngineFactory] = {}
_entry_points_loaded = False


def register_engine(name: str, factory: EngineFactory) -> None:
    """Register *factory* under *name*, replacing any previous registration.

    Parameters
    ----------
    name : str
        The name :func:`create_engine` will accept.
    factory : Callable[..., TmuxEngine]
        Called with whatever keyword arguments :func:`create_engine` is given.
        An engine class is usually its own factory.

    Examples
    --------
    >>> from libtmux.engines import CommandResult, available_engines, register_engine
    >>> class NullEngine:
    ...     def run(self, request):
    ...         return CommandResult(cmd=("tmux", *request.args))
    ...     def run_batch(self, requests):
    ...         return [self.run(r) for r in requests]
    >>> register_engine("null-doc", NullEngine)
    >>> "null-doc" in available_engines()
    True
    >>> unregister_engine("null-doc")
    """
    _registry[name] = factory


def unregister_engine(name: str) -> None:
    """Remove a registration, failing closed on an unknown name.

    Parameters
    ----------
    name : str
        A registered engine name.

    Raises
    ------
    :exc:`~libtmux.exc.LibTmuxException`
        Nothing is registered under *name*.

    Examples
    --------
    >>> from libtmux.engines import unregister_engine
    >>> unregister_engine("never-registered")
    Traceback (most recent call last):
    ...
    libtmux.exc.LibTmuxException: unknown tmux engine 'never-registered'
    (registered: ...)
    """
    _load_entry_points()
    if name not in _registry:
        raise exc.LibTmuxException(_unknown_message(name))
    del _registry[name]


def _unknown_message(name: str) -> str:
    """Build an error naming what the caller could have said instead."""
    known = ", ".join(available_engines()) or "none"
    return f"unknown tmux engine {name!r} (registered: {known})"


def _load_entry_points() -> None:
    """Read the entry-point group once, on first use.

    A distribution that advertises a broken engine should not make every other
    engine unresolvable, so a failed load is skipped rather than raised. An
    explicit :func:`register_engine` always wins over an entry point of the same
    name.
    """
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True
    for entry_point in metadata.entry_points(group=ENGINE_ENTRY_POINT_GROUP):
        if entry_point.name in _registry:
            continue
        try:
            _registry[entry_point.name] = entry_point.load()
        except Exception:  # noqa: BLE001 - a third party's import is not ours to trust
            continue


def available_engines() -> tuple[str, ...]:
    """Return every registered engine name, sorted.

    Returns
    -------
    tuple[str, ...]
        Built-in names plus any contributed through the entry-point group.

    Examples
    --------
    >>> from libtmux.engines import available_engines
    >>> "subprocess" in available_engines()
    True
    """
    _load_entry_points()
    return tuple(sorted(_registry))


def create_engine(name: str, **kwargs: t.Any) -> TmuxEngine:
    """Build the engine registered under *name*.

    Parameters
    ----------
    name : str
        A name from :func:`available_engines`.
    **kwargs : typing.Any
        Passed through to the factory.

    Returns
    -------
    :class:`~libtmux.engines.base.TmuxEngine`
        A new engine.

    Raises
    ------
    :exc:`~libtmux.exc.LibTmuxException`
        No engine is registered under *name*. The message lists what is.

    Examples
    --------
    >>> from libtmux.engines import SubprocessEngine, create_engine
    >>> isinstance(create_engine("subprocess"), SubprocessEngine)
    True
    >>> create_engine("subprocess", server_args=("-Lwork",)).server_args
    ('-Lwork',)
    >>> create_engine("nope")
    Traceback (most recent call last):
    ...
    libtmux.exc.LibTmuxException: unknown tmux engine 'nope' (registered: ...)
    """
    _load_entry_points()
    try:
        factory = _registry[name]
    except KeyError:
        raise exc.LibTmuxException(_unknown_message(name)) from None
    return factory(**kwargs)


register_engine("subprocess", SubprocessEngine.of)
register_engine("replay", ReplayEngine)
