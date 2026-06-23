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
    """Build a FastMCP server over a default :class:`~..engines.SubprocessEngine`.

    A convenience factory (also the ``fastmcp.json`` entrypoint) for embedding or
    deploying the server with the default tmux socket. Requires the ``mcp``
    extra (``pip install 'libtmux[mcp]'``).
    """
    from libtmux.experimental.engines import SubprocessEngine
    from libtmux.experimental.mcp.fastmcp_adapter import build_server

    return build_server(SubprocessEngine(), expose_operations=expose_operations)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the libtmux-engine MCP server over stdio (console-script entry).

    Wired to the ``libtmux-engine-mcp`` console script and
    ``python -m libtmux.experimental.mcp``. Requires the ``mcp`` extra.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="libtmux-engine-mcp",
        description="Run the experimental libtmux typed-ops MCP server (stdio).",
    )
    parser.add_argument("--name", default="libtmux-engine", help="server name")
    parser.add_argument(
        "--operations",
        action="store_true",
        help="expose the full per-operation tool surface (op_*)",
    )
    args = parser.parse_args(argv)

    try:
        from libtmux.experimental.engines import SubprocessEngine
        from libtmux.experimental.mcp.fastmcp_adapter import build_server
    except ImportError:
        sys.stderr.write(
            "libtmux-engine-mcp requires the 'mcp' extra: pip install 'libtmux[mcp]'\n",
        )
        raise SystemExit(1) from None

    server = build_server(
        SubprocessEngine(),
        name=args.name,
        expose_operations=args.operations,
    )
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
