"""Safety middleware for libtmux MCP server.

Gates tools by safety tier based on the ``LIBTMUX_SAFETY`` environment
variable. Tools tagged above the configured tier are hidden from listing
and blocked from execution.
"""

from __future__ import annotations

import typing as t

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext

from libtmux.mcp._utils import TAG_DESTRUCTIVE, TAG_MUTATING, TAG_READONLY

_TIER_LEVELS: dict[str, int] = {
    TAG_READONLY: 0,
    TAG_MUTATING: 1,
    TAG_DESTRUCTIVE: 2,
}


class SafetyMiddleware(Middleware):
    """Gate tools by safety tier.

    Parameters
    ----------
    max_tier : str
        Maximum allowed tier. One of ``TAG_READONLY``, ``TAG_MUTATING``,
        or ``TAG_DESTRUCTIVE``.
    """

    def __init__(self, max_tier: str = TAG_MUTATING) -> None:
        self.max_level = _TIER_LEVELS.get(max_tier, 1)

    def _is_allowed(self, tags: set[str]) -> bool:
        """Return True if the tool's tags fall within the allowed tier.

        Fail-closed: tools without a recognized tier tag are denied.
        """
        found_tier = False
        for tier, level in _TIER_LEVELS.items():
            if tier in tags:
                found_tier = True
                if level > self.max_level:
                    return False
        return found_tier

    async def on_list_tools(
        self,
        context: MiddlewareContext,
        call_next: t.Any,
    ) -> t.Any:
        """Filter tools above the safety tier from the listing."""
        tools = await call_next(context)
        return [tool for tool in tools if self._is_allowed(tool.tags)]

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: t.Any,
    ) -> t.Any:
        """Block execution of tools above the safety tier."""
        if context.fastmcp_context:
            tool = await context.fastmcp_context.fastmcp.get_tool(context.message.name)
            if tool and not self._is_allowed(tool.tags):
                msg = (
                    f"Tool '{context.message.name}' is not available at the "
                    f"current safety level. Set LIBTMUX_SAFETY=destructive "
                    f"to enable destructive tools."
                )
                raise ToolError(msg)
        return await call_next(context)
