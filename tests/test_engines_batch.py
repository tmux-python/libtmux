"""Tests for :mod:`libtmux.engines.batch`: command groups with per-request results."""

from __future__ import annotations

import subprocess
import typing as t

import pytest

from libtmux.engines import (
    CommandRequest,
    CommandResult,
    ControlModeEngine,
    ExecEngine,
    SubprocessEngine,
)
from libtmux.engines.batch import (
    NOT_RUN,
    NOT_RUN_RETURNCODE,
    group_request,
    run_group,
    split_group_result,
)

if t.TYPE_CHECKING:
    from collections.abc import Iterator

    from libtmux.engines import TmuxEngine
    from libtmux.server import Server
    from libtmux.session import Session


def req(*args: str) -> CommandRequest:
    """Build a request."""
    return CommandRequest.from_args(*args)


@pytest.fixture(params=["subprocess", "exec", "control"])
def engine(request: pytest.FixtureRequest, session: Session) -> Iterator[TmuxEngine]:
    """Yield each engine kind bound to the test server."""
    server = session.server
    if request.param == "subprocess":
        yield SubprocessEngine.for_server(server)
    elif request.param == "exec":
        yield ExecEngine().with_connection(
            SubprocessEngine.for_server(server).connection,
        )
    else:
        control = ControlModeEngine.for_server(server)
        try:
            yield control
        finally:
            control.close()


def option(server: Server, name: str) -> str:
    """Read a global user option, ``""`` when unset."""
    return "\n".join(server.cmd("show-options", "-gqv", name).stdout)


def test_group_attributes_output_to_each_request(engine: TmuxEngine) -> None:
    """Each command's own lines come back on its own result."""
    results = run_group(
        engine,
        [
            req("display-message", "-p", "one"),
            req("set-option", "-g", "@g", "x"),
            req("display-message", "-p", "two"),
        ],
    )
    assert [r.stdout for r in results] == [("one",), (), ("two",)]
    assert all(r.ok for r in results)


def test_failing_middle_command_stops_the_group(
    engine: TmuxEngine,
    session: Session,
) -> None:
    """A three-command group with a failing middle gives three attributed results."""
    results = run_group(
        engine,
        [
            req("set-option", "-g", "@first", "1"),
            req("kill-window", "-t", "@9999"),
            req("set-option", "-g", "@third", "3"),
        ],
    )
    first, failed, skipped = results
    assert first.ok
    assert not failed.ok
    assert failed.returncode == 1
    assert any("@9999" in line for line in failed.stderr)
    assert skipped.returncode == NOT_RUN_RETURNCODE
    assert skipped.stderr == NOT_RUN
    assert not skipped.ok
    assert option(session.server, "@first") == "1"
    assert option(session.server, "@third") == ""


def test_semicolons_in_data_are_not_boundaries(
    engine: TmuxEngine,
    session: Session,
) -> None:
    """Data ending in or holding ``;`` stays data inside a group, on every engine."""
    values = ["a;b;", ";", "mid;dle", r"end\;"]
    requests = [req("set-option", "-g", f"@v{i}", v) for i, v in enumerate(values)]
    requests += [req("display-message", "-p", f"fmt:{v}") for v in values]
    results = run_group(engine, requests)
    assert all(r.ok for r in results), [r.stderr for r in results]
    assert [r.stdout for r in results[len(values) :]] == [(f"fmt:{v}",) for v in values]
    assert [option(session.server, f"@v{i}") for i in range(len(values))] == values


