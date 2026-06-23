"""Optional fastmcp adapter -- expose the curated vocabulary on a FastMCP server.

This is the thin, framework-specific edge. It requires the ``mcp`` extra
(``pip install libtmux[mcp]``); fastmcp is imported lazily so the rest of
:mod:`libtmux.experimental.mcp` stays dependency-free. The agent-facing ``engine``
is bound out of each tool's schema with :func:`functools.partial`, and the safety
tier becomes the tool's ``ToolAnnotations`` + tag.

Examples
--------
>>> import asyncio
>>> from fastmcp import Client  # doctest: +SKIP
>>> from libtmux.experimental.engines import ConcreteEngine
>>> server = build_server(ConcreteEngine())  # doctest: +SKIP
>>> async def main():  # doctest: +SKIP
...     async with Client(server) as client:
...         return (await client.call_tool("create_session", {"name": "dev"})).data
>>> asyncio.run(main())  # doctest: +SKIP
"""

from __future__ import annotations

import inspect
import typing as t

from libtmux.experimental.mcp import vocabulary

if t.TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

    from libtmux.experimental.engines.base import TmuxEngine

# (function, safety tier) -- every curated tool takes ``engine`` as its first arg.
_VOCABULARY: tuple[tuple[Callable[..., t.Any], str], ...] = (
    (vocabulary.create_session, "mutating"),
    (vocabulary.create_window, "mutating"),
    (vocabulary.split_pane, "mutating"),
    (vocabulary.send_input, "mutating"),
    (vocabulary.capture_pane, "readonly"),
    (vocabulary.list_sessions, "readonly"),
    (vocabulary.list_windows, "readonly"),
    (vocabulary.list_panes, "readonly"),
    (vocabulary.rename_window, "mutating"),
    (vocabulary.rename_session, "mutating"),
    (vocabulary.select_layout, "mutating"),
    (vocabulary.select_pane, "mutating"),
    (vocabulary.kill_pane, "destructive"),
    (vocabulary.kill_window, "destructive"),
    (vocabulary.kill_session, "destructive"),
)

_INSTRUCTIONS = (
    "Drive tmux through typed tools. Targets accept tmux ids (%pane, @window, "
    "$session), names, or 'session:window.pane'. Creating a session/window also "
    "returns the new first-pane id for chaining."
)


def _summary(doc: str | None) -> str | None:
    """Return the first non-empty docstring line."""
    for line in (doc or "").splitlines():
        if line.strip():
            return line.strip()
    return None


def _bind_engine(
    fn: Callable[..., t.Any],
    engine: TmuxEngine,
) -> Callable[..., t.Any]:
    """Bind *engine* out of *fn*, returning a wrapper fastmcp can introspect.

    Unlike :func:`functools.partial`, this carries *pre-resolved* annotations
    (with ``engine`` removed) and an explicit ``__signature__``, so fastmcp's
    ``get_type_hints`` never has to re-evaluate the forward references in *fn*
    (it would do so against the wrong module globals and fail).
    """
    hints = t.get_type_hints(fn)
    signature = inspect.signature(fn)
    params = [p for name, p in signature.parameters.items() if name != "engine"]

    def tool(*args: t.Any, **kwargs: t.Any) -> t.Any:
        return fn(engine, *args, **kwargs)

    tool.__name__ = fn.__name__
    tool.__qualname__ = fn.__name__
    tool.__doc__ = fn.__doc__
    tool.__signature__ = signature.replace(parameters=params)  # type: ignore[attr-defined]
    tool.__annotations__ = {k: v for k, v in hints.items() if k != "engine"}
    return tool


def register_vocabulary(mcp: FastMCP, engine: TmuxEngine) -> None:
    """Register the curated vocabulary as tools on *mcp*, bound to *engine*."""
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    for fn, safety in _VOCABULARY:
        annotations = ToolAnnotations(
            title=fn.__name__,
            readOnlyHint=safety == "readonly",
            destructiveHint=safety == "destructive",
        )
        tool = FunctionTool.from_function(
            _bind_engine(fn, engine),
            name=fn.__name__,
            description=_summary(fn.__doc__),
            tags={safety},
            annotations=annotations,
        )
        mcp.add_tool(tool)


def build_server(
    engine: TmuxEngine,
    *,
    name: str = "libtmux",
    instructions: str | None = None,
) -> FastMCP:
    """Build a FastMCP server exposing the curated vocabulary over *engine*."""
    from fastmcp import FastMCP

    mcp: FastMCP = FastMCP(name=name, instructions=instructions or _INSTRUCTIONS)
    register_vocabulary(mcp, engine)
    return mcp
