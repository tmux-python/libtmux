"""Paste-buffer vocabulary: set, show, paste."""

from __future__ import annotations

from libtmux.experimental.engines.base import AsyncTmuxEngine
from libtmux.experimental.mcp.target_resolver import resolve_target
from libtmux.experimental.mcp.vocabulary._bridge import synced
from libtmux.experimental.mcp.vocabulary._results import BufferText
from libtmux.experimental.ops import PasteBuffer, SetBuffer, ShowBuffer, arun
from libtmux.experimental.ops._types import Target


async def aset_buffer(
    engine: AsyncTmuxEngine,
    data: str,
    *,
    buffer_name: str | None = None,
    version: str | None = None,
) -> None:
    """Set a paste buffer's contents (``set-buffer``)."""
    (
        await arun(
            SetBuffer(data=data, buffer_name=buffer_name),
            engine,
            version=version,
        )
    ).raise_for_status()


async def ashow_buffer(
    engine: AsyncTmuxEngine,
    *,
    buffer_name: str | None = None,
    version: str | None = None,
) -> BufferText:
    """Return a paste buffer's contents (``show-buffer``)."""
    result = await arun(ShowBuffer(buffer_name=buffer_name), engine, version=version)
    result.raise_for_status()
    return BufferText(text=result.text)


async def apaste_buffer(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    buffer_name: str | None = None,
    delete: bool = False,
    version: str | None = None,
) -> None:
    """Paste a buffer into a pane (``paste-buffer``)."""
    (
        await arun(
            PasteBuffer(
                target=resolve_target(target),
                buffer_name=buffer_name,
                delete=delete,
            ),
            engine,
            version=version,
        )
    ).raise_for_status()


set_buffer = synced(aset_buffer)
show_buffer = synced(ashow_buffer)
paste_buffer = synced(apaste_buffer)
