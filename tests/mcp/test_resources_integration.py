"""Integration tests for libtmux MCP resources via FastMCP Client."""

from __future__ import annotations

import asyncio
import json
import typing as t

import pytest
from fastmcp import Client

from libtmux.mcp.server import _register_all, mcp

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window


_registered = False


@pytest.fixture(autouse=True)
def _ensure_registered() -> None:
    """Ensure tools and resources are registered with the MCP server once."""
    global _registered
    if not _registered:
        _register_all()
        _registered = True


def _run(coro: t.Any) -> t.Any:
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


async def _read(uri: str) -> str:
    """Read a resource via FastMCP Client and return text content."""
    async with Client(mcp) as client:
        results = await client.read_resource(uri)
        assert len(results) >= 1
        return results[0].text or ""


class ResourceIntegrationFixture(t.NamedTuple):
    """Test fixture for resource integration reads."""

    test_id: str
    uri_template: str
    expect_json: bool
    expect_contains: str | None


RESOURCE_INTEGRATION_FIXTURES: list[ResourceIntegrationFixture] = [
    ResourceIntegrationFixture(
        test_id="list_all_sessions",
        uri_template="tmux://sessions",
        expect_json=True,
        expect_contains="session_id",
    ),
    ResourceIntegrationFixture(
        test_id="session_detail",
        uri_template="tmux://sessions/{session_name}",
        expect_json=True,
        expect_contains="windows",
    ),
    ResourceIntegrationFixture(
        test_id="session_windows",
        uri_template="tmux://sessions/{session_name}/windows",
        expect_json=True,
        expect_contains="window_id",
    ),
    ResourceIntegrationFixture(
        test_id="pane_detail",
        uri_template="tmux://panes/{pane_id}",
        expect_json=True,
        expect_contains="pane_id",
    ),
    ResourceIntegrationFixture(
        test_id="pane_content",
        uri_template="tmux://panes/{pane_id}/content",
        expect_json=False,
        expect_contains=None,  # fresh pane may be empty
    ),
]


@pytest.mark.parametrize(
    ResourceIntegrationFixture._fields,
    RESOURCE_INTEGRATION_FIXTURES,
    ids=[f.test_id for f in RESOURCE_INTEGRATION_FIXTURES],
)
def test_resource_read_via_client(
    mcp_server: Server,
    mcp_session: Session,
    mcp_window: Window,
    mcp_pane: Pane,
    test_id: str,
    uri_template: str,
    expect_json: bool,
    expect_contains: str | None,
) -> None:
    """Resources are readable via FastMCP Client protocol."""
    uri = uri_template.format(
        session_name=mcp_session.session_name,
        window_index=mcp_window.window_index,
        pane_id=mcp_pane.pane_id,
    )

    text = _run(_read(uri))
    assert isinstance(text, str)

    if expect_json:
        data = json.loads(text)
        assert data is not None

    if expect_contains is not None:
        assert expect_contains in text
