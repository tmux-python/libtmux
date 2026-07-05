"""Sync bridge: drive one async tool body over a synchronous engine.

The curated vocabulary is written once as ``async def`` over an
:class:`~libtmux.experimental.engines.base.AsyncTmuxEngine` (the canonical,
"async-first" surface). A synchronous twin is *derived* -- not hand-written --
by :func:`synced`, which wraps a plain :class:`~..engines.base.TmuxEngine` in the
async protocol (:class:`SyncToAsyncEngine`) and drives the coroutine to
completion with a sans-I/O trampoline (:func:`drive_sync`).

This is sound because every curated tool's only ``await`` is a single
``arun(op, engine)`` -- and the wrapped sync engine's ``run`` returns inline,
never suspending on a real :class:`asyncio.Future`. The trampoline therefore
runs the whole coroutine in one ``send(None)``, needing no event loop, and works
even when called from inside a running loop. A tool that *does* suspend (the
event stream) has no sync twin and raises here, by design.
"""

from __future__ import annotations

import functools
import inspect
import typing as t

# Imported at runtime (not under TYPE_CHECKING) so the derived sync twin's
# ``engine`` annotation resolves when the fastmcp adapter calls get_type_hints().
from libtmux.experimental.engines.base import TmuxEngine

if t.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from libtmux.experimental.engines.base import CommandRequest, CommandResult

R = t.TypeVar("R")


class SyncToAsyncEngine:
    """Adapt a synchronous :class:`TmuxEngine` to the async engine protocol.

    Each ``await`` resolves inline (the underlying call is synchronous), so a
    coroutine awaiting only this adapter never yields to an event loop.

    Examples
    --------
    >>> from libtmux.experimental.engines import MockEngine
    >>> bridge = SyncToAsyncEngine(MockEngine())
    >>> hasattr(bridge, "run") and hasattr(bridge, "run_batch")
    True
    """

    def __init__(self, engine: TmuxEngine) -> None:
        self._engine = engine

    def __getattr__(self, name: str) -> t.Any:
        """Delegate unknown attributes to the wrapped engine.

        Keeps the wrapper transparent for the attributes the vocabulary reads off
        an engine -- ``server_args`` (socket scoping) and the stashed
        ``_caller_context`` -- so the sync surface sees the same identity the
        async surface does.
        """
        return getattr(self._engine, name)

    async def run(self, request: CommandRequest) -> CommandResult:
        """Run one command on the wrapped sync engine (resolves inline)."""
        return self._engine.run(request)

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Run a batch on the wrapped sync engine (resolves inline)."""
        return self._engine.run_batch(requests)


def drive_sync(coro: Awaitable[R]) -> R:
    """Run *coro* to completion synchronously, without an event loop.

    Works only for coroutines whose awaits never suspend on a real future
    (the curated tools, driven over a :class:`SyncToAsyncEngine`).

    Raises
    ------
    RuntimeError
        If the coroutine suspends on real I/O -- use the async surface instead.
    """
    runner = t.cast("t.Coroutine[t.Any, t.Any, R]", coro)
    try:
        runner.send(None)
    except StopIteration as stop:
        return t.cast("R", stop.value)
    runner.close()
    msg = "sync bridge: tool awaited real I/O; call it on the async surface"
    raise RuntimeError(msg)


def synced(afn: Callable[..., Awaitable[R]]) -> Callable[..., R]:
    """Derive a synchronous twin of an async tool ``afn(engine, ...)``.

    The twin takes a sync :class:`TmuxEngine`, wraps it as async, and drives the
    same coroutine to completion -- so each tool's logic is written exactly once.
    """
    hints = t.get_type_hints(afn)
    signature = inspect.signature(afn)

    @functools.wraps(afn)
    def wrapper(engine: TmuxEngine, *args: t.Any, **kwargs: t.Any) -> R:
        return drive_sync(afn(SyncToAsyncEngine(engine), *args, **kwargs))

    twin_hints = dict(hints)
    twin_hints["engine"] = TmuxEngine
    wrapper.__annotations__ = twin_hints
    wrapper.__signature__ = signature  # type: ignore[attr-defined]
    return wrapper
