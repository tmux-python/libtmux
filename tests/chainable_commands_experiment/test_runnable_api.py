"""Tests for a LangChain-style runnable command API."""

from __future__ import annotations

from dataclasses import dataclass, field

from typing_extensions import assert_type

from . import runnable_api as api
from .shared import Arg


@dataclass
class _FakeRunner:
    """Record runnable command dispatches."""

    calls: list[tuple[str, tuple[Arg, ...], str | int | None]] = field(
        default_factory=list,
    )

    def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> api.RunRecord:
        """Record one command dispatch."""
        self.calls.append((cmd, args, target))
        return api.RunRecord(command=cmd, args=args, target=target, stdout=["ok"])


def test_runnable_api_invokes_batches_and_streams() -> None:
    """Runnable commands support symmetric single and batch execution."""
    runner = _FakeRunner()
    pipeline = api.target_capture_call().then(api.run_command())

    result = pipeline.invoke("%1", runner)
    results = pipeline.batch(["%2", "%3"], runner)
    streamed = list(pipeline.stream("%4", runner))

    assert_type(pipeline, api.RunnableCommand[str, api.RunRecord])
    assert result.command == "capture-pane"
    assert results[0].target == "%2"
    assert streamed[0].target == "%4"


def test_runnable_api_composes_with_shift_operator() -> None:
    """The shorthand composition operator remains type preserving."""
    pipeline = api.target_capture_call() >> api.render_argv()

    assert_type(pipeline, api.RunnableCommand[str, tuple[str, ...]])
    assert pipeline.invoke("%1", _FakeRunner()) == ("capture-pane", "-t", "%1", "-p")
