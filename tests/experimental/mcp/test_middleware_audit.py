"""Tests for the audit, safety-tier, and readonly-retry middleware."""

from __future__ import annotations

import asyncio
import logging
import typing as t
from types import SimpleNamespace

import pytest

pytest.importorskip("fastmcp")


def test_audit_emits_one_redacted_record(caplog: pytest.LogCaptureFixture) -> None:
    """One structured INFO record per call, with sensitive args digested."""
    from libtmux.experimental.mcp.middleware import AuditMiddleware

    mw = AuditMiddleware()
    ctx: t.Any = SimpleNamespace(
        message=SimpleNamespace(
            name="send_input",
            arguments={"keys": "secret-cmd", "pane_id": "%1"},
        ),
        fastmcp_context=SimpleNamespace(client_id="c1", request_id="r1"),
    )

    async def call_next(_context: t.Any) -> str:
        return "ok"

    async def main() -> t.Any:
        return await mw.on_call_tool(ctx, call_next)

    with caplog.at_level(logging.INFO, logger="libtmux.experimental.mcp.audit"):
        result = asyncio.run(main())

    assert result == "ok"
    records = [
        r for r in caplog.records if getattr(r, "tmux_subcommand", None) == "send_input"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.outcome == "ok"  # type: ignore[attr-defined]
    assert isinstance(record.duration_ms, float)  # type: ignore[attr-defined]
    # the sensitive `keys` payload is digested, never logged raw
    summary = record.tmux_args  # type: ignore[attr-defined]
    assert "secret-cmd" not in str(summary)
    assert summary["keys"]["sha256_prefix"]
    assert summary["pane_id"] == "%1"  # non-sensitive args pass through


def test_safety_is_allowed_is_fail_closed() -> None:
    """A tool at or below the tier is allowed; an untagged tool is denied."""
    from libtmux.experimental.mcp._safety import (
        TAG_DESTRUCTIVE,
        TAG_MUTATING,
        TAG_READONLY,
    )
    from libtmux.experimental.mcp.middleware import SafetyMiddleware

    mw = SafetyMiddleware(TAG_MUTATING)
    assert mw._is_allowed({TAG_READONLY})
    assert mw._is_allowed({TAG_MUTATING})
    assert not mw._is_allowed({TAG_DESTRUCTIVE})  # over tier
    assert not mw._is_allowed(set())  # no recognized tier -> denied


def test_readonly_retry_passes_through_without_context() -> None:
    """With no fastmcp context the retry wrapper is a transparent pass-through."""
    from libtmux.experimental.mcp.middleware import ReadonlyRetryMiddleware

    mw = ReadonlyRetryMiddleware()
    ctx: t.Any = SimpleNamespace(fastmcp_context=None)
    calls = 0

    async def call_next(_context: t.Any) -> str:
        nonlocal calls
        calls += 1
        return "value"

    async def main() -> t.Any:
        return await mw.on_call_tool(ctx, call_next)

    assert asyncio.run(main()) == "value"
    assert calls == 1  # not retried, just forwarded
