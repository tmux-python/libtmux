"""Shared fixtures for the experimental MCP tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _hermetic_caller_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the ``/proc`` parent walk by default so server builds are hermetic.

    ``build_*_server`` defaults its caller to ``CallerContext.discover()``, which
    would otherwise walk the test host's process tree (host-dependent). Tests that
    exercise discovery pass explicit readers/environ to ``discover`` and are
    unaffected; tests that want a caller monkeypatch ``TMUX_PANE`` (the
    process-env source, which wins before the walk).
    """
    monkeypatch.setenv("LIBTMUX_MCP_DISCOVER", "0")
