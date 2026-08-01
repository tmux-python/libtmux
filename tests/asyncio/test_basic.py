"""Tests for libtmux with :mod`asyncio` support."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from libtmux.session import Session

if TYPE_CHECKING:
    from libtmux.server import Server

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_asyncio(server: Server) -> None:
    """Test basic asyncio usage."""
    result = await server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]
    session = Session.from_session_id(
        session_id=session_id,
        server=server,
    )
    assert isinstance(session, Session)
