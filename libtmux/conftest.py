import logging
import os
import typing as t

import pytest

from _pytest.fixtures import SubRequest
from _pytest.monkeypatch import MonkeyPatch

from libtmux import exc
from libtmux.common import which
from libtmux.server import Server
from libtmux.test import TEST_SESSION_PREFIX, get_test_session_name, namer

if t.TYPE_CHECKING:
    from libtmux.session import Session

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: MonkeyPatch) -> None:
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
def server(request: SubRequest, monkeypatch: MonkeyPatch) -> Server:

    t = Server()
    t.socket_name = "tmuxp_test%s" % next(namer)

    def fin() -> None:
        t.kill_server()

    request.addfinalizer(fin)

    return t


@pytest.fixture(scope="function")
def session(request: SubRequest, server: Server) -> "Session":
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


@pytest.fixture(autouse=True)
def add_doctest_fixtures(
    doctest_namespace: t.Dict[str, t.Any],
    # usefixtures / autouse
    clear_env: t.Any,
    # Normal fixtures
    server: "Server",
    session: "Session",
) -> None:
    if which("tmux"):
        doctest_namespace["server"] = server
        doctest_namespace["session"] = session
        doctest_namespace["window"] = session.attached_window
        doctest_namespace["pane"] = session.attached_pane
