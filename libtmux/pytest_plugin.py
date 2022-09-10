import getpass
import logging
import os
import pathlib
import typing as t

import pytest

from libtmux import exc
from libtmux.server import Server
from libtmux.test import TEST_SESSION_PREFIX, get_test_session_name, namer

if t.TYPE_CHECKING:
    from libtmux.session import Session

logger = logging.getLogger(__name__)
USING_ZSH = "zsh" in os.getenv("SHELL", "")


@pytest.fixture(scope="session")
def home_path(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Temporary `/home/` path."""
    return tmp_path_factory.mktemp("home")


@pytest.fixture(scope="session")
def home_user_name() -> str:
    """Default username to set for :func:`user_path` fixture."""
    return getpass.getuser()


@pytest.fixture(scope="session")
def user_path(home_path: pathlib.Path, home_user_name: str) -> pathlib.Path:
    """Default temporary user directory.

    Used by: :func:`config_file`, :func:`zshrc`

    Note: You will need to set the home directory, see :ref:`set_home`.
    """
    p = home_path / home_user_name
    p.mkdir()
    return p


@pytest.mark.skipif(USING_ZSH, reason="Using ZSH")
@pytest.fixture(scope="session")
def zshrc(user_path: pathlib.Path) -> pathlib.Path:
    """This quiets ZSH default message.

    Needs a startup file .zshenv, .zprofile, .zshrc, .zlogin.
    """
    p = user_path / ".zshrc"
    p.touch()
    return p


@pytest.fixture(scope="session")
def config_file(user_path: pathlib.Path) -> pathlib.Path:
    """Default `.tmux.conf` configuration.

    - ``base-index -g 1``

    These guarantee pane and windows targets can be reliably referenced and asserted.

    Note: You will need to set the home directory, see :ref:`set_home`.
    """
    c = user_path / ".tmux.conf"
    c.write_text(
        """
set -g base-index 1
    """,
        encoding="utf-8",
    )
    return c


@pytest.fixture
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear out any unnecessary environment variables that could interrupt tests.

    tmux show-environment tests were being interrupted due to a lot of crazy env vars.
    """
    for k, v in os.environ.items():
        if not any(
            needle in k.lower()
            for needle in [
                "window",
                "tmux",
                "pane",
                "session",
                "pytest",
                "path",
                "pwd",
                "shell",
                "home",
                "xdg",
                "disable_auto_title",
                "lang",
                "term",
            ]
        ):
            monkeypatch.delenv(k)


@pytest.fixture(scope="function")
def server(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    config_file: pathlib.Path,
) -> Server:
    """Returns a new, temporary :class:`libtmux.server.Server`"""
    t = Server()
    t.socket_name = "libtmux_test%s" % next(namer)

    def fin() -> None:
        t.kill_server()

    request.addfinalizer(fin)

    return t


@pytest.fixture(scope="function")
def session(request: pytest.FixtureRequest, server: Server) -> "Session":
    """Returns a new, temporary :class:`libtmux.Session`"""
    session_name = "tmuxp"

    if not server.has_session(session_name):
        server.cmd("new-session", "-d", "-s", session_name)

    # find current sessions prefixed with tmuxp
    old_test_sessions = []
    for s in server._sessions:
        old_name = s.get("session_name")
        if old_name is not None and old_name.startswith(TEST_SESSION_PREFIX):
            old_test_sessions.append(old_name)

    TEST_SESSION_NAME = get_test_session_name(server=server)

    try:
        session = server.new_session(session_name=TEST_SESSION_NAME)
    except exc.LibTmuxException as e:
        raise e

    """
    Make sure that tmuxp can :ref:`test_builder_visually` and switches to
    the newly created session for that testcase.
    """
    session_id = session.get("session_id")
    assert session_id is not None

    try:
        server.switch_client(target_session=session_id)
    except exc.LibTmuxException:
        # server.attach_session(session.get('session_id'))
        pass

    for old_test_session in old_test_sessions:
        logger.debug("Old test test session %s found. Killing it." % old_test_session)
        server.kill_session(old_test_session)
    assert TEST_SESSION_NAME == session.get("session_name")
    assert TEST_SESSION_NAME != "tmuxp"

    return session
