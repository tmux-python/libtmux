"""Wait for a freshly created pane's shell to draw its prompt.

tmux returns a pane id the instant it forks the pane, long before the shell in it
has printed a prompt -- so a ``send-keys`` fired immediately can be swallowed. The
fix both builders use is the same: poll ``#{cursor_x},#{cursor_y}`` until the
cursor leaves the origin, then proceed.

This is a *host* step: it must run between tmux dispatches, never inside a fold,
so both drivers replay it from their plan's ``on_step`` hook (the workspace runner
through a compiled :class:`~.workspace.compiler.HostStep`, the fluent builder
through its recorded host action). Only the poll itself is shared here.
"""

from __future__ import annotations

import asyncio
import time
import typing as t

from libtmux.experimental.ops import DisplayMessage, arun, run
from libtmux.experimental.ops.plan import _resolve

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops._types import Target
    from libtmux.experimental.ops.operation import Operation

#: Pane-readiness poll budget: ~2s at a 50ms cadence (matches tmuxp's timeout).
WAIT_PANE_POLLS = 40
WAIT_PANE_INTERVAL = 0.05
CURSOR_FMT = "#{cursor_x},#{cursor_y}"


def pane_ready(cursor: str) -> bool:
    """Whether the pane's cursor has left the origin (its shell prompt drew).

    Parameters
    ----------
    cursor : str
        A ``#{cursor_x},#{cursor_y}`` reading, or ``""`` when unreadable.

    Returns
    -------
    bool

    Examples
    --------
    >>> pane_ready("2,1")
    True
    >>> pane_ready("0,0")
    False
    >>> pane_ready("")
    False
    """
    return bool(cursor) and cursor != "0,0"


def _cursor_probe(
    pane: Target,
    bindings: dict[int | tuple[int, str], str],
) -> Operation[t.Any]:
    """Build the cursor read for *pane*, resolving a forward ref against bindings."""
    return _resolve(DisplayMessage(target=pane, message=CURSOR_FMT), bindings)


def wait_pane(
    engine: TmuxEngine,
    pane: Target,
    bindings: dict[int | tuple[int, str], str],
    version: str | None = None,
) -> bool:
    """Poll *pane* until its prompt draws; return whether it did within the budget.

    Returns ``False`` on exhaustion rather than raising: a pane whose shell never
    moves the cursor (a full-screen program, a bare ``cat``) is not an error, and
    the build proceeds exactly as it did before the wait was requested.
    """
    op = _cursor_probe(pane, bindings)
    for _ in range(WAIT_PANE_POLLS):
        if pane_ready(run(op, engine, version=version).text):
            return True
        time.sleep(WAIT_PANE_INTERVAL)
    return False


async def await_pane(
    engine: AsyncTmuxEngine,
    pane: Target,
    bindings: dict[int | tuple[int, str], str],
    version: str | None = None,
) -> bool:
    """Async sibling of :func:`wait_pane` (same budget, same exhaustion contract)."""
    op = _cursor_probe(pane, bindings)
    for _ in range(WAIT_PANE_POLLS):
        result = await arun(op, engine, version=version)
        if pane_ready(result.text):
            return True
        await asyncio.sleep(WAIT_PANE_INTERVAL)
    return False
