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

from libtmux.common import get_version
from libtmux.pane import Pane
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


@pytest.fixture(autouse=True)
def _reset_get_version_cache() -> t.Generator[None, None, None]:
    """Clear ``libtmux.common.get_version`` lru_cache around every test.

    ``get_version`` is memoized per ``tmux_bin`` so production code only
    forks ``tmux -V`` once per process. Tests that monkeypatch
    ``tmux_cmd`` to return synthetic versions, or that exercise the real
    binary, otherwise leak cached values across tests and produce
    order-dependent failures.
    """
    yield
    get_version.cache_clear()


@pytest.fixture(autouse=True)
def _reset_engine_tmux_bin_cache() -> t.Generator[None, None, None]:
    """Reset cached ``shutil.which("tmux")`` paths on the default engine.

    Both engines memoize the resolved tmux binary per instance. The
    module-level ``_builtin_default_engine`` survives across tests, so
    monkeypatching PATH to simulate a missing tmux requires invalidating
    its cache before each test or the cached lookup wins.
    """
    from libtmux import common as libtmux_common
    from libtmux.engines.imsg import ImsgEngine
    from libtmux.engines.subprocess import SubprocessEngine

    builtin = libtmux_common._builtin_default_engine
    if isinstance(builtin, SubprocessEngine):
        builtin._resolved_default_tmux_bin = None
    elif isinstance(builtin, ImsgEngine):
        builtin._resolved_tmux_bin = None
    yield


@pytest.fixture(autouse=True, scope="session")
def setup_session(
    request: pytest.FixtureRequest,
    config_file: pathlib.Path,
) -> None:
    """Session-level test configuration for pytest.

    Requesting ``config_file`` here forces the ``.tmux.conf`` fixture
    to be materialized once per session even when no test requests
    it directly.
    """
    del request, config_file
