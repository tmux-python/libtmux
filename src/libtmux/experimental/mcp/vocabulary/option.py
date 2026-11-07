"""Option vocabulary: show and set tmux options."""

from __future__ import annotations

from libtmux.experimental.engines.base import AsyncTmuxEngine
from libtmux.experimental.mcp.vocabulary._bridge import synced
from libtmux.experimental.mcp.vocabulary._resolve import opt_target
from libtmux.experimental.mcp.vocabulary._results import OptionMap
from libtmux.experimental.ops import SetOption, ShowOptions, arun
from libtmux.experimental.ops._types import Target


async def ashow_options(
    engine: AsyncTmuxEngine,
    target: str | Target | None = None,
    *,
    global_: bool = False,
    server: bool = False,
    window: bool = False,
    version: str | None = None,
) -> OptionMap:
    """Show tmux options as ``name -> value`` pairs (``show-options``)."""
    result = await arun(
        ShowOptions(
            target=opt_target(target),
            global_=global_,
            server=server,
            window=window,
        ),
        engine,
        version=version,
    )
    result.raise_for_status()
    return OptionMap(options=result.options)


async def aset_option(
    engine: AsyncTmuxEngine,
    option: str,
    value: str | None = None,
    target: str | Target | None = None,
    *,
    global_: bool = False,
    server: bool = False,
    window: bool = False,
    unset: bool = False,
    version: str | None = None,
) -> None:
    """Set (or unset) a tmux option (``set-option``)."""
    (
        await arun(
            SetOption(
                target=opt_target(target),
                option=option,
                value=value,
                global_=global_,
                server=server,
                window=window,
                unset=unset,
            ),
            engine,
            version=version,
        )
    ).raise_for_status()


show_options = synced(ashow_options)
set_option = synced(aset_option)
