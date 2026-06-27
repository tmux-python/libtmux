"""Tests for the error-result + tail-preserving response middleware."""

from __future__ import annotations

import pytest

pytest.importorskip("fastmcp")


def test_truncate_keeps_tail_with_header() -> None:
    """The limiter drops the head and keeps the tail behind a header."""
    from mcp.types import TextContent

    from libtmux.experimental.mcp.middleware import (
        TailPreservingResponseLimitingMiddleware,
    )

    mw = TailPreservingResponseLimitingMiddleware(max_size=200)
    result = mw._truncate_to_result("HEAD" + "x" * 1000 + "TAILEND")
    block = result.content[0]
    assert isinstance(block, TextContent)
    assert block.text.startswith("[... truncated")
    assert block.text.endswith("TAILEND")  # tail preserved, head dropped
    assert len(block.text.encode("utf-8")) <= 200


def test_error_result_carries_message_and_meta() -> None:
    """A plain failure becomes an is_error result with typed meta, no prefix."""
    from mcp.types import TextContent

    from libtmux.experimental.mcp.middleware import _error_tool_result

    result = _error_tool_result(ValueError("boom"))
    block = result.content[0]
    assert result.is_error is True
    assert result.meta is not None
    assert result.meta["error_type"] == "ValueError"
    assert result.meta["expected"] is False
    assert isinstance(block, TextContent)
    assert block.text == "boom"


def test_error_result_appends_suggestion() -> None:
    """An ExpectedToolError's suggestion lands in text + meta, marked expected."""
    from mcp.types import TextContent

    from libtmux.experimental.mcp._safety import ExpectedToolError
    from libtmux.experimental.mcp.middleware import _error_tool_result

    result = _error_tool_result(
        ExpectedToolError("Pane not found", suggestion="Call list_panes."),
    )
    block = result.content[0]
    assert result.meta is not None
    assert result.meta["expected"] is True
    assert result.meta["suggestion"] == "Call list_panes."
    assert isinstance(block, TextContent)
    assert block.text.endswith("Call list_panes.")


def test_schema_validation_error_formats_without_raw_input() -> None:
    """Schema-validation failures are expected and never echo the raw input."""
    import pydantic

    from libtmux.experimental.mcp.middleware import (
        _format_schema_validation_error,
        _is_schema_validation_error,
    )

    class Model(pydantic.BaseModel):
        x: int

    try:
        Model(x="not-an-int")  # type: ignore[arg-type]
    except pydantic.ValidationError as exc:
        assert _is_schema_validation_error(exc)
        formatted = _format_schema_validation_error(exc)
        assert "x" in formatted
        assert "[type=" in formatted
        assert "not-an-int" not in formatted  # raw input is redacted
    else:
        pytest.fail("expected a ValidationError")