def test_group_runs_in_one_process(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Twelve commands cost one fork as a group and twelve as sequential calls."""
    engine = SubprocessEngine.for_server(session.server)
    requests = [req("set-option", "-g", f"@p{i}", str(i)) for i in range(12)]
    spawned = 0
    real = subprocess.Popen

    class Counting(real):  # type: ignore[misc, valid-type]
        def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
            nonlocal spawned
            spawned += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", Counting)
    run_group(engine, requests)
    grouped = spawned
    spawned = 0
    engine.run_batch(requests)
    assert (grouped, spawned) == (1, 12)


def test_pipelined_control_batch_keeps_order_and_runs_past_a_failure(
    session: Session,
) -> None:
    """``run_batch`` on control mode is independent: a failure does not stop it."""
    with ControlModeEngine.for_server(session.server) as engine:
        first, bad, third, shown = engine.run_batch(
            [
                req("set-option", "-g", "@pipe1", "1"),
                req("kill-window", "-t", "@9999"),
                req("set-option", "-g", "@pipe3", "3"),
                req("show-options", "-gqv", "@pipe3"),
            ],
        )
    assert (first.ok, bad.ok, third.ok) == (True, False, True)
    assert shown.stdout == ("3",)


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(
            CommandRequest(args=("load-buffer", "-"), input="x"),
            id="input",
        ),
        pytest.param(req("run-shell", "true"), id="run-shell"),
        pytest.param(req("wait-for", "x"), id="wait-for"),
        pytest.param(req("attach-session"), id="attach"),
        pytest.param(CommandRequest(args=("list-sessions",), tmux_bin="x"), id="bin"),
    ],
)
def test_group_refuses_requests_it_cannot_carry(bad: CommandRequest) -> None:
    """Input, waiting commands and terminals cannot share a command list."""
    with pytest.raises(ValueError, match="group"):
        group_request([req("list-sessions"), bad], "t0")


class MarkerEngine:
    """An in-memory engine: echoes group markers, failing at a chosen command."""

    def __init__(self, fail_at: int | None = None) -> None:
        self.requests: list[CommandRequest] = []
        self.fail_at = fail_at

    def run(self, request: CommandRequest) -> CommandResult:
        """Echo every marker before the failure."""
        self.requests.append(request)
        markers = [a for a in request.args if a.startswith("libtmux-group-")]
        failed = self.fail_at is not None and self.fail_at < len(markers)
        shown = markers[: self.fail_at] if failed else markers
        return CommandResult(
            cmd=("tmux", *request.args),
            stdout=tuple(shown),
            stderr=("boom",) if failed else (),
            returncode=1 if failed else 0,
        )

    def run_batch(self, requests: t.Sequence[CommandRequest]) -> list[CommandResult]:
        """Run each request alone."""
        return [self.run(r) for r in requests]


def test_long_group_splits_under_the_command_limit() -> None:
    """A group above tmux's 16 KiB limit becomes several lists, still in order."""
    engine = MarkerEngine()
    requests = [req("set-option", "-g", f"@l{i}", "v" * 3000) for i in range(10)]
    results = run_group(engine, requests)
    assert len(results) == 10
    assert len(engine.requests) > 1
    assert all(sum(len(a) + 1 for a in r.args) < 16_384 for r in engine.requests)


def test_failure_in_one_chunk_skips_later_chunks() -> None:
    """The group stops at the first failure across chunk boundaries."""
    engine = MarkerEngine(fail_at=1)
    requests = [req("set-option", "-g", f"@l{i}", "v" * 3000) for i in range(10)]
    results = run_group(engine, requests)
    assert len(engine.requests) == 1
    assert [r.returncode for r in results[:2]] == [0, 1]
    assert {r.returncode for r in results[2:]} == {NOT_RUN_RETURNCODE}


def test_split_attributes_by_marker() -> None:
    """The split is pure: markers close each command, the first gap is the failure."""
    requests = [req("a"), req("b"), req("c")]
    joined = CommandResult(
        cmd=("tmux",),
        stdout=("a-out", "libtmux-group-t:0", "b-partial"),
        stderr=("bad",),
        returncode=1,
    )
    first, second, third = split_group_result(requests, joined, "t")
    assert first.stdout == ("a-out",)
    assert (second.stdout, second.stderr, second.returncode) == (
        ("b-partial",),
        ("bad",),
        1,
    )
    assert third.returncode == NOT_RUN_RETURNCODE
