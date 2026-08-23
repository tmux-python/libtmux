"""Tests for the benchmark primitives shared across libtmux's benchmarks."""

from __future__ import annotations

import importlib.util
import math
import pathlib
import typing as t

import pytest

if t.TYPE_CHECKING:
    import types

_BENCH = pathlib.Path(__file__).parent.parent / "scripts" / "bench"


@pytest.fixture(scope="module")
def primitives() -> types.ModuleType:
    """Load the primitives by path; ``scripts`` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "primitives", _BENCH / "primitives.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_primitives_do_not_reach_the_experimental_package(
    primitives: types.ModuleType,
) -> None:
    """They exist to be shared by benchmarks that predate the engines.

    A primitive that imported an engine would make the seam's own benchmark
    depend on the layer it is meant to be the baseline for.
    """
    source = (_BENCH / "primitives.py").read_text(encoding="utf-8")

    assert "libtmux.experimental" not in source
    assert "from libtmux.server import Server" in source


def test_parse_shape_reads_windows_by_panes(primitives: types.ModuleType) -> None:
    """``8x4`` is eight windows of four panes, case-insensitively."""
    assert primitives.parse_shape("8x4") == (8, 4)
    assert primitives.parse_shape("2X1") == (2, 1)


def test_uniq_never_repeats(primitives: types.ModuleType) -> None:
    """Session names must not collide across builds in one process."""
    names = {primitives.uniq() for _ in range(50)}

    assert len(names) == 50


def test_percentile_is_nearest_rank(primitives: types.ModuleType) -> None:
    """The reported percentile is an observed sample, not an interpolation."""
    values = [1.0, 2.0, 3.0, 4.0]

    assert primitives.percentile(values, 100) == 4.0
    assert primitives.percentile(values, 50) in values
    assert math.isnan(primitives.percentile([], 50))


def test_summarize_reports_every_labelled_statistic(
    primitives: types.ModuleType,
) -> None:
    """Whatever STAT_LABELS advertises, summarize must actually return."""
    summary = primitives.summarize([1.0, 2.0, 3.0, 4.0])

    assert set(summary) == set(primitives.STAT_LABELS)
    assert summary["n"] == 4.0
    assert summary["min"] == 1.0
    assert summary["max"] == 4.0
    assert summary["median"] == 2.5


def test_new_server_pins_itself_above_zero_sessions(
    primitives: types.ModuleType,
) -> None:
    """The keepalive is what stops tmux's exit-empty teardown racing a build.

    Without it a cell that kills its own session drops the server to zero, and
    the next build can reach the socket mid-shutdown. Asserting the session
    exists is asserting that guard is still in place.
    """
    server = primitives.new_server()
    try:
        names = [s.name for s in server.sessions]

        assert primitives.KEEPALIVE in names
        assert server.is_alive()
    finally:
        server.kill()


def test_build_classic_creates_the_requested_shape(
    primitives: types.ModuleType,
) -> None:
    """Two windows of two panes is what ``2x2`` has to produce."""
    server = primitives.new_server()
    try:
        primitives.build_classic(server, "shape", 2, 2)
        session = next(s for s in server.sessions if s.name == "shape")

        assert len(session.windows) == 2
        for window in session.windows:
            assert len(window.panes) == 2
    finally:
        server.kill()


def test_reap_leaves_a_live_scratch_dir_alone(
    primitives: types.ModuleType,
) -> None:
    """A directory with a running server may belong to a concurrent run.

    Stealing another run's servers would be worse than leaking, so the reaper
    is deliberately conservative and this pins that choice.
    """
    server = primitives.new_server()
    try:
        assert primitives.SOCK_DIR.is_dir()
        reaped = primitives.reap_stale_scratch()

        assert isinstance(reaped, int)
        assert primitives.SOCK_DIR.is_dir()
    finally:
        server.kill()


def test_new_server_ignores_the_calling_user_s_tmux_config(
    primitives: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A benchmark that reads ``~/.tmux.conf`` measures that file, not libtmux.

    tmux loads the invoking user's configuration when a server starts, so
    without an explicit one the numbers move with whatever the machine happens
    to set -- history limits, hooks, a slow ``default-shell``. A unique socket
    isolates the server from other servers; it does nothing about the
    configuration, and this module promises isolation rather than a fresh
    socket.
    """
    (tmp_path / ".tmux.conf").write_text(
        "set-option -g history-limit 4242\n", encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    server = primitives.new_server()
    try:
        limit = server.cmd("show-options", "-gv", "history-limit").stdout

        assert limit != ["4242"]
    finally:
        server.kill()
