"""Framework-agnostic MCP projection: typed, chained, toolable tmux commands.

The third tier over the Core (ops/plan/engines) and Declarative
(:mod:`libtmux.experimental.workspace`) tiers. It projects each operation into a
typed :class:`~.descriptor.ToolDescriptor` (via
:class:`~.registry.OperationToolRegistry`), resolves agent string/dict targets
(:func:`~.target_resolver.resolve_target`), and exposes plan tools
(:func:`~.plan_tools.preview_plan`, :func:`~.plan_tools.execute_plan`,
:func:`~.plan_tools.result_schema`) plus :func:`~.plan_tools.build_workspace`.

It has **no** MCP-framework dependency (no fastmcp/pydantic at import time); a
thin adapter in a server (e.g. libtmux-mcp) binds these descriptors at runtime.
Everything here is experimental and outside the versioning policy.

Examples
--------
>>> from libtmux.experimental.engines import ConcreteEngine
>>> reg = OperationToolRegistry()
>>> reg.descriptor("new_session").safety
'mutating'
>>> resolve_target("%1")
PaneId(value='%1')
"""

from __future__ import annotations

import typing as t

from libtmux.experimental.mcp.descriptor import ParamDescriptor, ToolDescriptor
from libtmux.experimental.mcp.plan_tools import (
    PlanOutcome,
    PlanPreview,
    ResultSchema,
    aexecute_plan,
    build_workspace,
    execute_plan,
    preview_plan,
    result_schema,
)
from libtmux.experimental.mcp.registry import OperationToolRegistry
from libtmux.experimental.mcp.schema import schema_for_type
from libtmux.experimental.mcp.target_resolver import resolve_target
from libtmux.experimental.mcp.vocabulary import (
    Listing,
    PaneCapture,
    PaneResult,
    SessionResult,
    WindowResult,
    capture_pane,
    create_session,
    create_window,
    kill_pane,
    kill_session,
    kill_window,
    list_panes,
    list_sessions,
    list_windows,
    rename_session,
    rename_window,
    select_layout,
    select_pane,
    send_input,
    split_pane,
)

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from fastmcp import FastMCP


def default_server(*, expose_operations: bool = False) -> FastMCP:
    """Build a synchronous FastMCP server over a :class:`~..engines.SubprocessEngine`.

    A convenience factory for embedding or deploying the *synchronous* server
    with the default tmux socket. Prefer :func:`default_async_server` for the
    async-first surface and the live event stream. Requires the ``mcp`` extra
    (``pip install 'libtmux[mcp]'``).
    """
    from libtmux.experimental.engines import SubprocessEngine
    from libtmux.experimental.mcp.fastmcp_adapter import build_server

    return build_server(SubprocessEngine(), expose_operations=expose_operations)


def default_async_server(
    *,
    expose_operations: bool = False,
    events: str = "push",
    event_source: str = "subscription",
) -> FastMCP:
    """Build the async-first FastMCP server over an :class:`AsyncControlModeEngine`.

    The default deployment: tools are awaited on FastMCP's loop and the live
    event stream is wired up. The control-mode connection opens lazily on first
    use. Requires the ``mcp`` extra.
    """
    import typing as t

    from libtmux.experimental.engines import AsyncControlModeEngine
    from libtmux.experimental.mcp.events import EventMode, EventSource
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    return build_async_server(
        AsyncControlModeEngine(),
        expose_operations=expose_operations,
        events=t.cast("EventMode", events),
        event_source=t.cast("EventSource", event_source),
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Run the libtmux-engine MCP server over stdio (console-script entry).

    Async-first by default (an :class:`AsyncControlModeEngine`); pass ``--sync``
    for the subprocess-backed synchronous server. Event mode/source default from
    ``LIBTMUX_MCP_EVENTS`` / ``LIBTMUX_MCP_EVENT_SOURCE``. Wired to the
    ``libtmux-engine-mcp`` console script and ``python -m
    libtmux.experimental.mcp``. Requires the ``mcp`` extra.
    """
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(
        prog="libtmux-engine-mcp",
        description="Run the experimental libtmux typed-ops MCP server (stdio).",
    )
    parser.add_argument("--name", default="tmux", help="server name")
    parser.add_argument(
        "--operations",
        action="store_true",
        help="expose the full per-operation tool surface (op_*)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="use the synchronous subprocess server instead of async-first",
    )
    parser.add_argument(
        "--events",
        choices=("off", "push", "pull", "both"),
        default=os.environ.get("LIBTMUX_MCP_EVENTS", "push"),
        help="live event mechanism (async server only)",
    )
    parser.add_argument(
        "--event-source",
        choices=("subscription", "output"),
        default=os.environ.get("LIBTMUX_MCP_EVENT_SOURCE", "subscription"),
        help="event substrate (async server only)",
    )
    args = parser.parse_args(argv)

    try:
        if args.sync:
            from libtmux.experimental.engines import SubprocessEngine
            from libtmux.experimental.mcp.fastmcp_adapter import build_server

            server = build_server(
                SubprocessEngine(),
                name=args.name,
                expose_operations=args.operations,
            )
        else:
            server = default_async_server(
                expose_operations=args.operations,
                events=args.events,
                event_source=args.event_source,
            )
    except ImportError:
        sys.stderr.write(
            "libtmux-engine-mcp requires the 'mcp' extra: pip install 'libtmux[mcp]'\n",
        )
        raise SystemExit(1) from None

    server.run(transport="stdio")


__all__ = (
    "Listing",
    "OperationToolRegistry",
    "PaneCapture",
    "PaneResult",
    "ParamDescriptor",
    "PlanOutcome",
    "PlanPreview",
    "ResultSchema",
    "SessionResult",
    "ToolDescriptor",
    "WindowResult",
    "aexecute_plan",
    "build_workspace",
    "capture_pane",
    "create_session",
    "create_window",
    "default_async_server",
    "default_server",
    "execute_plan",
    "kill_pane",
    "kill_session",
    "kill_window",
    "list_panes",
    "list_sessions",
    "list_windows",
    "main",
    "preview_plan",
    "rename_session",
    "rename_window",
    "resolve_target",
    "result_schema",
    "schema_for_type",
    "select_layout",
    "select_pane",
    "send_input",
    "split_pane",
)
