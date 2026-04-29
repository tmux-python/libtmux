"""libtmux pytest plugin."""

from __future__ import annotations

import contextlib
import functools
import getpass
import logging
import os
import pathlib
import typing as t

import pytest

from libtmux import exc
from libtmux.server import Server
from libtmux.test.constants import TEST_SESSION_PREFIX
from libtmux.test.random import get_test_session_name, namer

if t.TYPE_CHECKING:
    from libtmux.session import Session

logger = logging.getLogger(__name__)
_PYTEST_ENGINES = ("subprocess", "imsg", "control_mode")
_PytestEngine = t.Literal["subprocess", "imsg", "control_mode"]


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add libtmux-specific pytest command line options."""
    group = parser.getgroup("libtmux")
    group.addoption(
        "--engine",
        action="store",
        choices=_PYTEST_ENGINES,
        default="subprocess",
        help="Select the libtmux engine for plugin-managed fixtures.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register libtmux-specific markers so ``--strict-markers`` accepts them."""
    config.addinivalue_line(
        "markers",
        "skip_engine(*engines, reason=''): skip the test when running under "
        "any of the named libtmux engines. Pair with --engine=<name> at the "
        "CLI. Example: ``@pytest.mark.skip_engine('control_mode', "
        "reason='auto-attach interferes with empty-server semantics')``.",
    )
    config.addinivalue_line(
        "markers",
        "engine_only(*engines, reason=''): skip the test unless running "
        "under one of the named libtmux engines. Inverse of skip_engine — "
        "use for tests that exercise engine-specific behaviour.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip doctests that assume lazy-spawn semantics when ``--engine=control_mode``.

    pytest markers cannot decorate doctest items the way they decorate
    regular test functions, so doctests rely on this collection hook
    for engine-aware skipping. The condition is simple: under
    ``control_mode``, every doctest that uses the live ``server``
    fixture observes the auto-attached default session and breaks the
    "fresh server" expectation the doctests were written for. Rather
    than rewrite the doctests to be engine-agnostic (which would
    obscure the ergonomics for the 99 % of users who run under the
    default engine), we skip them en masse.
    """
    engine = _fixture_engine_from_config(config)
    if engine != "control_mode":
        return

    from _pytest.doctest import DoctestItem

    skip = pytest.mark.skip(
        reason=(
            "doctest assumes lazy-spawn / zero-session semantics; "
            "control_mode auto-attaches to a default session on connect"
        ),
    )
    for item in items:
        if isinstance(item, DoctestItem):
            item.add_marker(skip)


def _fixture_engine_from_config(
    config: pytest.Config,
) -> _PytestEngine:
    """Return the selected engine for pytest-managed libtmux fixtures."""
    return t.cast("_PytestEngine", config.getoption("engine"))


@pytest.fixture(scope="session")
def libtmux_engine(pytestconfig: pytest.Config) -> _PytestEngine:
    """Return the engine selected for libtmux-managed pytest fixtures."""
    return _fixture_engine_from_config(pytestconfig)


@pytest.fixture(autouse=True)
def _enforce_engine_marks(
    request: pytest.FixtureRequest,
    libtmux_engine: _PytestEngine,
) -> None:
    """Enforce ``@pytest.mark.skip_engine`` and ``@pytest.mark.engine_only``.

    Implemented as an autouse fixture (not a ``pytest_collection_modifyitems``
    hook) because the matplotlib pattern proves cheaper: only the test
    that's about to run pays the marker lookup, and ``pytest.skip()``
    handles reporting + summary lines for free.

    Two marks are recognised:

    * ``skip_engine(*engines, reason="…")`` — skip when the active
      engine is in the list. Use for tests that fundamentally
      conflict with one engine's semantics (e.g. control_mode's
      auto-attach behaviour breaks "fresh-server" assumptions).
    * ``engine_only(*engines, reason="…")`` — skip when the active
      engine is *not* in the list. Use for tests that exercise
      engine-specific public surface (e.g. ``Server.subscribe`` only
      works on control_mode).

    A test may carry both — both predicates apply.
    """
    skip_mark = request.node.get_closest_marker("skip_engine")
    if skip_mark is not None and libtmux_engine in skip_mark.args:
        reason = skip_mark.kwargs.get(
            "reason",
            f"skipped on the {libtmux_engine!r} engine via skip_engine marker",
        )
        pytest.skip(reason)

    only_mark = request.node.get_closest_marker("engine_only")
    if only_mark is not None and libtmux_engine not in only_mark.args:
        reason = only_mark.kwargs.get(
            "reason",
            (
                f"engine_only({', '.join(repr(e) for e in only_mark.args)}) — "
                f"current engine is {libtmux_engine!r}"
            ),
        )
        pytest.skip(reason)


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

    # ``Server(socket_name=...)`` does not populate ``socket_path`` —
    # the Server class only derives the path when neither ``socket_name``
    # nor ``socket_path`` was supplied. Recompute the location tmux uses
    # so we can unlink the file regardless of daemon state.
    tmux_tmpdir = pathlib.Path(os.environ.get("TMUX_TMPDIR", "/tmp"))
    socket_path = tmux_tmpdir / f"tmux-{os.geteuid()}" / socket_name
    with contextlib.suppress(OSError):
        socket_path.unlink(missing_ok=True)


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
def config_file(user_path: pathlib.Path) -> pathlib.Path:
    """Return fixture for ``.tmux.conf`` configuration.

    Pinned settings:

    - ``base-index 1`` — guarantees pane and window targets can be
      reliably referenced and asserted starting at 1.
    - ``default-shell /bin/sh`` — bypasses the developer's interactive
      shell (zsh/bash) so each test pane skips ~60ms of shell init
      and the non-deterministic prompt rendering that otherwise causes
      flakes against ``automatic-rename`` and ``capture-pane`` assertions.
      ``default-command`` is intentionally left at tmux's default
      (empty string) so that consumer test workspaces — for example
      tmuxp's ``window_options_after.yaml`` which pins
      ``default-shell: /bin/bash`` to test Up-arrow shell history —
      can override ``default-shell`` per-session and have it take
      effect. Setting ``default-command`` here would short-circuit
      that override path (per tmux's ``cmd-new-window.c``,
      ``default-command`` always wins over ``default-shell``).

    Note: You will need to set the home directory, see :ref:`set_home`.
    """
    c = user_path / ".tmux.conf"
    c.write_text(
        """
