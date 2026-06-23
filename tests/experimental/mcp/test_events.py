"""The live event stream tools -- push, pull, and the registration gate.

Driven offline against a fake engine that yields a fixed notification sequence,
so the push/pull mechanics are exercised without a real tmux ``-C`` connection.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines.async_control_mode import ControlNotification
from libtmux.experimental.engines.base import CommandResult

fastmcp = pytest.importorskip("fastmcp")

if t.TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from libtmux.experimental.engines.base import CommandRequest


class FakeStreamEngine:
    """An async engine that replays a fixed notification stream."""

    def __init__(self, raw: tuple[bytes, ...]) -> None:
        self._raw = raw

    async def run(self, request: CommandRequest) -> CommandResult:
        """Acknowledge any command."""
        return CommandResult(cmd=("tmux", *request.args), returncode=0)

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Acknowledge a batch of commands."""
        return [await self.run(r) for r in requests]

    async def subscribe(self) -> AsyncIterator[ControlNotification]:
        """Yield the fixed notification sequence."""
        for raw in self._raw:
            yield ControlNotification.parse(raw)


_STREAM = (b"%window-add @3", b"%output %1 hi", b"%window-close @3")


def _tool_names(server: t.Any) -> set[str]:
    """Return the visible tool names of *server* (via an in-process client)."""

    async def main() -> set[str]:
        async with fastmcp.Client(server) as client:
            return {tool.name for tool in await client.list_tools()}

    return asyncio.run(main())


def test_push_collects_filtered_events() -> None:
    """watch_events streams and returns only the requested notification kinds."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        FakeStreamEngine(_STREAM),
        events="push",
        include_operations=False,
        include_plan_tools=False,
    )

    async def main() -> dict[str, t.Any]:
        async with fastmcp.Client(server) as client:
            result = await client.call_tool(
                "watch_events",
                {
                    "kinds": ["window-add", "window-close"],
                    "max_events": 2,
                    "timeout": 2.0,
                },
            )
            return t.cast("dict[str, t.Any]", result.data)

    data = asyncio.run(main())
    assert data["count"] == 2
    assert [event["kind"] for event in data["events"]] == ["window-add", "window-close"]


def test_pull_buffers_events() -> None:
    """poll_events drains the background ring buffer with a cursor."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        FakeStreamEngine(_STREAM),
        events="pull",
        include_operations=False,
        include_plan_tools=False,
    )

    async def main() -> dict[str, t.Any]:
        async with fastmcp.Client(server) as client:
            await client.call_tool("poll_events", {"since": 0})  # start the drainer
            await asyncio.sleep(0.05)
            result = await client.call_tool("poll_events", {"since": 0})
            return t.cast("dict[str, t.Any]", result.data)

    data = asyncio.run(main())
    assert len(data["events"]) == 3
    assert data["cursor"] == 3


def test_both_registers_push_and_pull() -> None:
    """events='both' exposes both mechanisms."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        FakeStreamEngine(_STREAM),
        events="both",
        include_operations=False,
        include_plan_tools=False,
    )
    names = _tool_names(server)
    assert {"watch_events", "poll_events"} <= names


def test_no_event_tools_without_a_stream() -> None:
    """A non-streaming engine registers no event tools, even when asked."""
    from libtmux.experimental.engines import ConcreteEngine
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server
    from libtmux.experimental.mcp.vocabulary._bridge import SyncToAsyncEngine

    server = build_async_server(
        SyncToAsyncEngine(ConcreteEngine()),
        events="both",
        include_operations=False,
        include_plan_tools=False,
    )
    names = _tool_names(server)
    assert "watch_events" not in names
    assert "poll_events" not in names
