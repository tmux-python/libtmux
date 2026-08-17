"""Engine-probe lifespan for the async MCP server.

A startup preflight that fails fast if the engine cannot reach tmux at all
(missing binary, a fundamentally broken connection) -- distinct from a tmux-side
error such as "no server running", which the engine returns as data, not an
exception. The lifespan also closes engines whose ownership was explicitly
transferred to the server. Injected engines remain borrowed by default.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import sys
import typing as t

from libtmux.experimental.engines.base import CommandRequest

if t.TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from fastmcp import FastMCP

    from libtmux.experimental.engines.base import AsyncTmuxEngine


class EngineOwnership(str, enum.Enum):
    """Whether the async MCP server borrows or owns its engine.

    ``BORROWED`` leaves shutdown to the caller that supplied the engine.
    ``OWNED`` closes it exactly once when the server lifespan exits.

    Examples
    --------
    >>> EngineOwnership.BORROWED.value
    'borrowed'
    >>> EngineOwnership.OWNED.value
    'owned'
    """

    BORROWED = "borrowed"
    OWNED = "owned"


@t.runtime_checkable
class _SupportsAsyncClose(t.Protocol):
    """An engine with asynchronous lifecycle cleanup."""

    async def aclose(self) -> None:
        """Close the engine."""
        ...


async def _drain_aclose(
    closer: _SupportsAsyncClose,
) -> tuple[BaseException | None, asyncio.CancelledError | None]:
    """Run ``aclose()`` once and drain it through caller cancellation.

    Returns the close failure, if any, and the first caller cancellation caught
    while cleanup was pending. The caller decides which exception remains
    primary after cleanup finishes.

    Returns
    -------
    tuple[BaseException | None, asyncio.CancelledError | None]
        Cleanup failure and delayed caller cancellation, respectively.
    """
    close_task = asyncio.create_task(
        closer.aclose(),
        name="libtmux-mcp-engine-close",
    )
    cancellation: asyncio.CancelledError | None = None
    while not close_task.done():
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError as error:  # noqa: PERF203 - drain each cancel
            if not close_task.cancelled() and cancellation is None:
                cancellation = error
        except Exception:
            if close_task.done():
                break
            raise

    try:
        close_task.result()
    except asyncio.CancelledError as error:
        return error, cancellation
    except Exception as error:  # noqa: BLE001 - preserve cleanup failure as cause
        return error, cancellation
    return None, cancellation


def make_lifespan(
    engine: AsyncTmuxEngine,
    *,
    ownership: EngineOwnership = EngineOwnership.BORROWED,
) -> Callable[[FastMCP], contextlib.AbstractAsyncContextManager[None]]:
    """Return a FastMCP lifespan that probes and conditionally closes *engine*.

    The probe runs ``list-sessions`` over *engine* and raises ``RuntimeError``
    only when the engine itself is broken (it raises -- missing binary, lost
    connection), never on a tmux-side failure, which comes back as a
    :class:`~..engines.base.CommandResult`. An ``OWNED`` engine must provide
    ``aclose()`` and is closed exactly once after startup begins. Cleanup is
    drained through repeated caller cancellation. A close failure propagates
    after a clean server body; if a body exception or cancellation is already
    in flight, that original exception remains primary and the close failure is
    chained as its cause.
    """
    ownership = EngineOwnership(ownership)
    closer: _SupportsAsyncClose | None = None
    if ownership is EngineOwnership.OWNED:
        if not isinstance(engine, _SupportsAsyncClose):
            msg = "an owned async MCP engine must provide aclose()"
            raise TypeError(msg)
        closer = engine

    @contextlib.asynccontextmanager
    async def _lifespan(_app: FastMCP) -> AsyncIterator[None]:
        async def probe() -> None:
            try:
                await engine.run(CommandRequest.from_args("list-sessions"))
            except Exception as error:
                msg = f"tmux engine preflight failed: {error}"
                raise RuntimeError(msg) from error

        if closer is None:
            await probe()
            yield
            return

        try:
            await probe()
            yield
        finally:
            primary_error = sys.exc_info()[1]
            close_error, close_cancellation = await _drain_aclose(closer)
            if primary_error is not None:
                if close_error is not None:
                    raise primary_error from close_error
            elif close_cancellation is not None:
                if close_error is not None and close_error is not close_cancellation:
                    raise close_cancellation from close_error
                raise close_cancellation
            elif close_error is not None:
                raise close_error

    return _lifespan
