"""Conftest.py (root-level).

We keep this in root pytest fixtures in pytest's doctest plugin to be available, as well
as avoiding conftest.py from being included in the wheel, in addition to pytest_plugin
for pytester only being available via the root directory.

See "pytest_plugins in non-top-level conftest files" in
https://docs.pytest.org/en/stable/deprecations.html
"""

from __future__ import annotations

import shutil
import typing as t

import pytest
from _pytest.doctest import DoctestItem

from libtmux.pane import Pane
from libtmux.pytest_plugin import USING_ZSH
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

if t.TYPE_CHECKING:
    import pathlib

pytest_plugins = ["pytester"]


@pytest.fixture(autouse=True)
def add_doctest_fixtures(
    request: pytest.FixtureRequest,
    doctest_namespace: dict[str, t.Any],
) -> None:
    """Configure doctest fixtures for pytest-doctest."""
    if isinstance(request._pyfuncitem, DoctestItem) and shutil.which("tmux"):
        request.getfixturevalue("set_home")
        doctest_namespace["Server"] = Server
        doctest_namespace["Session"] = Session
        doctest_namespace["Window"] = Window
        doctest_namespace["Pane"] = Pane
        doctest_namespace["server"] = request.getfixturevalue("server")
        doctest_namespace["Server"] = request.getfixturevalue("TestServer")
        session: Session = request.getfixturevalue("session")
        doctest_namespace["session"] = session
        doctest_namespace["window"] = session.active_window
        doctest_namespace["pane"] = session.active_pane
        doctest_namespace["request"] = request


@pytest.fixture(autouse=True)
def set_home(
    monkeypatch: pytest.MonkeyPatch,
    user_path: pathlib.Path,
) -> None:
    """Configure home directory for pytest tests."""
    monkeypatch.setenv("HOME", str(user_path))


@pytest.fixture(autouse=True)
def setup_fn(
    clear_env: None,
) -> None:
    """Function-level test configuration fixtures for pytest."""


@pytest.fixture(autouse=True, scope="session")
def setup_session(
    request: pytest.FixtureRequest,
    config_file: pathlib.Path,
) -> None:
    """Session-level test configuration for pytest."""
    if USING_ZSH:
        request.getfixturevalue("zshrc")


# Async test fixtures
# These require pytest-asyncio to be installed
import asyncio

import pytest_asyncio


@pytest_asyncio.fixture
async def async_server(server: Server):
    """Async wrapper for sync server fixture.

    Provides async context while using proven sync server isolation.
    Server has unique socket name from libtmux_test{random}.

    The sync server fixture creates a Server with:
    - Unique socket name: libtmux_test{8-random-chars}
    - Automatic cleanup via request.addfinalizer
    - Complete isolation from developer's tmux sessions

    This wrapper just ensures we're in an async context.
    All cleanup is handled by the parent sync fixture.
    """
    await asyncio.sleep(0)  # Ensure in async context
    yield server
    # Cleanup handled by sync fixture's finalizer


@pytest_asyncio.fixture
async def async_test_server(TestServer: t.Callable[..., Server]):
    """Async wrapper for TestServer factory fixture.

    Returns factory that creates servers with unique sockets.
    Each call to factory() creates new isolated server.

    The sync TestServer fixture creates a factory that:
    - Generates unique socket names per call
    - Tracks all created servers
    - Cleans up all servers via request.addfinalizer

    Usage in async tests:
        server1 = async_test_server()  # Creates server with unique socket
        server2 = async_test_server()  # Creates another with different socket

    This wrapper just ensures we're in an async context.
    All cleanup is handled by the parent sync fixture.
    """
    await asyncio.sleep(0)  # Ensure in async context
    yield TestServer
    # Cleanup handled by TestServer's finalizer
