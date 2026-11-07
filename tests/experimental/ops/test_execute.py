"""Tests for the :func:`run` / :func:`arun` execution bridge.

These use in-memory fake engines so they need no tmux server -- the same
property that lets the contract suite run an operation through every engine.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine
from libtmux.experimental.engines.base import SupportsTmuxVersion
from libtmux.experimental.engines.control_mode import ControlModeEngine
from libtmux.experimental.engines.mock import MockEngine
from libtmux.experimental.engines.subprocess import SubprocessEngine
from libtmux.experimental.ops import BreakPane, SendKeys, SplitWindow, arun, run
from libtmux.experimental.ops._types import PaneId, WindowId
from libtmux.experimental.ops.exc import TmuxCommandError

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest


class FakeEngine:
    """A synchronous fake engine that echoes argv and a canned stdout."""

    def __init__(self, stdout: tuple[str, ...] = (), returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[tuple[str, ...]] = []

    def run(self, request: CommandRequest) -> t.Any:
        """Record the request and return a canned result."""
        from libtmux.experimental.engines.base import CommandResult

        self.calls.append(request.args)
        return CommandResult(
            cmd=("tmux", *request.args),
            stdout=self.stdout,
            stderr=() if self.returncode == 0 else ("boom",),
            returncode=self.returncode,
        )

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[t.Any]:
        """Execute each request in order."""
        return [self.run(req) for req in requests]


class AsyncFakeEngine:
    """An asynchronous fake engine mirroring :class:`FakeEngine`."""

    def __init__(self, stdout: tuple[str, ...] = (), returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode

    async def run(self, request: CommandRequest) -> t.Any:
        """Return a canned result asynchronously."""
        from libtmux.experimental.engines.base import CommandResult

        return CommandResult(
            cmd=("tmux", *request.args),
            stdout=self.stdout,
            returncode=self.returncode,
        )

    async def run_batch(self, requests: Sequence[CommandRequest]) -> list[t.Any]:
        """Execute each request in order."""
        return [await self.run(req) for req in requests]


def test_run_returns_typed_result() -> None:
    """``run`` renders, dispatches, and returns the operation's typed result."""
    engine = FakeEngine(stdout=("%9",))
    result = run(SplitWindow(target=WindowId("@1")), engine)
    assert result.new_pane_id == "%9"
    assert result.argv == ("split-window", "-t", "@1", "-v", "-P", "-F", "#{pane_id}")
    assert engine.calls == [result.argv]


def test_run_does_not_raise_on_failure() -> None:
    """A tmux failure is data on the result; ``run`` itself never raises."""
    engine = FakeEngine(returncode=1)
    result = run(SendKeys(target=PaneId("%9"), keys="x"), engine)
    assert result.failed
    with pytest.raises(TmuxCommandError):
        result.raise_for_status()


def test_run_version_threads_through() -> None:
    """The ``version`` argument reaches operation rendering."""
    from libtmux.experimental.ops import CapturePane

    engine = FakeEngine()
    result = run(
        CapturePane(target=PaneId("%1"), trim_trailing=True),
        engine,
        version="3.3",
    )
    assert "-T" not in result.argv


class VersionedFakeEngine(FakeEngine):
    """A sync fake engine that reports a fixed tmux version."""

    def __init__(
        self,
        *,
        tmux_version: str | None,
        stdout: tuple[str, ...] = (),
        returncode: int = 0,
    ) -> None:
        super().__init__(stdout=stdout, returncode=returncode)
        self._tmux_version = tmux_version

    def tmux_version(self) -> str | None:
        """Report the canned tmux version."""
        return self._tmux_version


def test_resolve_engine_version_prefers_explicit() -> None:
    """An explicit version always wins over the engine's reported version."""
    from libtmux.experimental.ops.execute import resolve_engine_version

    engine = VersionedFakeEngine(tmux_version="2.9")
    assert resolve_engine_version(engine, "3.4") == "3.4"


def test_resolve_engine_version_falls_back_to_engine() -> None:
    """With no explicit version, the engine's reported version is used."""
    from libtmux.experimental.ops.execute import resolve_engine_version

    engine = VersionedFakeEngine(tmux_version="2.9")
    assert resolve_engine_version(engine, None) == "2.9"


def test_resolve_engine_version_none_without_capability() -> None:
    """A plain engine (no version capability) resolves to None (assume latest)."""
    from libtmux.experimental.ops.execute import resolve_engine_version

    assert resolve_engine_version(FakeEngine(), None) is None


class _CapabilityCase(t.NamedTuple):
    """One engine and whether it reports a tmux version to the resolver."""

    test_id: str
    make_engine: t.Callable[[], object]
    reports_version: bool


_CAPABILITY_CASES: tuple[_CapabilityCase, ...] = (
    _CapabilityCase("subprocess", SubprocessEngine, True),
    _CapabilityCase("control_mode", ControlModeEngine, True),
    _CapabilityCase("async_control_mode", AsyncControlModeEngine, True),
    _CapabilityCase("mock", MockEngine, False),
)


@pytest.mark.parametrize(
    "case",
    _CAPABILITY_CASES,
    ids=[c.test_id for c in _CAPABILITY_CASES],
)
def test_engine_advertises_version_capability(case: _CapabilityCase) -> None:
    """Real-tmux engines satisfy SupportsTmuxVersion; simulators assume latest.

    A control-mode engine can query its server's version, so version-gated
    rendering must fire over it; an in-memory engine cannot, so it omits the
    capability and resolution assumes latest.
    """
    engine = case.make_engine()
    assert isinstance(engine, SupportsTmuxVersion) is case.reports_version


