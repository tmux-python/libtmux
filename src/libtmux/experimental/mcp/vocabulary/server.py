"""Server-scope vocabulary: list clients, display-message, and the raw escape hatch."""

from __future__ import annotations

from libtmux.experimental.engines.base import AsyncTmuxEngine, CommandRequest
from libtmux.experimental.mcp.target_resolver import resolve_target
from libtmux.experimental.mcp.vocabulary._bridge import synced
from libtmux.experimental.mcp.vocabulary._results import Listing, MessageText, RawResult
from libtmux.experimental.ops import DisplayMessage, ListClients, arun
from libtmux.experimental.ops._types import Target


async def alist_clients(
    engine: AsyncTmuxEngine,
    *,
    version: str | None = None,
) -> Listing:
    """List attached clients (``list-clients``)."""
    result = await arun(ListClients(), engine, version=version)
    result.raise_for_status()
    return Listing(rows=result.rows)


async def adisplay_message(
    engine: AsyncTmuxEngine,
    target: str | Target,
    message: str,
    *,
    version: str | None = None,
) -> MessageText:
    """Expand a tmux format string against *target* (``display-message -p``)."""
    result = await arun(
        DisplayMessage(target=resolve_target(target), message=message),
        engine,
        version=version,
    )
    result.raise_for_status()
    return MessageText(text=result.text)


async def arun_tmux(
    engine: AsyncTmuxEngine,
    args: list[str],
    *,
    version: str | None = None,
) -> RawResult:
    """Run an arbitrary tmux command (the guarded raw escape hatch).

    Returns the structured outcome without raising on a tmux-side failure -- a
    nonzero exit or stderr is reported in :class:`~._results.RawResult`. This is
    deliberately *not* read-only; servers exposed on a network transport should
    gate it more strictly than local ones.

    Examples
    --------
    >>> from libtmux.experimental.engines import MockEngine
    >>> run_tmux(MockEngine(), ["list-sessions"]).ok
    True
    """
    raw = await engine.run(CommandRequest.from_args(*args))
    return RawResult(
        ok=raw.returncode == 0 and not raw.stderr,
        returncode=raw.returncode,
        stdout=tuple(raw.stdout),
        stderr=tuple(raw.stderr),
    )


list_clients = synced(alist_clients)
display_message = synced(adisplay_message)
run_tmux = synced(arun_tmux)