set -g base-index 1
set -g default-shell /bin/sh
    """,
        encoding="utf-8",
    )
    return c


@pytest.fixture(autouse=True)
def _pin_test_shell_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``$SHELL`` to ``/bin/sh`` for every test that loads this plugin.

    The companion ``config_file`` fixture pins tmux's ``default-shell`` to
    ``/bin/sh``; this autouse hook keeps Python-side ``os.getenv("SHELL")``
    consumers aligned. Without it, libtmux's conftest already covers its
    own tests via ``clear_env``, but external consumers (notably tmuxp's
    ``test_automatic_rename_option`` which asserts
    ``w.name in {Path(os.getenv("SHELL")).name, ...}``) see the
    developer's interactive shell on the env side and ``/bin/sh`` on the
    tmux side and flake on the mismatch. Running autouse from the plugin
    ensures every consumer's tests get the alignment for free.
    """
    monkeypatch.setenv("SHELL", "/bin/sh")


@pytest.fixture
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear out any unnecessary environment variables that could interrupt tests.

    tmux show-environment tests were being interrupted due to a lot of crazy env vars.

    Note: ``SHELL`` alignment with tmux's ``default-shell`` is handled by
    the ``_pin_test_shell_env`` autouse fixture in this same module, so
    callers do not need to opt into ``clear_env`` solely to get that
    behavior.
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
    libtmux_engine: _PytestEngine,
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
    socket_name = f"libtmux_test{next(namer)}"
    if libtmux_engine == "imsg":
        server = Server(socket_name=socket_name, engine="imsg")
    elif libtmux_engine == "control_mode":
        server = Server(socket_name=socket_name, engine="control_mode")
    else:
        server = Server(socket_name=socket_name, engine="subprocess")

    def fin() -> None:
        # Ensure the persistent control-mode subprocess is shut down
        # before the socket reap kicks tmux in the head — otherwise the
        # finalizer's SIGKILL races our weakref.finalize and CPython
        # warns about an unclosed file in the engine's pipes.
        if libtmux_engine == "control_mode":
            from libtmux.engines.control_mode import ControlModeEngine

            if isinstance(server.engine, ControlModeEngine):
                server.engine.close()
        _reap_test_server(server.socket_name)

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
def TestServer(
    request: pytest.FixtureRequest,
    libtmux_engine: _PytestEngine,
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

    def socket_name_factory() -> str:
        """Generate unique socket names."""
        return f"libtmux_test{next(namer)}"

    def fin() -> None:
        """Kill all servers created with these sockets and unlink their sockets."""
        for socket_name in created_sockets:
            _reap_test_server(socket_name)

    request.addfinalizer(fin)

    if libtmux_engine == "imsg":
        factory = functools.partial(
            Server,
            on_init=on_init,
            socket_name_factory=socket_name_factory,
            engine="imsg",
        )
    elif libtmux_engine == "control_mode":
        factory = functools.partial(
            Server,
            on_init=on_init,
            socket_name_factory=socket_name_factory,
            engine="control_mode",
        )
    else:
        factory = functools.partial(
            Server,
            on_init=on_init,
            socket_name_factory=socket_name_factory,
            engine="subprocess",
        )

    return t.cast("type[Server]", factory)