def test_run_auto_resolves_engine_version() -> None:
    """run() asks the engine for its version when none is passed; gating fires."""
    from libtmux.experimental.ops import CapturePane

    engine = VersionedFakeEngine(tmux_version="3.3")
    result = run(CapturePane(target=PaneId("%1"), trim_trailing=True), engine)
    assert "-T" not in result.argv  # -T is gated >= 3.4, dropped on resolved 3.3


def test_run_applies_break_pane_name_after_tmux_3_7_workaround() -> None:
    """A named tmux 3.7 break is completed by a typed rename operation."""
    engine = VersionedFakeEngine(tmux_version="3.7", stdout=("@9",))

    result = run(BreakPane(src_target=PaneId("%2"), name="logs"), engine)

    assert result.ok
    assert result.new_id == "@9"
    assert engine.calls == [
        (
            "break-pane",
            "-d",
            "-n",
            "libtmux",
            "-P",
            "-F",
            "#{window_id}",
            "-s",
            "%2",
        ),
        ("rename-window", "-t", "@9", "--", "logs"),
    ]
    assert result.argv == (*engine.calls[0], ";", *engine.calls[1])


@pytest.mark.parametrize(
    "stdout",
    (
        pytest.param((), id="absent_stdout"),
        pytest.param(("",), id="empty_line"),
        pytest.param((" \t ",), id="whitespace_line"),
    ),
)
def test_run_break_pane_3_7_missing_capture_skips_rename(
    stdout: tuple[str, ...],
) -> None:
    """A missing tmux 3.7 break id fails before constructing the rename target."""
    engine = VersionedFakeEngine(tmux_version="3.7", stdout=stdout)

    result = run(BreakPane(src_target=PaneId("%2"), name="logs"), engine)

    assert result.failed
    assert result.returncode == 0
    assert result.new_id is None
    assert result.stderr == ("break-pane did not capture its new window id",)
    assert len(engine.calls) == 1


def test_run_reports_break_pane_rename_failure() -> None:
    """A failed tmux 3.7 follow-up cannot report the requested name as applied."""
    from libtmux.experimental.engines import CommandResult

    class RenameFailsEngine(VersionedFakeEngine):
        def run(self, request: CommandRequest) -> t.Any:
            if request.args[0] == "rename-window":
                self.calls.append(request.args)
                return CommandResult(
                    cmd=("tmux", *request.args),
                    stderr=("rename failed",),
                    returncode=1,
                )
            return super().run(request)

    engine = RenameFailsEngine(tmux_version="3.7", stdout=("@9",))

    result = run(BreakPane(src_target=PaneId("%2"), name="logs"), engine)

    assert result.failed
    assert result.new_id == "@9"
    assert result.stderr == ("rename failed",)


def test_run_break_pane_3_7_captures_follow_up_target_internally() -> None:
    """A non-capturing caller still gets its named tmux 3.7 follow-up."""
    engine = VersionedFakeEngine(tmux_version="3.7", stdout=("@9",))

    result = run(
        BreakPane(src_target=PaneId("%2"), name="logs", capture=False),
        engine,
    )

    assert result.ok
    assert result.new_id is None
    assert engine.calls[0][4:7] == ("-P", "-F", "#{window_id}")
    assert engine.calls[1] == ("rename-window", "-t", "@9", "--", "logs")


def test_run_without_version_capability_renders_every_flag() -> None:
    """A plain engine has no version, so version-gated flags are kept."""
    from libtmux.experimental.ops import CapturePane

    engine = FakeEngine()
    result = run(CapturePane(target=PaneId("%1"), trim_trailing=True), engine)
    assert "-T" in result.argv


def test_arun_auto_resolves_engine_version() -> None:
    """arun() resolves the engine version on the async path too."""
    from libtmux.experimental.ops import CapturePane

    class AsyncVersionedFakeEngine(AsyncFakeEngine):
        def tmux_version(self) -> str | None:
            return "3.3"

    engine = AsyncVersionedFakeEngine()
    result = asyncio.run(
        arun(CapturePane(target=PaneId("%1"), trim_trailing=True), engine),
    )
    assert "-T" not in result.argv


def test_arun_shares_render_and_build() -> None:
    """``arun`` produces the same typed result as ``run`` via the async path."""
    engine = AsyncFakeEngine(stdout=("%5",))
    result = asyncio.run(arun(SplitWindow(target=WindowId("@1")), engine))
    assert result.new_pane_id == "%5"
    assert result.ok


def test_arun_applies_break_pane_name_after_tmux_3_7_workaround() -> None:
    """The async executor applies the same typed rename follow-up."""

    class AsyncTmux37Engine(AsyncFakeEngine):
        def __init__(self) -> None:
            super().__init__(stdout=("@5",))
            self.calls: list[tuple[str, ...]] = []

        def tmux_version(self) -> str | None:
            return "3.7"

        async def run(self, request: CommandRequest) -> t.Any:
            self.calls.append(request.args)
            return await super().run(request)

    engine = AsyncTmux37Engine()
    result = asyncio.run(
        arun(BreakPane(src_target=PaneId("%2"), name="logs"), engine),
    )

    assert result.ok
    assert engine.calls[-1] == ("rename-window", "-t", "@5", "--", "logs")
