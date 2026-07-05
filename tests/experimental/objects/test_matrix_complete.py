"""Tests completing the object matrix: lazy/async Server+Session and Client."""

from __future__ import annotations

import asyncio

from libtmux.experimental.engines import AsyncConcreteEngine, ConcreteEngine
from libtmux.experimental.objects import (
    AsyncClient,
    AsyncServer,
    EagerClient,
    LazyClient,
    LazyServer,
)
from libtmux.experimental.ops import LazyPlan


def test_lazy_server_session_window_plan() -> None:
    """LazyServer records a full Server->Session->Window creation plan."""
    plan = LazyPlan()
    server = LazyServer(plan)
    session = server.new_session(name="work")
    window = session.new_window(name="build")
    window.split()
    assert len(plan) == 3  # new-session, new-window, split-window

    outcome = plan.execute(ConcreteEngine())
    assert outcome.ok
    assert [r.created_id for r in outcome.results] == ["$1", "@1", "%1"]


def test_async_server_navigation() -> None:
    """AsyncServer->AsyncSession->AsyncWindow navigation via await."""

    async def main() -> str:
        server = AsyncServer(AsyncConcreteEngine())
        session = await server.new_session(name="work")
        window = await session.new_window()
        pane = await window.split()
        return pane.pane_id

    assert asyncio.run(main()) == "%1"


def test_eager_client_methods() -> None:
    """EagerClient detach/refresh/switch_to return successful results."""
    client = EagerClient(ConcreteEngine(), "/dev/pts/3")
    assert client.refresh().ok
    assert client.switch_to("$1").ok
    assert client.detach().ok


def test_lazy_client_records() -> None:
    """LazyClient records client ops into a plan."""
    plan = LazyPlan()
    client = LazyClient(plan, "/dev/pts/3")
    client.refresh().switch_to("$1")
    assert [op.kind for op in plan] == ["refresh_client", "switch_client"]
    assert plan.execute(ConcreteEngine()).ok


def test_async_client() -> None:
    """AsyncClient mirrors the eager client via await."""

    async def main() -> bool:
        client = AsyncClient(AsyncConcreteEngine(), "/dev/pts/3")
        return (await client.refresh()).ok

    assert asyncio.run(main())
