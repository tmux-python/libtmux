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

from libtmux._internal import trace as libtmux_trace
from libtmux.pane import Pane
from libtmux.pytest_plugin import USING_ZSH
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

if t.TYPE_CHECKING:
    import pathlib

pytest_plugins = ["pytester"]


@pytest.fixture(autouse=True, scope="session")
def trace_session() -> None:
    """Initialize trace collection when enabled."""
    if not libtmux_trace.TRACE_ENABLED:
        return
    if libtmux_trace.TRACE_RESET:
        libtmux_trace.reset_trace()


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print trace summary in pytest's terminal summary."""
    if not libtmux_trace.TRACE_ENABLED:
        return
    terminalreporter.section("libtmux trace")
    terminalreporter.write_line(libtmux_trace.summarize())


@pytest.fixture(autouse=True)
def trace_test_context(request: pytest.FixtureRequest) -> t.Iterator[None]:
    """Attach the current pytest node id to trace events."""
    if not libtmux_trace.TRACE_ENABLED:
        yield
        return
    libtmux_trace.set_test_context(request.node.nodeid)
    yield
    libtmux_trace.set_test_context(None)


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
