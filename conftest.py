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


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add CLI options for selecting tmux engine."""
    parser.addoption(
        "--engine",
        action="store",
        default="subprocess",
        choices=["subprocess", "control"],
        help="Select tmux engine for fixtures (default: subprocess).",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        (
            "engines(names): run the test once for each engine in 'names' "
            "(e.g. ['control', 'subprocess'])."
        ),
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize engine_name when requested by tests."""
    if "engine_name" in metafunc.fixturenames:
        marker = metafunc.definition.get_closest_marker("engines")
        if marker:
            params = list(marker.args[0])
        else:
            params = [metafunc.config.getoption("--engine")]
        metafunc.parametrize("engine_name", params, indirect=True)
