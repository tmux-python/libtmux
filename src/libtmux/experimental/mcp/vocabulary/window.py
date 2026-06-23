"""Window-scope vocabulary: create, rename, select, move, swap, kill, list, layout."""

from __future__ import annotations

from libtmux.experimental.engines.base import AsyncTmuxEngine
from libtmux.experimental.mcp.target_resolver import resolve_target
from libtmux.experimental.mcp.vocabulary._bridge import synced
from libtmux.experimental.mcp.vocabulary._results import Listing, WindowResult
from libtmux.experimental.ops import (
    KillWindow,
    ListWindows,
    MoveWindow,
    NewWindow,
    RenameWindow,
    SelectLayout,
    SelectWindow,
    SwapWindow,
    arun,
)
from libtmux.experimental.ops._types import Target


async def acreate_window(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    name: str | None = None,
    start_directory: str | None = None,
    version: str | None = None,
) -> WindowResult:
    """Create a window in a session (mirrors ``session.new_window``).

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> w = create_window(ConcreteEngine(), "$1", name="logs")
    >>> w.window_id.startswith("@"), w.name
    (True, 'logs')
    """
    result = await arun(
        NewWindow(
            target=resolve_target(target),
            name=name,
            start_directory=start_directory,
            capture_pane=True,
        ),
        engine,
        version=version,
    )
    result.raise_for_status()
    return WindowResult(
        window_id=result.new_id or "",
        name=name,
        first_pane_id=result.first_pane_id,
    )


async def arename_window(
    engine: AsyncTmuxEngine,
    target: str | Target,
    name: str,
    *,
    version: str | None = None,
) -> None:
    """Rename a window (mirrors ``window.rename_window``)."""
    (
        await arun(
            RenameWindow(target=resolve_target(target), name=name),
            engine,
            version=version,
        )
    ).raise_for_status()


async def aselect_window(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    version: str | None = None,
) -> None:
    """Make a window active (mirrors ``window.select_window``)."""
    (
        await arun(SelectWindow(target=resolve_target(target)), engine, version=version)
    ).raise_for_status()


async def amove_window(
    engine: AsyncTmuxEngine,
    src: str | Target,
    dst: str | Target,
    *,
    version: str | None = None,
) -> None:
    """Move a window to a new index/session (``move-window``)."""
    (
        await arun(
            MoveWindow(target=resolve_target(dst), src_target=resolve_target(src)),
            engine,
            version=version,
        )
    ).raise_for_status()


async def aswap_window(
    engine: AsyncTmuxEngine,
    src: str | Target,
    dst: str | Target,
    *,
    version: str | None = None,
) -> None:
    """Swap two windows (``swap-window``)."""
    (
        await arun(
            SwapWindow(target=resolve_target(dst), src_target=resolve_target(src)),
            engine,
            version=version,
        )
    ).raise_for_status()


async def akill_window(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    others: bool = False,
    version: str | None = None,
) -> None:
    """Kill a window (or all others in its session with ``others=True``)."""
    (
        await arun(
            KillWindow(target=resolve_target(target), others=others),
            engine,
            version=version,
        )
    ).raise_for_status()


async def alist_windows(
    engine: AsyncTmuxEngine,
    target: str | Target | None = None,
    *,
    all_windows: bool = False,
    version: str | None = None,
) -> Listing:
    """List windows of a session, or all windows (mirrors ``session.windows``)."""
    result = await arun(
        ListWindows(
            target=None if target is None else resolve_target(target),
            all_windows=all_windows,
        ),
        engine,
        version=version,
    )
    result.raise_for_status()
    return Listing(rows=result.rows)


async def aselect_layout(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    layout: str | None = None,
    version: str | None = None,
) -> None:
    """Apply a layout to a window (mirrors ``window.select_layout``)."""
    (
        await arun(
            SelectLayout(target=resolve_target(target), layout=layout),
            engine,
            version=version,
        )
    ).raise_for_status()


create_window = synced(acreate_window)
rename_window = synced(arename_window)
select_window = synced(aselect_window)
move_window = synced(amove_window)
swap_window = synced(aswap_window)
kill_window = synced(akill_window)
list_windows = synced(alist_windows)
select_layout = synced(aselect_layout)
