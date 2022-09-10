import pathlib
import shutil
import typing as t

import pytest

from _pytest.doctest import DoctestItem

from libtmux.pytest_plugin import USING_ZSH

if t.TYPE_CHECKING:
    from libtmux.session import Session


@pytest.fixture(autouse=True)
def add_doctest_fixtures(
    request: pytest.FixtureRequest,
    doctest_namespace: t.Dict[str, t.Any],
) -> None:
    if isinstance(request._pyfuncitem, DoctestItem) and shutil.which("tmux"):
        request.getfixturevalue("set_home")
        doctest_namespace["server"] = request.getfixturevalue("server")
        session: "Session" = request.getfixturevalue("session")
        doctest_namespace["session"] = session
        doctest_namespace["window"] = session.attached_window
        doctest_namespace["pane"] = session.attached_pane


@pytest.fixture(autouse=True, scope="function")
def set_home(
    monkeypatch: pytest.MonkeyPatch,
    user_path: pathlib.Path,
) -> None:
    monkeypatch.setenv("HOME", str(user_path))


@pytest.fixture(autouse=True, scope="session")
@pytest.mark.usefixtures("clear_env")
def setup(
    request: pytest.FixtureRequest,
    config_file: pathlib.Path,
) -> None:
    if USING_ZSH:
        request.getfixturevalue("zshrc")
