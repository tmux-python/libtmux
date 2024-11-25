"""libtmux pytest plugin."""

import contextlib
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
    """Return default username to set for :func:`user_path` fixture."""
    return getpass.getuser()


@pytest.fixture(scope="session")
def user_path(home_path: pathlib.Path, home_user_name: str) -> pathlib.Path:
    """Ensure and return temporary user directory.

    Used by: :func:`config_file`, :func:`zshrc`

    Note: You will need to set the home directory, see :ref:`set_home`.
    """
    p = home_path / home_user_name
    p.mkdir()
    return p


@pytest.mark.skipif(USING_ZSH, reason="Using ZSH")
@pytest.fixture(scope="session")
def zshrc(user_path: pathlib.Path) -> pathlib.Path:
    """Suppress ZSH default message.

    Needs a startup file .zshenv, .zprofile, .zshrc, .zlogin.
    """
    p = user_path / ".zshrc"
    p.touch()
    return p


@pytest.fixture(scope="session")
def config_file(user_path: pathlib.Path) -> pathlib.Path:
    """Return fixture for ``.tmux.conf`` configuration.

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
    for k in os.environ:
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


@pytest.fixture
def server(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    config_file: pathlib.Path,
) -> Server:
    """Return new, temporary :class:`libtmux.Server`.

    >>> from libtmux.server import Server

    >>> def test_example(server: Server) -> None:
    ...     assert isinstance(server, Server)
    ...     session = server.new_session('my session')
    ...     assert len(server.sessions) == 1
    ...     assert [session.name.startswith('my') for session in server.sessions]

    .. ::
        >>> locals().keys()
        dict_keys(...)

        >>> source = ''.join([e.source for e in request._pyfuncitem.dtest.examples][:3])
        >>> pytester = request.getfixturevalue('pytester')

        >>> pytester.makepyfile(**{'whatever.py': source})
        PosixPath(...)

        >>> result = pytester.runpytest('whatever.py', '--disable-warnings')
        ===...

        >>> result.assert_outcomes(passed=1)
    """
    server = Server(socket_name=f"libtmux_test{next(namer)}")

    def fin() -> None:
        server.kill()

    request.addfinalizer(fin)

    return server


@pytest.fixture
def session_params() -> t.Dict[str, t.Any]:
    """Return new, temporary :class:`libtmux.Session`.

    >>> import pytest
    >>> from libtmux.session import Session

    >>> @pytest.fixture
    ... def session_params(session_params):
    ...     return {
    ...         'x': 800,
    ...         'y': 600,
    ...     }

    >>> def test_example(session: "Session") -> None:
    ...     assert isinstance(session.name, str)
    ...     assert session.name.startswith('libtmux_')
    ...     window = session.new_window(window_name='new one')
    ...     assert window.name == 'new one'

    .. ::
        >>> locals().keys()
        dict_keys(...)

        >>> source = ''.join([e.source for e in request._pyfuncitem.dtest.examples][:4])
        >>> pytester = request.getfixturevalue('pytester')

        >>> pytester.makepyfile(**{'whatever.py': source})
        PosixPath(...)

        >>> result = pytester.runpytest('whatever.py', '--disable-warnings')
        ===...

        >>> result.assert_outcomes(passed=1)
    """
    return {}


@pytest.fixture
def session(
    request: pytest.FixtureRequest,
    session_params: t.Dict[str, t.Any],
    server: Server,
) -> "Session":
    """Return new, temporary :class:`libtmux.Session`.

    >>> from libtmux.session import Session

    >>> def test_example(session: "Session") -> None:
    ...     assert isinstance(session.name, str)
    ...     assert session.name.startswith('libtmux_')
    ...     window = session.new_window(window_name='new one')
    ...     assert window.name == 'new one'

    .. ::
        >>> locals().keys()
        dict_keys(...)

        >>> source = ''.join([e.source for e in request._pyfuncitem.dtest.examples][:3])
        >>> pytester = request.getfixturevalue('pytester')

        >>> pytester.makepyfile(**{'whatever.py': source})
        PosixPath(...)

        >>> result = pytester.runpytest('whatever.py', '--disable-warnings')
        ===...

        >>> result.assert_outcomes(passed=1)
    """
    session_name = "tmuxp"

    if not server.has_session(session_name):
        server.new_session(
            session_name=session_name,
        )

    # find current sessions prefixed with tmuxp
    old_test_sessions = []
    for s in server.sessions:
        old_name = s.session_name
        if old_name is not None and old_name.startswith(TEST_SESSION_PREFIX):
            old_test_sessions.append(old_name)

    TEST_SESSION_NAME = get_test_session_name(server=server)

    session = server.new_session(
        session_name=TEST_SESSION_NAME,
        **session_params,
    )

    """
    Make sure that tmuxp can :ref:`test_builder_visually` and switches to
    the newly created session for that testcase.
    """
    session_id = session.session_id
    assert session_id is not None

    with contextlib.suppress(exc.LibTmuxException):
        server.switch_client(target_session=session_id)

    for old_test_session in old_test_sessions:
        logger.debug(f"Old test test session {old_test_session} found. Killing it.")
        server.kill_session(old_test_session)
    assert session.session_name == TEST_SESSION_NAME
    assert TEST_SESSION_NAME != "tmuxp"

    return session
