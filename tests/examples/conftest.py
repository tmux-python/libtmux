"""Pytest configuration for example tests."""

from __future__ import annotations

import pytest  # noqa: F401 - Need this import for pytest hooks to work


def pytest_configure(config) -> None:
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers",
        "example: mark a test as an example that demonstrates how to use the library",
    )
