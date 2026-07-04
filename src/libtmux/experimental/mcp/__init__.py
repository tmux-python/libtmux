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
    abuild_workspace,
    aexecute_plan,
    build_workspace,
    execute_plan,
    explain_plan,
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
    new_pane,
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

    from libtmux.experimental.mcp.vocabulary._caller import CallerContext


def _socket_args(
    caller: CallerContext,
    *,
    socket_path: str | None = None,
    socket_name: str | None = None,
    no_caller_socket: bool = False,
) -> tuple[str, ...]:
    """Resolve tmux connection flags: explicit overrides, else the caller's socket.

    Precedence: ``--socket-path`` > ``--socket-name`` > ``$LIBTMUX_SOCKET_PATH`` >
    ``$LIBTMUX_SOCKET`` > the discovered caller's socket (unless suppressed) >
    none (ambient/default server).
    """
    import os

    from libtmux.experimental.mcp.vocabulary._caller import caller_server_args

    if socket_path:
        return ("-S", socket_path)
    if socket_name:
        return ("-L", socket_name)
    env_path = os.environ.get("LIBTMUX_SOCKET_PATH")
    if env_path:
        return ("-S", env_path)
    env_name = os.environ.get("LIBTMUX_SOCKET")
    if env_name:
        return ("-L", env_name)
    if no_caller_socket:
        return ()
    return caller_server_args(caller, explicit=False)


def default_server(*, expose_operations: bool = False) -> FastMCP:
    """Build a synchronous FastMCP server over a :class:`~..engines.SubprocessEngine`.

    A convenience factory for embedding or deploying the *synchronous* server
    with the default tmux socket. Prefer :func:`default_async_server` for the
    async-first surface and the live event stream. Requires the ``mcp`` extra
    (``pip install 'libtmux[mcp]'``).
    """
    from libtmux.experimental.engines import SubprocessEngine
    from libtmux.experimental.mcp.fastmcp_adapter import build_server
    from libtmux.experimental.mcp.vocabulary._caller import CallerContext

    ctx = CallerContext.discover()
    engine = SubprocessEngine(server_args=_socket_args(ctx))
    return build_server(engine, expose_operations=expose_operations, caller=ctx)


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
    from libtmux.experimental.mcp.vocabulary._caller import CallerContext

    ctx = CallerContext.discover()
    engine = AsyncControlModeEngine(server_args=_socket_args(ctx))
    return build_async_server(
        engine,
        caller=ctx,
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
        epilog=(
            "socket precedence: --socket-path > --socket-name > "
            "$LIBTMUX_SOCKET_PATH > $LIBTMUX_SOCKET > discovered caller socket > "
            "default; --no-caller-socket drops the caller socket. "
            "caller identity: $TMUX/$TMUX_PANE > $LIBTMUX_MCP_CALLER_PANE "
            "(+$LIBTMUX_MCP_CALLER_TMUX) > /proc parent walk "
            "($LIBTMUX_MCP_DISCOVER=0 disables)."
        ),
    )
    parser.add_argument("--name", default="tmux", help="server name")
    parser.add_argument(
        "--operations",
        action="store_true",
        help="expose the full per-operation tool surface (op_*)",
    )
    parser.add_argument(
        "--safety",
        choices=("readonly", "mutating", "destructive"),
        default=None,
        help="max tool safety tier (default: $LIBTMUX_SAFETY or mutating)",
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
    parser.add_argument(
        "--socket-path",
        help="tmux -S socket path (overrides caller-socket discovery)",
    )
    parser.add_argument(
        "--socket-name",
        help="tmux -L socket name (overrides caller-socket discovery)",
    )
    parser.add_argument(
        "--no-caller-socket",
        action="store_true",
        help="do not auto-bind to the discovered caller's tmux socket",
    )
    args = parser.parse_args(argv)

    try:
        from libtmux.experimental.mcp.vocabulary._caller import CallerContext

        ctx = CallerContext.discover()
        srv_args = _socket_args(
            ctx,
            socket_path=args.socket_path,
            socket_name=args.socket_name,
            no_caller_socket=args.no_caller_socket,
        )
        if args.sync:
            from libtmux.experimental.engines import SubprocessEngine
            from libtmux.experimental.mcp.fastmcp_adapter import build_server

            server = build_server(
                SubprocessEngine(server_args=srv_args),
                name=args.name,
                expose_operations=args.operations,
                safety_level=args.safety,
                caller=ctx,
            )
        else:
            from libtmux.experimental.engines import AsyncControlModeEngine
            from libtmux.experimental.mcp.events import EventMode, EventSource
            from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

            server = build_async_server(
                AsyncControlModeEngine(server_args=srv_args),
                name=args.name,
                expose_operations=args.operations,
                safety_level=args.safety,
                events=t.cast("EventMode", args.events),
                event_source=t.cast("EventSource", args.event_source),
                caller=ctx,
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
    "abuild_workspace",
    "aexecute_plan",
    "build_workspace",
    "capture_pane",
    "create_session",
    "create_window",
    "default_async_server",
    "default_server",
    "execute_plan",
    "explain_plan",
    "kill_pane",
    "kill_session",
    "kill_window",
    "list_panes",
    "list_sessions",
    "list_windows",
    "main",
    "new_pane",
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
