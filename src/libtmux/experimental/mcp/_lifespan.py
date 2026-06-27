"""Engine-probe lifespan for the async MCP server.

A startup preflight that fails fast if the engine cannot reach tmux at all
(missing binary, a fundamentally broken connection) -- distinct from a tmux-side
error such as "no server running", which the engine returns as data, not an
exception. Shutdown is a best-effort no-op: engine-ops does not namespace
MCP-created paste buffers, so there is no buffer GC to run (a documented
follow-up).
"""

from __future__ import annotations

import contextlib
import typing as t

from libtmux.experimental.engines.base import CommandRequest

if t.TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from fastmcp import FastMCP

    from libtmux.experimental.engines.base import AsyncTmuxEngine


def make_lifespan(
    engine: AsyncTmuxEngine,
) -> Callable[[FastMCP], contextlib.AbstractAsyncContextManager[None]]:
    """Return a FastMCP lifespan that probes *engine* at startup.

    The probe runs ``list-sessions`` over *engine* and raises ``RuntimeError``
    only when the engine itself is broken (it raises -- missing binary, lost
    connection), never on a tmux-side failure, which comes back as a
    :class:`~..engines.base.CommandResult`.
    """

    @contextlib.asynccontextmanager
    async def _lifespan(_app: FastMCP) -> AsyncIterator[None]:
        try:
            await engine.run(CommandRequest.from_args("list-sessions"))
        except Exception as error:
            msg = f"tmux engine preflight failed: {error}"
            raise RuntimeError(msg) from error
        yield

    return _lifespan
