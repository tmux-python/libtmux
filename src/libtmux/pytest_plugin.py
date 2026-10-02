"""libtmux pytest plugin."""

from __future__ import annotations

import contextlib
import functools
import getpass
import logging
import os
import pathlib
import shlex
import typing as t

import pytest

from libtmux import exc
from libtmux._internal.control_mode import ControlMode
from libtmux._internal.env import resolve_socket_path
from libtmux.server import Server
from libtmux.test.constants import TEST_SESSION_PREFIX
from libtmux.test.random import get_test_session_name, namer

if t.TYPE_CHECKING:
    from libtmux.session import Session

logger = logging.getLogger(__name__)
USING_ZSH = "zsh" in os.getenv("SHELL", "")

_SERVERS_KEY = pytest.StashKey["list[Server]"]()
_FAILED_KEY = pytest.StashKey[bool]()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--libtmux-keep-failed`` option."""
    group = parser.getgroup("libtmux")
    group.addoption(
        "--libtmux-keep-failed",
        action="store_true",
        default=False,
        help=(
            "Leave the tmux server of a failed test running, so the attach "
            "command in the failure report keeps working. Kill it with the "
            "kill-server command the report prints."
        ),
    )


def _track_server(item: pytest.Item, server: Server) -> None:
    """Remember ``server`` so a failure report can name how to attach to it."""
    item.stash.setdefault(_SERVERS_KEY, []).append(server)


def _attach_report(item: pytest.Item, *, keep: bool) -> str | None:
    """Return the attach commands for the live servers of ``item``.

    Returns ``None`` when no tracked server is still running, since there is
    nothing to attach to.
    """
    blocks: list[str] = []
    session = getattr(item, "funcargs", {}).get("session")
    for srv in item.stash.get(_SERVERS_KEY, []):
        if not srv.is_alive():
            continue
        socket_path = srv.cmd("display-message", "-p", "#{socket_path}").stdout
        path = socket_path[0] if socket_path else None
        if not path and srv.socket_name:
            path = str(resolve_socket_path(srv.socket_name))
        if not path:
            continue
        tmux = srv.tmux_bin or "tmux"
        attach = [tmux, "-S", path, "attach"]
        if session is not None and session.server is srv:
            win = session.active_window
            attach += ["-t", session.session_name or ""]
            attach += [";", "resize-window"]
            attach += ["-x", str(win.window_width), "-y", str(win.window_height)]
        lines = ["Attach to the tmux server this test used:", f"  {shlex.join(attach)}"]
        if keep:
            kill = shlex.join([tmux, "-S", path, "kill-server"])
            lines.append("The server stays running (--libtmux-keep-failed). Stop it:")
            lines.append(f"  {kill}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[None],
) -> t.Generator[None, t.Any, None]:
    """Add the attach command of the test's tmux servers to a failure report."""
    outcome = yield
    report = outcome.get_result()
    if report.when not in {"setup", "call"} or not report.failed:
        return
    item.stash[_FAILED_KEY] = True
    keep = bool(item.config.getoption("libtmux_keep_failed"))
    text = _attach_report(item, keep=keep)
    if text:
        report.sections.append(("libtmux", text))


def _teardown_server(item: pytest.Item, socket_name: str | None) -> None:
    """Reap ``socket_name``, unless ``--libtmux-keep-failed`` keeps it."""
    keep = item.config.getoption("libtmux_keep_failed")
    if keep and item.stash.get(_FAILED_KEY, False):
        return
    _reap_test_server(socket_name)


def _reap_test_server(socket_name: str | None) -> None:
    """Kill the tmux daemon on ``socket_name`` and unlink the socket file.

    Invoked from the :func:`server` and :func:`TestServer` fixture
    finalizers to guarantee teardown even when the daemon has already
    exited (``kill`` is a no-op then) and the socket file was left on
    disk. tmux does not reliably ``unlink(2)`` its socket on
    non-graceful exit, so ``/tmp/tmux-<uid>/`` otherwise accumulates
    stale entries across test runs.

    Conservative: suppresses ``LibTmuxException`` / ``OSError`` on both
    the kill and the unlink. A finalizer that raises replaces the real
    test failure with a cleanup error, and cleanup failures are not
    actionable (socket already gone, permissions changed, race with a
    concurrent pytest-xdist worker).
    """
    if not socket_name:
        return

    with contextlib.suppress(exc.LibTmuxException, OSError):
        srv = Server(socket_name=socket_name)
        if srv.is_alive():
            srv.kill()

    # ``Server(socket_name=...)`` does not populate ``socket_path``, so
    # resolve where tmux put the socket to unlink it regardless of daemon
    # state.
    with contextlib.suppress(OSError):
        resolve_socket_path(socket_name).unlink(missing_ok=True)


