"""Tests for libtmux pytest plugin."""

from __future__ import annotations

import textwrap
import time
import typing as t

if t.TYPE_CHECKING:
    import pathlib

    import pytest

    from libtmux.server import Server


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
