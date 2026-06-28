"""Tests for the recipe prompts on the engine-ops MCP server."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import ConcreteEngine

fastmcp = pytest.importorskip("fastmcp")

from libtmux.experimental.mcp.fastmcp_adapter import build_server  # noqa: E402

_NAMES = {
    "run_and_wait",
    "diagnose_failing_pane",
    "build_dev_workspace",
    "interrupt_gracefully",
}
#: Tool names from libtmux-mcp that do NOT exist in the engine-ops vocabulary.
_FOREIGN_TOOLS = (
    "run_command",
    "snapshot_pane",
    "send_keys",
    "split_window",
    "wait_for_text",
    "capture_since",
)


def test_prompts_registered() -> None:
    """The four recipe prompts are registered on the server."""
    server = build_server(ConcreteEngine())

    async def main() -> set[str]:
        async with fastmcp.Client(server) as client:
            return {prompt.name for prompt in await client.list_prompts()}

    assert asyncio.run(main()) >= _NAMES


def test_prompt_bodies_use_engine_ops_vocabulary() -> None:
    """Rendered prompt text names engine-ops verbs, never libtmux-mcp-only ones."""
    from libtmux.experimental.mcp.prompts import (
        build_dev_workspace,
        diagnose_failing_pane,
        interrupt_gracefully,
        run_and_wait,
    )

    bodies = [
        run_and_wait("ls", "%1"),
        diagnose_failing_pane("%1"),
        build_dev_workspace("dev"),
        interrupt_gracefully("%1"),
    ]
    for body in bodies:
        for foreign in _FOREIGN_TOOLS:
            assert foreign not in body, f"foreign tool {foreign!r} leaked"
    # the canonical engine-ops verbs appear
    assert "send_input" in run_and_wait("ls", "%1")
    assert "split_pane" in build_dev_workspace("dev")
    assert "wait_for_output" in interrupt_gracefully("%1")


class WaitForOutputCase(t.NamedTuple):
    """A prompt body that calls ``wait_for_output``."""

    test_id: str
    body: str


def _wait_for_output_bodies() -> tuple[WaitForOutputCase, ...]:
    from libtmux.experimental.mcp.prompts import (
        diagnose_failing_pane,
        interrupt_gracefully,
        run_and_wait,
    )

    return (
        WaitForOutputCase("run_and_wait", run_and_wait("ls", "%1")),
        WaitForOutputCase("diagnose_failing_pane", diagnose_failing_pane("%1")),
        WaitForOutputCase("interrupt_gracefully", interrupt_gracefully("%1")),
    )


_WAIT_FOR_OUTPUT_CASES = _wait_for_output_bodies()


@pytest.mark.parametrize(
    "case",
    _WAIT_FOR_OUTPUT_CASES,
    ids=[c.test_id for c in _WAIT_FOR_OUTPUT_CASES],
)
def test_wait_for_output_uses_target_param(case: WaitForOutputCase) -> None:
    """Prompts must call ``wait_for_output`` with ``target=`` (its real param).

    The tool signature is ``wait_for_output(target=..., ...)``; ``pane=`` is not a
    parameter, so a recipe emitting it would fail FastMCP schema validation.
    """
    assert "wait_for_output(target=" in case.body
    assert "wait_for_output(pane=" not in case.body
