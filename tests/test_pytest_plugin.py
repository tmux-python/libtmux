"""Tests for libtmux pytest plugin."""

from __future__ import annotations

import contextlib
import os
import pathlib
import textwrap
import time
import typing as t

from libtmux.pytest_plugin import _reap_test_server
from libtmux.server import Server

if t.TYPE_CHECKING:
    import pytest


def test_plugin(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test libtmux pytest plugin."""
    # Initialize variables
    pytester.plugins = ["pytest_plugin"]
    pytester.makefile(
        ".ini",
        pytest=textwrap.dedent(
            """
[pytest]
addopts=-vv
        """.strip(),
        ),
    )
    pytester.makeconftest(
        textwrap.dedent(
            r"""
import pathlib
import pytest

@pytest.fixture(autouse=True)
def setup(
    request: pytest.FixtureRequest,
) -> None:
    pass
    """,
        ),
    )
    tests_path = pytester.path / "tests"
    files = {
        "example.py": textwrap.dedent(
            """
import pathlib

def test_repo_git_remote_checkout(
    session,
) -> None:
    assert session.session_name is not None

    assert session.session_id == "$1"

    new_window = session.new_window(attach=False, window_name="my window name")
    assert new_window.window_name == "my window name"
        """,
        ),
    }
    first_test_key = next(iter(files.keys()))
    first_test_filename = str(tests_path / first_test_key)

    tests_path.mkdir()
    for file_name, text in files.items():
        test_file = tests_path / file_name
        test_file.write_text(
            text,
            encoding="utf-8",
        )

    # Test
    result = pytester.runpytest(str(first_test_filename))
    result.assert_outcomes(passed=1)


def test_test_server(TestServer: t.Callable[..., Server]) -> None:
    """Test TestServer creates and cleans up server."""
    server = TestServer()
    assert server.is_alive() is False  # Server not started yet

    session = server.new_session()
    assert server.is_alive() is True
    assert len(server.sessions) == 1
    assert session.session_name is not None

    # Test socket name is unique
    assert server.socket_name is not None
    assert server.socket_name.startswith("libtmux_test")

    # Each call creates a new server with unique socket
    server2 = TestServer()
    assert server2.socket_name is not None
    assert server2.socket_name.startswith("libtmux_test")
    assert server2.socket_name != server.socket_name


def test_test_server_with_config(
    TestServer: t.Callable[..., Server],
    tmp_path: pathlib.Path,
) -> None:
    """Test TestServer with config file."""
    config_file = tmp_path / "tmux.conf"
    config_file.write_text("set -g status off", encoding="utf-8")

    server = TestServer(config_file=str(config_file))
    session = server.new_session()

    # Verify config was loaded
    assert session.cmd("show-options", "-g", "status").stdout[0] == "status off"


def test_test_server_cleanup(TestServer: t.Callable[..., Server]) -> None:
    """Test TestServer properly cleans up after itself."""
    server = TestServer()
    socket_name = server.socket_name
    assert socket_name is not None

    # Create multiple sessions
    server.new_session(session_name="test1")
    server.new_session(session_name="test2")
    assert len(server.sessions) == 2

    # Verify server is alive
    assert server.is_alive() is True

    # Delete server and verify cleanup
    server.kill()
    time.sleep(0.1)  # Give time for cleanup

    # Create new server to verify old one was cleaned up
    new_server = TestServer()
    assert new_server.is_alive() is False  # Server not started yet
    new_server.new_session()  # This should work if old server was cleaned up
    assert new_server.is_alive() is True


def test_test_server_multiple(TestServer: t.Callable[..., Server]) -> None:
    """Test multiple TestServer instances can coexist."""
    server1 = TestServer()
    server2 = TestServer()

    # Each server should have a unique socket
    assert server1.socket_name != server2.socket_name

    # Create sessions in each server
    server1.new_session(session_name="test1")
    server2.new_session(session_name="test2")

    # Verify sessions are in correct servers
    assert any(s.session_name == "test1" for s in server1.sessions)
    assert any(s.session_name == "test2" for s in server2.sessions)
    assert not any(s.session_name == "test1" for s in server2.sessions)
    assert not any(s.session_name == "test2" for s in server1.sessions)


def _libtmux_socket_dir() -> pathlib.Path:
    """Resolve the tmux socket directory tmux uses for this uid."""
    tmux_tmpdir = pathlib.Path(os.environ.get("TMUX_TMPDIR", "/tmp"))
    return tmux_tmpdir / f"tmux-{os.geteuid()}"


def test_reap_test_server_unlinks_socket_file() -> None:
    """``_reap_test_server`` kills the daemon *and* unlinks the socket.

    Regression for #660: tmux does not reliably ``unlink(2)`` its socket
    on non-graceful exit. Before this fix the plugin's finalizer only
    called ``server.kill()``, so ``/tmp/tmux-<uid>/`` accumulated stale
    ``libtmux_test*`` socket files over time.

    This test boots a real tmux daemon on a unique socket, confirms the
    socket file exists, invokes the reaper, and asserts the file is
    gone.
    """
    server = Server(socket_name="libtmux_test_reap_unlink")
    server.new_session(session_name="reap_probe")
    socket_path = _libtmux_socket_dir() / "libtmux_test_reap_unlink"
    try:
        assert socket_path.exists(), (
            f"expected tmux to have created {socket_path}, but it is missing"
        )

        _reap_test_server("libtmux_test_reap_unlink")

        assert not socket_path.exists(), (
            f"_reap_test_server should have unlinked {socket_path}"
        )
    finally:
        # Belt-and-braces: if the assertion above fired before the
        # unlink, don't leak the socket the next run of this test.
        with contextlib.suppress(OSError):
            socket_path.unlink(missing_ok=True)


def test_reap_test_server_is_noop_when_socket_missing() -> None:
    """Reaping a non-existent socket succeeds silently.

    Finalizers run even when the fixture failed before the daemon ever
    started; the reaper must tolerate the case where the socket file
    never existed.
    """
    bogus_name = "libtmux_test_reap_never_existed_xyz"
    socket_path = _libtmux_socket_dir() / bogus_name
    assert not socket_path.exists()

    # Should not raise.
    _reap_test_server(bogus_name)


def test_reap_test_server_tolerates_none() -> None:
    """``_reap_test_server(None)`` is a no-op, not a crash.

    The ``server`` fixture's finalizer passes ``server.socket_name``,
    which is typed ``str | None``. Tolerate ``None`` for symmetry with
    other nullable paths in the API.
    """
    _reap_test_server(None)


def test_clear_env_drops_outer_tmux_session(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``clear_env`` drops ``TMUX`` and ``TMUX_PANE``.

    A client with neither ``-L`` nor ``-S`` follows ``$TMUX`` to the outer server.
    """
    monkeypatch.setenv("TMUX", "/nonexistent/outer,1,0")
    monkeypatch.setenv("TMUX_PANE", "%0")
    pytester.plugins = ["pytest_plugin"]
    pytester.makepyfile(
        textwrap.dedent(
            """
import os

def test_inner(clear_env) -> None:
    assert "TMUX" not in os.environ
    assert "TMUX_PANE" not in os.environ
            """,
        ),
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


FAILING_TEST = textwrap.dedent(
    """
    def test_fails(session):
        assert session.session_name is None
    """,
)


def test_failure_report_names_attach_command(pytester: pytest.Pytester) -> None:
    """A failing test with tmux fixtures reports how to attach to its server."""
    pytester.makepyfile(FAILING_TEST)

    result = pytester.runpytest()

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*Attach to the tmux server this test used:*"])
    attach = next(
        line.strip()
        for line in result.stdout.lines
        if line.strip().startswith("tmux -S ")
    )
    assert " attach -t libtmux_" in attach
    assert "resize-window -x" in attach


def test_passing_test_reports_nothing(pytester: pytest.Pytester) -> None:
    """A passing test leaves no attach command in the output."""
    pytester.makepyfile("def test_ok(session):\n    assert session.session_name\n")

    result = pytester.runpytest("-rA")

    result.assert_outcomes(passed=1)
    assert "tmux -S" not in result.stdout.str()


def test_keep_failed_leaves_server_running(pytester: pytest.Pytester) -> None:
    """``--libtmux-keep-failed`` keeps a failed test's server until killed."""
    pytester.makepyfile(FAILING_TEST)

    result = pytester.runpytest("--libtmux-keep-failed")

    result.assert_outcomes(failed=1)
    kill = next(
        line.strip()
        for line in result.stdout.lines
        if line.strip().endswith(" kill-server")
    )
    socket_path = pathlib.Path(kill.split()[2])
    server = Server(socket_path=socket_path)
    try:
        assert server.is_alive()
    finally:
        server.kill()
    assert not server.is_alive()


def test_default_reaps_failed_server(pytester: pytest.Pytester) -> None:
    """Without the flag, a failed test's server is reaped at teardown."""
    pytester.makepyfile(FAILING_TEST)

    result = pytester.runpytest()

    attach = next(
        line.strip()
        for line in result.stdout.lines
        if line.strip().startswith("tmux -S ")
    )
    server = Server(socket_path=pathlib.Path(attach.split()[2]))
    assert not server.is_alive()


def test_reap_test_server_unlinks_socket_under_empty_tmux_tmpdir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty ``$TMUX_TMPDIR`` means ``/tmp`` to tmux, and to the reaper."""
    monkeypatch.setenv("TMUX_TMPDIR", "")
    name = "libtmux_test_reap_empty_tmpdir"
    server = Server(socket_name=name)
    server.new_session(session_name="reap_probe")
    socket_path = pathlib.Path("/tmp") / f"tmux-{os.geteuid()}" / name
    try:
        assert socket_path.exists()

        _reap_test_server(name)

        assert not socket_path.exists()
    finally:
        with contextlib.suppress(OSError):
            socket_path.unlink(missing_ok=True)
