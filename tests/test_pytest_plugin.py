"""Tests for libtmux pytest plugin."""

from __future__ import annotations

import contextlib
import os
import pathlib
import textwrap
import typing as t

from libtmux.engines import SubprocessEngine
from libtmux.pytest_plugin import _reap_test_server
from libtmux.server import Server
from libtmux.test.retry import retry_until

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


def test_plugin_imsg_engine_option(pytester: pytest.Pytester) -> None:
    """The plugin fixtures honor ``--engine=imsg``."""
    pytester.plugins = ["pytest_plugin"]
    pytester.makepyfile(
        test_plugin_imsg_engine_option="""
from libtmux.engines import ImsgEngine

def test_server_uses_imsg(server) -> None:
    assert isinstance(server.engine, ImsgEngine)
    session = server.new_session(session_name="imsg-plugin")
    assert session.session_name == "imsg-plugin"
""",
    )

    result = pytester.runpytest("--engine=imsg", "-vv")
    result.assert_outcomes(passed=1)


def test_plugin_subprocess_engine_option(pytester: pytest.Pytester) -> None:
    """The plugin fixtures honor ``--engine=subprocess`` explicitly."""
    pytester.plugins = ["pytest_plugin"]
    pytester.makepyfile(
        test_plugin_subprocess_engine_option="""
from libtmux.engines import SubprocessEngine

def test_server_uses_subprocess(server) -> None:
    assert isinstance(server.engine, SubprocessEngine)
""",
    )

    result = pytester.runpytest("--engine=subprocess", "-vv")
    result.assert_outcomes(passed=1)


def test_plugin_rejects_invalid_engine_option(pytester: pytest.Pytester) -> None:
    """Pytest argument parsing rejects unknown libtmux engine values."""
    pytester.plugins = ["pytest_plugin"]
    pytester.makepyfile(
        test_plugin_rejects_invalid_engine_option="""
def test_placeholder() -> None:
    assert True
""",
    )

    result = pytester.runpytest("--engine=bogus")
    assert result.ret != 0
    result.stderr.fnmatch_lines(["*argument --engine: invalid choice:*"])


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


def test_pin_test_shell_env_aligns_shell_with_default_shell() -> None:
    """The autouse plugin fixture pins ``$SHELL`` to ``/bin/sh``.

    Code that compares ``os.getenv("SHELL")`` against the tmux pane's
    running command (notably tmuxp's ``test_automatic_rename_option``)
    must see ``/bin/sh`` to match the ``default-shell`` pinned in
    :func:`config_file`. Because the alignment fixture is autouse from
    the libtmux pytest plugin, every test that loads the plugin —
    including external consumers — gets the alignment without explicit
    fixture opt-in.
    """
    assert os.environ.get("SHELL") == "/bin/sh"


def test_config_file_pins_minimal_test_shell(config_file: pathlib.Path) -> None:
    """The shipped ``.tmux.conf`` pins ``/bin/sh`` as the default shell.

    Forcing ``default-shell`` to ``/bin/sh`` skips the developer's
    interactive shell init (~60ms per pane for zsh) and eliminates the
    non-deterministic prompt rendering that flakes ``capture-pane`` and
    ``automatic-rename`` assertions. The ``base-index 1`` line is
    behavioral and must remain. ``default-command`` is intentionally
    NOT set so consumer test workspaces can override ``default-shell``
    per-session (per tmux's ``cmd-new-window.c``, ``default-command``
    always wins, which would short-circuit those overrides).
    """
    content = config_file.read_text()
    assert "set -g base-index 1" in content
    assert "set -g default-shell /bin/sh" in content
    assert "set -g default-command" not in content


def test_test_server_uses_default_subprocess_engine(
    TestServer: t.Callable[..., Server],
) -> None:
    """TestServer inherits the default subprocess engine."""
    server = TestServer()
    assert isinstance(server.engine, SubprocessEngine)


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


def test_test_server_can_use_imsg_engine(pytester: pytest.Pytester) -> None:
    """TestServer inherits ``--engine=imsg`` from the plugin config."""
    pytester.plugins = ["pytest_plugin"]
    pytester.makepyfile(
        test_test_server_can_use_imsg_engine="""
from libtmux.engines import ImsgEngine

def test_test_server_factory_uses_imsg(TestServer) -> None:
    server = TestServer()
    assert isinstance(server.engine, ImsgEngine)
    session = server.new_session(session_name="factory-imsg")
    assert session.session_name == "factory-imsg"
""",
    )

    result = pytester.runpytest("--engine=imsg", "-vv")
    result.assert_outcomes(passed=1)


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

    # Delete server and verify cleanup. Poll the socket until tmux's
    # async unlink completes, replacing a flaky time.sleep(0.1).
    server.kill()
    assert retry_until(
        lambda: not server.is_alive(),
        seconds=2,
    )

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
