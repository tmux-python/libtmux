"""Sanity checks for the control_sandbox context-manager fixture."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.server import Server


@pytest.mark.engines(["control"])
def test_control_sandbox_smoke(control_sandbox: t.ContextManager[Server]) -> None:
    """Control sandbox should spin up an isolated server and run commands."""
    with control_sandbox as server:
        session = server.new_session(
            session_name="sandbox_session",
            attach=False,
            kill_session=True,
        )
        assert session.name == "sandbox_session"
        assert server.has_session("sandbox_session")

        # Run a simple command to ensure control mode path works.
        out = server.cmd("display-message", "-p", "hi")
        assert out.stdout == ["hi"]