@pytest.fixture(scope="session")
def home_path(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Temporary `/home/` path."""
    return tmp_path_factory.mktemp("home")


@pytest.fixture(scope="session")
def home_user_name() -> str:
    """Return default username to set for :fixture:`user_path` fixture."""
    return getpass.getuser()


@pytest.fixture(scope="session")
def user_path(home_path: pathlib.Path, home_user_name: str) -> pathlib.Path:
    """Ensure and return temporary user directory.

    Note: You will need to set the home directory, see :ref:`set_home`.
    """
    p = home_path / home_user_name
    p.mkdir()
    return p


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

    ``TMUX`` and ``TMUX_PANE`` are always removed: a tmux client given neither
    ``-L`` nor ``-S`` follows ``$TMUX`` to the server the test run was started
    from, so a bare :class:`~libtmux.Server` would act on that outer session.
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
    # The needle list keeps "tmux" and "pane" for TMUX_TMPDIR and the like;
    # these two name the outer session and must go.
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)


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
    _track_server(request.node, server)

    def fin() -> None:
        _teardown_server(request.node, server.socket_name)

    request.addfinalizer(fin)

    return server


@pytest.fixture
def session_params() -> dict[str, t.Any]:
    """Return default session creation parameters.

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
    session_params: dict[str, t.Any],
    server: Server,
) -> Session:
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
        server.kill_session(old_test_session)
        logger.debug(
            "old test session killed",
            extra={
                "tmux_session": old_test_session,
                "tmux_subcommand": "kill-session",
            },
        )
    assert session.session_name == TEST_SESSION_NAME
    assert TEST_SESSION_NAME != "tmuxp"

    return session


@pytest.fixture
def control_mode(
    server: Server,
    session: Session,
) -> t.Callable[[], ControlMode]:
    """Return :class:`ControlMode` context manager factory.

    Returns a callable that creates :class:`ControlMode` context managers
    bound to the test's server and session. Use as a context manager to
    spawn a control-mode tmux client.

    While the control-mode client is active, ``Server.list_clients()``
    will include it.

    Examples
    --------
    >>> from libtmux._internal.control_mode import ControlMode
    >>> def test_example(control_mode):
    ...     with control_mode() as ctl:
    ...         assert ctl.client_name != ''
    """
    return functools.partial(ControlMode, server=server, session=session)


@pytest.fixture
def TestServer(
    request: pytest.FixtureRequest,
) -> type[Server]:
    """Create a temporary tmux server that cleans up after itself.

    This is similar to the server pytest fixture, but can be used outside of pytest.
    The server will be killed when the test completes.

    Examples
    --------
    >>> server = Server()  # Create server instance
    >>> server.new_session()
    Session($... ...)
    >>> server.is_alive()
    True
    >>> # Each call creates a new server with unique socket
    >>> server2 = Server()
    >>> server2.socket_name != server.socket_name
    True
    """
    created_sockets: list[str] = []

    def on_init(server: Server) -> None:
        """Track created servers for cleanup."""
        created_sockets.append(server.socket_name or "default")
        _track_server(request.node, server)

    def socket_name_factory() -> str:
        """Generate unique socket names."""
        return f"libtmux_test{next(namer)}"

    def fin() -> None:
        """Kill all servers created with these sockets and unlink their sockets."""
        for socket_name in created_sockets:
            _teardown_server(request.node, socket_name)

    request.addfinalizer(fin)

    return t.cast(
        "type[Server]",
        functools.partial(
            Server,
            on_init=on_init,
            socket_name_factory=socket_name_factory,
        ),
    )
