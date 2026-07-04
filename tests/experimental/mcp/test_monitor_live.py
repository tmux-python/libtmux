"""End-to-end ``wait_for_output`` against a real tmux control-mode engine.

Unlike the offline event tests, this drives the monitor through an in-process
FastMCP client over a live ``tmux -C`` connection: a real pane produces output,
and the tool folds the genuine ``%output`` firehose (octal-decoded) until the
pane goes quiet. Proves the needle-free settle path works against real tmux, not
just a scripted stream.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines.base import CommandRequest
from libtmux.experimental.mcp._settle import output_payload

fastmcp = pytest.importorskip("fastmcp")

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_wait_for_output_captures_real_output(session: Session) -> None:
    """The monitor folds a real pane's output and settles when it goes quiet."""
    from libtmux.experimental.engines import AsyncControlModeEngine
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = session.server
    pane = session.active_window.active_pane
    assert pane is not None
    pane_id = pane.pane_id
    assert pane_id is not None

    async def main() -> t.Any:
        async with AsyncControlModeEngine.for_server(server) as engine:
            mcp = build_async_server(
                engine,
                events="push",
                include_operations=False,
                include_plan_tools=False,
            )
            async with fastmcp.Client(mcp) as client:

                async def produce() -> None:
                    # Let the monitor subscribe first, then make the pane emit.
                    await asyncio.sleep(0.3)
                    await engine.run(
                        CommandRequest.from_args(
                            "send-keys",
                            "-t",
                            pane_id,
                            "echo MONITOR_OK",
                            "Enter",
                        ),
                    )

                producer = asyncio.ensure_future(produce())
                try:
                    result = await client.call_tool(
                        "wait_for_output",
                        {"target": pane_id, "settle_ms": 400, "timeout": 10.0},
                    )
                finally:
                    await producer
                return result.data

    data = asyncio.run(main())
    assert data.pane_id == pane_id
    assert data.reason in ("settled", "byte_cap")
    assert "MONITOR_OK" in data.captured_text
    assert data.frame_count >= 1


def test_watch_events_output_source_captures_real_output(session: Session) -> None:
    """watch_events(target=...) attaches and streams a real pane's %output."""
    from libtmux.experimental.engines import AsyncControlModeEngine
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = session.server
    pane = session.active_window.active_pane
    assert pane is not None
    pane_id = pane.pane_id
    assert pane_id is not None

    async def main() -> t.Any:
        async with AsyncControlModeEngine.for_server(server) as engine:
            mcp = build_async_server(
                engine,
                events="push",
                event_source="output",
                include_operations=False,
                include_plan_tools=False,
            )
            async with fastmcp.Client(mcp) as client:

                async def produce() -> None:
                    await asyncio.sleep(0.3)
                    await engine.run(
                        CommandRequest.from_args(
                            "send-keys",
                            "-t",
                            pane_id,
                            "echo WATCH_OK",
                            "Enter",
                        ),
                    )

                producer = asyncio.ensure_future(produce())
                try:
                    result = await client.call_tool(
                        "watch_events",
                        {
                            "target": pane_id,
                            "kinds": ["output"],
                            "max_events": 8,
                            "timeout": 2.0,
                        },
                    )
                finally:
                    await producer
                return result.data

    data = asyncio.run(main())
    assert data["count"] >= 1
    assert {event["kind"] for event in data["events"]} == {"output"}
    text = "".join(
        payload
        for event in data["events"]
        if (payload := output_payload(event["raw"], pane_id)) is not None
    )
    assert "WATCH_OK" in text
