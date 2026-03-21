"""Tests for libtmux MCP safety middleware."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.mcp._utils import TAG_DESTRUCTIVE, TAG_MUTATING, TAG_READONLY
from libtmux.mcp.middleware import SafetyMiddleware


class SafetyAllowedFixture(t.NamedTuple):
    """Test fixture for SafetyMiddleware._is_allowed."""

    test_id: str
    max_tier: str
    tool_tags: set[str]
    expected_allowed: bool


SAFETY_ALLOWED_FIXTURES: list[SafetyAllowedFixture] = [
    # readonly tier: only readonly tools allowed
    SafetyAllowedFixture(
        test_id="readonly_allows_readonly",
        max_tier=TAG_READONLY,
        tool_tags={TAG_READONLY},
        expected_allowed=True,
    ),
    SafetyAllowedFixture(
        test_id="readonly_blocks_mutating",
        max_tier=TAG_READONLY,
        tool_tags={TAG_MUTATING},
        expected_allowed=False,
    ),
    SafetyAllowedFixture(
        test_id="readonly_blocks_destructive",
        max_tier=TAG_READONLY,
        tool_tags={TAG_DESTRUCTIVE},
        expected_allowed=False,
    ),
    # mutating tier: readonly + mutating allowed
    SafetyAllowedFixture(
        test_id="mutating_allows_readonly",
        max_tier=TAG_MUTATING,
        tool_tags={TAG_READONLY},
        expected_allowed=True,
    ),
    SafetyAllowedFixture(
        test_id="mutating_allows_mutating",
        max_tier=TAG_MUTATING,
        tool_tags={TAG_MUTATING},
        expected_allowed=True,
    ),
    SafetyAllowedFixture(
        test_id="mutating_blocks_destructive",
        max_tier=TAG_MUTATING,
        tool_tags={TAG_DESTRUCTIVE},
        expected_allowed=False,
    ),
    # destructive tier: all allowed
    SafetyAllowedFixture(
        test_id="destructive_allows_readonly",
        max_tier=TAG_DESTRUCTIVE,
        tool_tags={TAG_READONLY},
        expected_allowed=True,
    ),
    SafetyAllowedFixture(
        test_id="destructive_allows_mutating",
        max_tier=TAG_DESTRUCTIVE,
        tool_tags={TAG_MUTATING},
        expected_allowed=True,
    ),
    SafetyAllowedFixture(
        test_id="destructive_allows_destructive",
        max_tier=TAG_DESTRUCTIVE,
        tool_tags={TAG_DESTRUCTIVE},
        expected_allowed=True,
    ),
    # untagged tools are always allowed
    SafetyAllowedFixture(
        test_id="untagged_allowed_at_readonly",
        max_tier=TAG_READONLY,
        tool_tags=set(),
        expected_allowed=True,
    ),
]


@pytest.mark.parametrize(
    SafetyAllowedFixture._fields,
    SAFETY_ALLOWED_FIXTURES,
    ids=[f.test_id for f in SAFETY_ALLOWED_FIXTURES],
)
def test_safety_middleware_is_allowed(
    test_id: str,
    max_tier: str,
    tool_tags: set[str],
    expected_allowed: bool,
) -> None:
    """SafetyMiddleware._is_allowed gates tools by tier."""
    mw = SafetyMiddleware(max_tier=max_tier)
    assert mw._is_allowed(tool_tags) is expected_allowed


def test_safety_middleware_default_tier() -> None:
    """SafetyMiddleware defaults to mutating tier."""
    mw = SafetyMiddleware()
    assert mw._is_allowed({TAG_READONLY}) is True
    assert mw._is_allowed({TAG_MUTATING}) is True
    assert mw._is_allowed({TAG_DESTRUCTIVE}) is False


def test_safety_middleware_invalid_tier_falls_back() -> None:
    """SafetyMiddleware falls back to mutating for unknown tiers."""
    mw = SafetyMiddleware(max_tier="nonexistent")
    assert mw._is_allowed({TAG_READONLY}) is True
    assert mw._is_allowed({TAG_MUTATING}) is True
    assert mw._is_allowed({TAG_DESTRUCTIVE}) is False
