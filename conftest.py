"""Conftest.py (root-level).

We keep this in root pytest fixtures in pytest's doctest plugin to be available, as well
as avoiding conftest.py from being included in the wheel, in addition to pytest_plugin
for pytester only being available via the root directory.

See "pytest_plugins in non-top-level conftest files" in
https://docs.pytest.org/en/stable/deprecations.html
"""

from __future__ import annotations

import functools
import shutil
import typing as t

import pytest
from _pytest.doctest import DoctestItem

from libtmux._internal.control_mode import ControlMode
from libtmux.client import Client
from libtmux.pane import Pane
from libtmux.pytest_plugin import USING_ZSH
from libtmux.server import Server
from libtmux.session import Session
from libtmux.test.retry import retry_until
from libtmux.window import Window

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

pytest_plugins = ["pytester"]


def _requested_benchmarks_directly(args: Sequence[str]) -> bool:
    """Return True if a positional argument names ``benchmarks`` directly.

    Guards against firing on a broader scan (e.g. ``pytest .``) that
    merely walks through ``benchmarks/`` on its way elsewhere -- only an
    invocation that explicitly names that bare path should raise. A path
    to one file inside it (``benchmarks/bench_capture.py::test_x``)
    already collected its item and needs no rescue.
    """
    return any(arg.rstrip("/") == "benchmarks" for arg in args)


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Replace a silent zero-item ``benchmarks/`` run with a clear error.

    ``benchmarks/`` is deliberately outside ``testpaths`` and its files
    are named ``bench_*.py``, not ``test_*.py`` (see CONTRIBUTING.md's
    "Benchmarks" section). Pointing plain ``pytest`` at it directly
    (``uv run pytest benchmarks/``) collects nothing and exits 0 --
    pytest's default ``python_files`` glob never matches ``bench_*.py``
    -- which reads as "ran fine, nothing to benchmark" rather than a
    bad invocation.
    """
    if items:
        return
    if not _requested_benchmarks_directly(config.args):
        return
    msg = (
        "benchmarks/ collected 0 items: pytest's default python_files "
        "('test_*.py') does not match this directory's 'bench_*.py' "
        "files. Run `just bench`, or "
        "`uv run pytest benchmarks/ -o python_files='bench_*.py' "
        "--benchmark-only` directly."
    )
    raise pytest.UsageError(msg)


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
        doctest_namespace["Client"] = Client
        doctest_namespace["server"] = request.getfixturevalue("server")
        doctest_namespace["Server"] = request.getfixturevalue("TestServer")
        session: Session = request.getfixturevalue("session")
        doctest_namespace["session"] = session
        doctest_namespace["window"] = session.active_window
        doctest_namespace["pane"] = session.active_pane
        doctest_namespace["request"] = request
        doctest_namespace["ControlMode"] = ControlMode
        doctest_namespace["retry_until"] = retry_until
        doctest_namespace["control_mode"] = functools.partial(
            ControlMode,
            server=session.server,
            session=session,
        )
        doctest_namespace["monkeypatch"] = request.getfixturevalue("monkeypatch")


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
