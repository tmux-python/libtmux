"""Configure root-level pytest fixtures for libtmux.

We keep this file at the root to make these fixtures available to all
tests, while also preventing unwanted inclusion in the distributed
wheel. Additionally, `pytest_plugins` references ensure that the
`pytester` plugin is accessible for test generation and execution.

See Also
--------
pytest_plugins in non-top-level conftest files
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
    """Configure doctest fixtures for pytest-doctest.

    Automatically sets up tmux-related classes and default fixtures,
    making them available in doctest namespaces if `tmux` is found
    on the system. This ensures that doctest blocks referencing tmux
    structures can execute smoothly in the test environment.
    """
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
    """Set the HOME environment variable to the temporary user directory."""
    monkeypatch.setenv("HOME", str(user_path))


@pytest.fixture(autouse=True)
def setup_fn(
    clear_env: None,
) -> None:
    """Apply function-level test fixture configuration (e.g., environment cleanup)."""


@pytest.fixture(autouse=True, scope="session")
def setup_session(
    request: pytest.FixtureRequest,
    config_file: pathlib.Path,
) -> None:
    """Apply session-level test fixture configuration for libtmux testing.

    If zsh is in use, applies a suppressing `.zshrc` fix to avoid
    default interactive messages that might disrupt tmux sessions.
    """
    if USING_ZSH:
        request.getfixturevalue("zshrc")
