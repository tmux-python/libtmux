"""Test for libtmux Server object."""

from __future__ import annotations

import functools
import logging
import os
import pathlib
import shutil
import socket
import subprocess
import time
import typing as t

import pytest

from libtmux import exc
from libtmux._internal.control_mode import ControlMode
from libtmux._internal.env import SOCKET_PATH_MAX_BYTES, resolve_socket_path
from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux._internal.types import StrPath
    from libtmux.session import Session

logger = logging.getLogger(__name__)


def test_has_session(server: Server, session: Session) -> None:
    """Server.has_session() returns True if session exists."""
    session_name = session.session_name
    assert session_name is not None
    assert server.has_session(session_name)
    assert not server.has_session("asdf2314324321")


def test_socket_name(server: Server) -> None:
    """``-L`` socket_name.

    ``-L`` socket_name  file name of socket. which will be stored in
            env TMUX_TMPDIR or /tmp if unset.)

    """
    myserver = Server(socket_name="test")

    assert myserver.socket_name == "test"


def test_socket_path(server: Server) -> None:
    """``-S`` socket_path  (alternative path for server socket)."""
    myserver = Server(socket_path="test")

    assert myserver.socket_path == "test"


def test_socket_path_not_derived_from_socket_name() -> None:
    """A named socket leaves ``socket_path`` unset.

    tmux resolves a ``-L`` name against its own socket directory, so libtmux
    has no reason to guess the path. Anything that needs the real path asks
    tmux for it (``#{socket_path}``).
    """
    myserver = Server(socket_name="libtmux_test_named_socket")

    assert myserver.socket_name == "libtmux_test_named_socket"
    assert myserver.socket_path is None


def test_repr_socket_path_honors_tmux_tmpdir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """A default ``Server()`` reprs the socket tmux resolves, not ``/tmp``.

    Regression for #723: the repr hard-coded ``/tmp/tmux-<euid>/default``, so
    under any ``$TMUX_TMPDIR`` it named a socket the object was not using.
    """
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path))

    myserver = Server()

    socket_path = tmp_path / f"tmux-{os.geteuid()}" / "default"
    assert repr(myserver) == f"Server(socket_path={socket_path})"


def test_repr_socket_path_resolves_a_symlinked_tmpdir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """A symlinked ``$TMUX_TMPDIR`` reprs the path tmux reports, not the link.

    tmux resolves the socket directory before binding, so the link's own
    length is not what a socket has to fit in. Reporting the unresolved path
    would name a socket tmux never creates.
    """
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("TMUX_TMPDIR", str(link))

    myserver = Server()

    socket_path = target.resolve() / f"tmux-{os.geteuid()}" / "default"
    assert repr(myserver) == f"Server(socket_path={socket_path})"


def test_repr_socket_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """A named socket reprs its name, whatever ``$TMUX_TMPDIR`` says."""
    monkeypatch.setenv("TMUX_TMPDIR", "/nonexistent-tmux-tmpdir")

    myserver = Server(socket_name="libtmux_test_repr")

    assert repr(myserver) == "Server(socket_name=libtmux_test_repr)"


def _af_unix_path_fits(length: int) -> bool:
    """Return True if a *length*-byte path fits in a UNIX socket address.

    CPython measures ``sun_path`` itself and refuses an oversized path before
    any syscall, so this asks the live platform for its limit without creating a
    socket file. A path that fits fails for an ordinary reason instead --
    nothing is listening at it.
    """
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.connect("/" + "x" * (length - 1))
    except OSError as e:
        return "too long" not in str(e)
    finally:
        sock.close()
    return True


def test_socket_path_max_bytes_matches_platform() -> None:
    """The compiled-in limit is the one this platform actually enforces.

    ``sun_path``'s size is not exposed by the stdlib, so libtmux spells it out
    per platform. This keeps that number honest by probing.
    """
    assert _af_unix_path_fits(SOCKET_PATH_MAX_BYTES)
    assert not _af_unix_path_fits(SOCKET_PATH_MAX_BYTES + 1)


def test_socket_path_too_long_raises_at_construction() -> None:
    """An explicit ``socket_path`` is measurable the moment it is passed.

    Regression for #725: without the measurement the overrun surfaced as a
    passed-through ``File name too long`` without the byte count.

    This is the one socket libtmux hands to tmux unchanged, as ``-S<path>``,
    so its length cannot be revised by anything that happens later. A name or
    a bare server resolves against an environment tmux re-reads at exec, which
    is why those are measured at dispatch instead.
    """
    socket_path = f"/tmp/{'d' * 200}/sock"

    with pytest.raises(exc.SocketPathTooLong) as excinfo:
        Server(socket_path=socket_path)

    assert excinfo.value.length == len(socket_path)
    assert excinfo.value.limit == SOCKET_PATH_MAX_BYTES
    assert excinfo.value.over == len(socket_path) - SOCKET_PATH_MAX_BYTES
    assert excinfo.value.socket_name is None
    assert excinfo.value.env_var is None


def test_socket_path_at_limit_is_accepted() -> None:
    """A path that exactly fills the limit is usable, so it is dispatched."""
    socket_path = "/tmp/" + "d" * (SOCKET_PATH_MAX_BYTES - len("/tmp/"))
    assert len(socket_path) == SOCKET_PATH_MAX_BYTES

    myserver = Server(socket_path=socket_path)

    assert myserver.socket_path == socket_path
    assert myserver._socket_args() == [f"-S{socket_path}"]


def test_socket_name_too_long_via_tmux_tmpdir(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short name resolving under a long ``$TMUX_TMPDIR`` overruns too.

    Regression for #725. This is the case that bites: the length is inherited
    from the environment, so the caller never saw the path that failed -- hence
    the resolved path and the name are both reported.
    """
    _unbindable_tmux_tmpdir(tmp_path, monkeypatch)
    myserver = Server(socket_name="dev")

    with pytest.raises(exc.SocketPathTooLong) as excinfo:
        myserver.cmd("list-sessions")

    assert excinfo.value.socket_name == "dev"
    assert str(excinfo.value.socket_path).endswith(f"/tmux-{os.geteuid()}/dev")


def test_socket_name_factory_too_long_via_tmux_tmpdir(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A factory-generated name resolves under ``$TMUX_TMPDIR`` like any other.

    The factory runs in ``__init__``, so its name is on the object well before
    dispatch -- the measurement still happens at dispatch, against the name the
    factory produced.
    """
    _unbindable_tmux_tmpdir(tmp_path, monkeypatch)
    myserver = Server(socket_name_factory=lambda: "factory_made")

    assert myserver.socket_name == "factory_made"
    assert not myserver.is_alive()

    with pytest.raises(exc.SocketPathTooLong) as excinfo:
        myserver.cmd("list-sessions")

    assert excinfo.value.socket_name == "factory_made"


def test_socket_path_measured_at_dispatch_not_construction(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``$TMUX_TMPDIR`` is read when tmux would read it, not before.

    The tmux binary resolves its socket directory at exec time, so a server
    built under a short ``$TMUX_TMPDIR`` and used under a long one is measured
    against the long one -- and the reverse recovers without rebuilding the
    object.
    """
    myserver = Server(socket_name="dev")
    assert myserver._socket_args() == ["-Ldev"]

    _unbindable_tmux_tmpdir(tmp_path, monkeypatch)
    with pytest.raises(exc.SocketPathTooLong):
        myserver._socket_args()

    monkeypatch.delenv("TMUX_TMPDIR")
    assert myserver._socket_args() == ["-Ldev"]


def test_long_symlinked_tmpdir_is_measured_after_resolving(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """A long ``$TMUX_TMPDIR`` symlink to a short directory is accepted.

    tmux resolves the socket directory before binding, so the link's own
    length is not what has to fit. Measuring the unresolved path would refuse
    a server tmux runs happily.
    """
    target = tmp_path / "t"
    target.mkdir()
    link = tmp_path / ("s" * 120)
    link.symlink_to(target)
    monkeypatch.setenv("TMUX_TMPDIR", str(link))

    assert len(os.fsencode(str(link))) > SOCKET_PATH_MAX_BYTES

    myserver = Server(socket_name="dev")

    assert myserver._socket_args() == ["-Ldev"]


def _unbindable_tmux_tmpdir(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> pathlib.Path:
    """Point ``$TMUX_TMPDIR`` at a real directory too deep to hold a socket.

    The directory has to exist: tmux falls back to ``/tmp`` when it cannot
    create ``$TMUX_TMPDIR/tmux-<uid>``, and would then reach a real server
    instead of failing. ``$TMUX`` is cleared because a bare tmux client
    prefers it over ``$TMUX_TMPDIR``, so a suite run from inside a pane would
    otherwise be measuring a socket nothing here chose.
    """
    tmpdir = tmp_path / ("d" * 120)
    tmpdir.mkdir()
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("TMUX_TMPDIR", str(tmpdir))
    return tmpdir


def test_default_socket_too_long_via_tmux_tmpdir(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare ``Server()`` inherits its whole path, so it is measured as well.

    The constructor still succeeds and :meth:`Server.is_alive` still answers:
    a server at an address the kernel cannot hold is not alive.
    """
    _unbindable_tmux_tmpdir(tmp_path, monkeypatch)

    myserver = Server()

    assert not myserver.is_alive()

    with pytest.raises(exc.SocketPathTooLong) as excinfo:
        myserver.cmd("list-sessions")

    assert excinfo.value.socket_name is None
    assert str(excinfo.value.socket_path).endswith("/default")
    assert excinfo.value.env_var == "TMUX_TMPDIR"


def test_unusable_tmux_tmpdir_falls_back_to_tmp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``$TMUX_TMPDIR`` tmux cannot use is not the path that gets measured.

    tmux takes the first of ``$TMUX_TMPDIR`` and ``/tmp`` that resolves, so a
    directory that does not exist never holds the socket however long its name
    is. Measuring it anyway would refuse a server tmux reaches without
    difficulty: :meth:`Server.is_alive` would report a live daemon dead and the
    first command would raise.
    """
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("TMUX_TMPDIR", f"/nonexistent-{'d' * 200}")

    assert resolve_socket_path("dev") == pathlib.Path(
        f"/tmp/tmux-{os.geteuid()}/dev",
    )

    myserver = Server(socket_name="dev")

    assert myserver._socket_args() == ["-Ldev"]


def test_bare_server_inside_a_pane_ignores_tmux_tmpdir(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
) -> None:
    """A bare client inside a pane uses ``$TMUX``, so a deep dir is irrelevant.

    Measuring ``$TMUX_TMPDIR`` here would refuse a server tmux reaches without
    difficulty -- the common case for a script run inside tmux, which is where
    libtmux is most often used.

    The patched environment is scoped to the assertions rather than the test.
    The ``server`` fixture takes ``monkeypatch``, so pytest undoes the patches
    only after that fixture's finalizer has run -- and a finalizer that resolves
    the socket under an unreachable ``$TMUX_TMPDIR`` finds nothing to kill and
    unlinks a path that never existed, leaving the daemon running.
    """
    socket_path = session.server.cmd(
        "display-message",
        "-p",
        "#{socket_path}",
    ).stdout[0]
    deep = tmp_path / ("d" * 120)
    deep.mkdir()

    with monkeypatch.context() as m:
        m.setenv("TMUX_TMPDIR", str(deep))
        m.setenv("TMUX", f"{socket_path},{os.getpid()},0")

        myserver = Server()

        assert myserver._socket_args() == []
        assert myserver.is_alive()


def test_socket_args_covers_every_tmux_spawn(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
) -> None:
    """Every code path that spawns tmux builds its socket flags in one place.

    The measurement is only as total as the argv construction it rides on, so
    this pins the audit: each spawn site is exercised against a live server and
    asserted to have gone through :meth:`Server._socket_args`.
    """
    server = session.server
    calls: list[list[str]] = []
    real = Server._socket_args

    def spy(self: Server) -> list[str]:
        args = real(self)
        calls.append(args)
        return args

    monkeypatch.setattr(Server, "_socket_args", spy)

    server.cmd("list-sessions")
    assert calls, "Server.cmd did not build socket flags via _socket_args"

    calls.clear()
    server.raise_if_dead()
    assert calls, "Server.raise_if_dead did not build socket flags via _socket_args"

    calls.clear()
    assert server.sessions
    assert calls, "neo.fetch_objs did not build socket flags via _socket_args"

    calls.clear()
    with ControlMode(server=server, session=session) as ctl:
        assert ctl.client_name != ""
    assert calls, "ControlMode did not build socket flags via _socket_args"


def test_socket_path_too_long_raises_on_raise_if_dead(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``raise_if_dead`` is the loud primitive, so it reports the overrun.

    It builds its own argv and spawns tmux directly rather than going through
    :meth:`Server.cmd`, which is exactly how a dispatch-time check goes stale.
    An inherited path is the case that reaches it: an explicit ``socket_path``
    is refused at construction, so there is no object left to ask.
    """
    _unbindable_tmux_tmpdir(tmp_path, monkeypatch)
    myserver = Server()

    with pytest.raises(exc.SocketPathTooLong):
        myserver.raise_if_dead()


def test_config(server: Server) -> None:
    """``-f`` file for tmux(1) configuration."""
    myserver = Server(config_file="test")
    assert myserver.config_file == "test"


def test_256_colors(server: Server) -> None:
    """Assert Server respects ``colors=256``."""
    myserver = Server(colors=256)
    assert myserver.colors == 256

    proc = myserver.cmd("list-sessions")

    assert "-2" in proc.cmd
    assert "-8" not in proc.cmd


def test_88_colors(server: Server) -> None:
    """Assert Server respects ``colors=88``."""
    myserver = Server(colors=88)
    assert myserver.colors == 88

    proc = myserver.cmd("list-sessions")

    assert "-8" in proc.cmd
    assert "-2" not in proc.cmd


def test_show_environment(server: Server) -> None:
    """Server.show_environment() returns dict."""
    vars_ = server.show_environment()
    assert isinstance(vars_, dict)


def test_getenv(server: Server, session: Session) -> None:
    """Set environment then Server.show_environment(key)."""
    server.set_environment("FOO", "BAR")
    assert server.getenv("FOO") == "BAR"

    server.set_environment("FOO", "DAR")
    assert server.getenv("FOO") == "DAR"

    assert server.show_environment()["FOO"] == "DAR"


def test_show_environment_not_set(server: Server) -> None:
    """Unset environment variable returns None."""
    assert server.getenv("BAR") is None


def test_new_session(server: Server) -> None:
    """Server.new_session creates and returns valid session."""
    mysession = server.new_session("test_new_session")
    assert mysession.session_name == "test_new_session"
    assert server.has_session("test_new_session")


def test_new_session_returns_populated_session(server: Server) -> None:
    """Server.new_session returns Session populated from -P output."""
    session = server.new_session(session_name="test_populated")
    assert session.session_id is not None
    assert session.session_name == "test_populated"
    assert session.window_id is not None
    assert session.pane_id is not None


def test_sessions_property_hydrates_cross_scope(server: Server) -> None:
    """Server.sessions hydrates active window/pane via tmux's format_defaults cascade.

    Distinct from ``test_new_session_returns_populated_session``: that test
    exercises ``new-session -P -F`` (list-panes scope). This one exercises
    the ``list-sessions`` path used by the ``.sessions`` property, which
    must hydrate downward-cascade tokens (tmux ``format.c:format_defaults``
    walks ``s->curw`` and ``wl->window->active``).

    Pins the cascade *target*: ``session.window_id`` /
    ``session.pane_id`` must equal the session's current window's
    active pane — not any arbitrary pane in the session. A regression
    that hydrated to the wrong window or pane would still pass a
    "not None" check; this assertion catches that drift.
    """
    new_session = server.new_session(session_name="hydration_cascade_sessions")
    fetched = server.sessions.get(session_name="hydration_cascade_sessions")
    assert fetched is not None
    assert fetched.window_id == new_session.active_window.window_id
    active_pane = new_session.active_window.active_pane
    assert active_pane is not None
    assert fetched.pane_id == active_pane.pane_id
    assert fetched.pane_current_command is not None


def test_windows_property_hydrates_active_pane(
    server: Server,
    session: Session,
) -> None:
    """Server.windows hydrates each window's active pane via the cascade.

    Exercises the ``list-windows -a`` path used by the ``.windows``
    property. The cascade resolves to the window's active pane, so the
    hydrated ``pane_id`` must equal ``window.active_pane.pane_id``.
    """
    new_window = session.new_window(window_name="hydration_cascade_windows")
    fetched = server.windows.get(window_name="hydration_cascade_windows")
    assert fetched is not None
    active_pane = new_window.active_pane
    assert active_pane is not None
    assert fetched.pane_id == active_pane.pane_id
    assert fetched.pane_current_command is not None


def test_new_session_no_name(server: Server) -> None:
    """Server.new_session works with no name."""
    first_session = server.new_session()
    first_session_name = first_session.session_name
    assert first_session_name is not None
    assert server.has_session(first_session_name)

    expected_session_name = str(int(first_session_name) + 1)

    # When a new session is created, it should enumerate
    second_session = server.new_session()
    second_session_name = second_session.session_name
    assert expected_session_name == second_session_name
    assert second_session_name is not None
    assert server.has_session(second_session_name)


def test_new_session_shell(server: Server) -> None:
    """Verify ``Server.new_session`` creates valid session running w/ command."""
    cmd = "sleep 1m"
    mysession = server.new_session("test_new_session", window_command=cmd)
    window = mysession.windows[0]
    pane = window.panes[0]
    assert mysession.session_name == "test_new_session"
    assert server.has_session("test_new_session")

    pane_start_command = pane.pane_start_command
    assert pane_start_command is not None

    assert pane_start_command.replace('"', "") == cmd


def test_new_session_shell_env(server: Server) -> None:
    """Verify ``Server.new_session`` creates valid session running w/ command (#553)."""
    cmd = "sleep 1m"
    env = dict(os.environ)
    mysession = server.new_session(
        "test_new_session_env",
        window_command=cmd,
        environment=env,
    )
    time.sleep(0.1)
    window = mysession.windows[0]
    pane = window.panes[0]
    assert mysession.session_name == "test_new_session_env"
    assert server.has_session("test_new_session_env")

    pane_start_command = pane.pane_start_command
    assert pane_start_command is not None

    assert pane_start_command.replace('"', "") == cmd


@pytest.mark.skipif(True, reason="tmux 3.2 returns wrong width - test needs rework")
def test_new_session_width_height(server: Server) -> None:
    """Verify ``Server.new_session`` creates valid session running w/ dimensions."""
    cmd = "/usr/bin/env PS1='$ ' sh"
    mysession = server.new_session(
        "test_new_session_width_height",
        window_command=cmd,
        x=32,
        y=32,
    )
    window = mysession.windows[0]
    pane = window.panes[0]
    assert pane.display_message("#{window_width}", get_text=True)[0] == "32"
    assert pane.display_message("#{window_height}", get_text=True)[0] == "32"


def test_new_session_environmental_variables(
    server: Server,
) -> None:
    """Server.new_session creates and returns valid session."""
    my_session = server.new_session("test_new_session", environment={"FOO": "HI"})

    assert my_session.show_environment()["FOO"] == "HI"


def test_no_server_sessions(server: Server) -> None:
    """Verify ``Server.sessions`` returns empty list without tmux server."""
    assert server.sessions == []


def test_no_server_attached_sessions(server: Server) -> None:
    """Verify ``Server.attached_sessions`` returns empty list without tmux server."""
    assert server.attached_sessions == []


def test_no_server_is_alive(server: Server) -> None:
    """Verify is_alive() returns False without tmux server."""
    assert not server.is_alive()


def test_with_server_is_alive(server: Server) -> None:
    """Verify is_alive() returns True when tmux server is alive."""
    server.new_session()
    assert server.is_alive()


def test_raise_if_dead_no_server_raises(server: Server) -> None:
    """Verify ``Server.raise_if_dead`` raises if tmux server is dead."""
    with pytest.raises(subprocess.CalledProcessError):
        server.raise_if_dead()


def test_raise_if_dead_does_not_raise_if_alive(server: Server) -> None:
    """Verify new_session() does not raise if tmux server is alive."""
    server.new_session()
    server.raise_if_dead()


def test_on_init(server: Server) -> None:
    """Verify on_init callback is called during Server initialization."""
    called_with: list[Server] = []

    def on_init(server: Server) -> None:
        called_with.append(server)

    myserver = Server(socket_name="test_on_init", on_init=on_init)
    try:
        assert len(called_with) == 1
        assert called_with[0] is myserver
    finally:
        if myserver.is_alive():
            myserver.kill()


def test_socket_name_factory(server: Server) -> None:
    """Verify socket_name_factory generates socket names."""
    socket_names: list[str] = []

    def socket_name_factory() -> str:
        name = f"test_socket_{len(socket_names)}"
        socket_names.append(name)
        return name

    myserver = Server(socket_name_factory=socket_name_factory)
    try:
        assert myserver.socket_name == "test_socket_0"
        assert socket_names == ["test_socket_0"]

        # Creating another server should use factory again
        myserver2 = Server(socket_name_factory=socket_name_factory)
        try:
            assert myserver2.socket_name == "test_socket_1"
            assert socket_names == ["test_socket_0", "test_socket_1"]
        finally:
            if myserver2.is_alive():
                myserver2.kill()
    finally:
        if myserver.is_alive():
            myserver.kill()
        if myserver2.is_alive():
            myserver2.kill()


def test_socket_name_precedence(server: Server) -> None:
    """Verify socket_name takes precedence over socket_name_factory."""

    def socket_name_factory() -> str:
        return "from_factory"

    myserver = Server(
        socket_name="explicit_name",
        socket_name_factory=socket_name_factory,
    )
    myserver2 = Server(socket_name_factory=socket_name_factory)
    try:
        assert myserver.socket_name == "explicit_name"

        # Without socket_name, factory is used
        assert myserver2.socket_name == "from_factory"
    finally:
        if myserver.is_alive():
            myserver.kill()
        if myserver2.is_alive():
            myserver2.kill()


def test_server_context_manager(TestServer: type[Server]) -> None:
    """Test Server context manager functionality."""
    with TestServer() as server:
        session = server.new_session()
        assert server.is_alive()
        assert len(server.sessions) == 1
        assert session in server.sessions

    # Server should be killed after exiting context
    assert not server.is_alive()


class StartDirectoryTestFixture(t.NamedTuple):
    """Test fixture for start_directory parameter testing."""

    test_id: str
    start_directory: StrPath | None
    description: str


START_DIRECTORY_TEST_FIXTURES: list[StartDirectoryTestFixture] = [
    StartDirectoryTestFixture(
        test_id="none_value",
        start_directory=None,
        description="None should not add -c flag",
    ),
    StartDirectoryTestFixture(
        test_id="empty_string",
        start_directory="",
        description="Empty string should not add -c flag",
    ),
    StartDirectoryTestFixture(
        test_id="user_path",
        start_directory="{user_path}",
        description="User path should add -c flag",
    ),
    StartDirectoryTestFixture(
        test_id="relative_path",
        start_directory="./relative/path",
        description="Relative path should add -c flag",
    ),
]


@pytest.mark.parametrize(
    list(StartDirectoryTestFixture._fields),
    START_DIRECTORY_TEST_FIXTURES,
    ids=[test.test_id for test in START_DIRECTORY_TEST_FIXTURES],
)
def test_new_session_start_directory(
    test_id: str,
    start_directory: StrPath | None,
    description: str,
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    user_path: pathlib.Path,
) -> None:
    """Test Server.new_session start_directory parameter handling."""
    monkeypatch.chdir(tmp_path)

    # Format path placeholders with actual fixture values
    actual_start_directory = start_directory
    expected_path = None

    if start_directory and str(start_directory) not in {"", "None"}:
        if f"{user_path}" in str(start_directory):
            # Replace placeholder with actual user_path
            actual_start_directory = str(start_directory).format(user_path=user_path)
            expected_path = str(user_path)
        elif str(start_directory).startswith("./"):
            # For relative paths, use tmp_path as base
            temp_dir = tmp_path / "relative" / "path"
            temp_dir.mkdir(parents=True, exist_ok=True)
            actual_start_directory = str(temp_dir)
            expected_path = str(temp_dir.resolve())

    # Should not raise an error
    session = server.new_session(
        session_name=f"test_session_{test_id}",
        start_directory=actual_start_directory,
    )

    assert session.session_name == f"test_session_{test_id}"
    assert server.has_session(f"test_session_{test_id}")

    # Verify working directory if we have an expected path
    if expected_path:
        active_pane = session.active_window.active_pane
        assert active_pane is not None
        active_pane.refresh()
        assert active_pane.pane_current_path is not None
        actual_path = str(pathlib.Path(active_pane.pane_current_path).resolve())
        assert actual_path == expected_path


def test_new_session_start_directory_pathlib(
    server: Server,
    user_path: pathlib.Path,
) -> None:
    """Test Server.new_session accepts pathlib.Path for start_directory."""
    # Pass pathlib.Path directly to test pathlib.Path acceptance
    session = server.new_session(
        session_name="test_pathlib_start_dir",
        start_directory=user_path,
    )

    assert session.session_name == "test_pathlib_start_dir"
    assert server.has_session("test_pathlib_start_dir")

    # Verify working directory
    active_pane = session.active_window.active_pane
    assert active_pane is not None
    active_pane.refresh()
    assert active_pane.pane_current_path is not None
    actual_path = str(pathlib.Path(active_pane.pane_current_path).resolve())
    expected_path = str(user_path.resolve())
    assert actual_path == expected_path


def test_tmux_bin_default(server: Server) -> None:
    """Default tmux_bin is None, falls back to shutil.which."""
    assert server.tmux_bin is None


def test_tmux_bin_custom_path(caplog: pytest.LogCaptureFixture) -> None:
    """Custom tmux_bin path is used for commands.

    Uses a manual Server instance (not the ``server`` fixture) because this
    test must control the tmux_bin parameter at construction time.
    """
    tmux_path = shutil.which("tmux")
    assert tmux_path is not None
    s = Server(socket_name="test_tmux_bin", tmux_bin=tmux_path)
    try:
        assert s.tmux_bin == tmux_path
        with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
            s.cmd("list-sessions")
        running_records = [r for r in caplog.records if hasattr(r, "tmux_cmd")]
        assert any(tmux_path in r.tmux_cmd for r in running_records)
    finally:
        if s.is_alive():
            s.kill()


def test_tmux_bin_invalid_path() -> None:
    """Invalid tmux_bin raises TmuxCommandNotFound."""
    from libtmux import exc

    s = Server(tmux_bin="/nonexistent/tmux")
    with pytest.raises(exc.TmuxCommandNotFound):
        s.cmd("list-sessions")


def test_tmux_bin_invalid_path_raise_if_dead() -> None:
    """Invalid tmux_bin raises TmuxCommandNotFound in raise_if_dead()."""
    from libtmux import exc

    s = Server(tmux_bin="/nonexistent/tmux")
    with pytest.raises(exc.TmuxCommandNotFound):
        s.raise_if_dead()


class ConfirmBeforeCase(t.NamedTuple):
    """Test case for confirm_before()."""

    test_id: str
    confirm_key: str
    use_default_yes: bool
    custom_confirm_key: str | None
    option_name: str
    expected_value: str
    min_tmux_version: str | None


CONFIRM_BEFORE_CASES: list[ConfirmBeforeCase] = [
    ConfirmBeforeCase(
        test_id="confirm_y",
        confirm_key="y",
        use_default_yes=False,
        custom_confirm_key=None,
        option_name="@cf_test_y",
        expected_value="yes",
        min_tmux_version="3.4",
    ),
    ConfirmBeforeCase(
        test_id="default_yes_enter",
        confirm_key="Enter",
        use_default_yes=True,
        custom_confirm_key=None,
        option_name="@cf_test_enter",
        expected_value="yes",
        min_tmux_version="3.4",
    ),
]


@pytest.mark.parametrize(
    list(ConfirmBeforeCase._fields),
    CONFIRM_BEFORE_CASES,
    ids=[c.test_id for c in CONFIRM_BEFORE_CASES],
)
def test_confirm_before(
    test_id: str,
    confirm_key: str,
    use_default_yes: bool,
    custom_confirm_key: str | None,
    option_name: str,
    expected_value: str,
    min_tmux_version: str | None,
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.confirm_before() with send-keys -K confirmation."""
    from libtmux.common import has_gte_version

    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    with control_mode() as ctl:
        kwargs: dict[str, t.Any] = {"target_client": ctl.client_name}
        if use_default_yes:
            kwargs["default_yes"] = True
        if custom_confirm_key is not None:
            kwargs["confirm_key"] = custom_confirm_key

        server.confirm_before(f"set -g {option_name} {expected_value}", **kwargs)
        server.cmd("send-keys", "-K", "-c", ctl.client_name, confirm_key)

    result = server.cmd("show-options", "-gv", option_name)
    assert result.stdout[0] == expected_value


class CommandPromptCase(t.NamedTuple):
    """Test case for command_prompt()."""

    test_id: str
    template: str
    keys: list[str]
    inputs: str | None
    option_name: str
    expected_value: str
    min_tmux_version: str | None


COMMAND_PROMPT_CASES: list[CommandPromptCase] = [
    CommandPromptCase(
        test_id="type_and_submit",
        template="set -g @cp_typed '%1'",
        keys=["h", "e", "l", "l", "o", "Enter"],
        inputs=None,
        option_name="@cp_typed",
        expected_value="hello",
        min_tmux_version="3.4",
    ),
    CommandPromptCase(
        test_id="prefill_and_submit",
        template="set -g @cp_prefill '%1'",
        keys=["Enter"],
        inputs="prefilled",
        option_name="@cp_prefill",
        expected_value="prefilled",
        min_tmux_version="3.4",
    ),
]


@pytest.mark.parametrize(
    list(CommandPromptCase._fields),
    COMMAND_PROMPT_CASES,
    ids=[c.test_id for c in COMMAND_PROMPT_CASES],
)
def test_command_prompt(
    test_id: str,
    template: str,
    keys: list[str],
    inputs: str | None,
    option_name: str,
    expected_value: str,
    min_tmux_version: str | None,
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.command_prompt() with send-keys -K input."""
    from libtmux.common import has_gte_version

    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    with control_mode() as ctl:
        kwargs: dict[str, t.Any] = {"target_client": ctl.client_name}
        if inputs is not None:
            kwargs["inputs"] = inputs

        server.command_prompt(template, **kwargs)

        for key in keys:
            server.cmd("send-keys", "-K", "-c", ctl.client_name, key)

    result = server.cmd("show-options", "-gv", option_name)
    assert result.stdout[0] == expected_value


@pytest.mark.parametrize(
    ("kwargs", "expected_flag", "min_tmux_version"),
    [
        ({"expand_format": True}, "-F", "3.3"),
        ({"literal": True}, "-l", "3.6"),
        # -e is master-only (upstream 1e5f93b7); not in any 3.6 release
        ({"bspace_exit": True}, "-e", "3.7"),
        ({"no_freeze": True}, "-C", "3.7"),
    ],
    ids=["expand_format_v33", "literal_v36", "bspace_exit", "no_freeze"],
)
def test_command_prompt_extra_flags(
    kwargs: dict[str, t.Any],
    expected_flag: str,
    min_tmux_version: str | None,
    monkeypatch: pytest.MonkeyPatch,
    server: Server,
) -> None:
    """``command_prompt`` exposes -F/-l/-e flags.

    End-to-end behaviour for these flags depends on tmux internals
    that are awkward to drive from a headless test (format
    expansion, comma-split disabling, backspace-exit). Verify the
    constructed argv instead, matching the test_display_menu_flags
    monkeypatch pattern.
    """
    from libtmux.common import has_gte_version

    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    captured: list[tuple[str, ...]] = []
    real_cmd = server.cmd

    class _StubResult:
        stderr: t.ClassVar[list[str]] = []
        stdout: t.ClassVar[list[str]] = []

    def fake_cmd(cmd: str, *args: str, **_kw: t.Any) -> t.Any:
        if cmd == "command-prompt":
            captured.append((cmd, *args))
            return _StubResult()
        return real_cmd(cmd, *args, **_kw)

    monkeypatch.setattr(server, "cmd", fake_cmd)
    server.command_prompt("set -g @x '%1'", **kwargs)

    assert captured, "Server.cmd was not invoked"
    _name, *flags = captured[0]
    assert expected_flag in flags


class DisplayMenuCase(t.NamedTuple):
    """Test case for display_menu() flag variations."""

    test_id: str
    items: tuple[str, ...]
    kwargs: dict[str, t.Any]
    min_tmux_version: str | None


_MENU_ITEM = ("First", "1", "select-pane")


DISPLAY_MENU_CASES: list[DisplayMenuCase] = [
    DisplayMenuCase(
        test_id="basic",
        items=_MENU_ITEM,
        kwargs={},
        min_tmux_version=None,
    ),
    DisplayMenuCase(
        test_id="with_title",
        items=_MENU_ITEM,
        kwargs={"title": "menu_title"},
        min_tmux_version=None,
    ),
    DisplayMenuCase(
        test_id="with_position",
        items=_MENU_ITEM,
        kwargs={"x": "C", "y": "C"},
        min_tmux_version=None,
    ),
    DisplayMenuCase(
        test_id="with_starting_choice_v34",
        items=_MENU_ITEM,
        kwargs={"starting_choice": "0"},
        min_tmux_version="3.4",
    ),
    DisplayMenuCase(
        test_id="with_border_lines_v34",
        items=_MENU_ITEM,
        kwargs={"border_lines": "single"},
        min_tmux_version="3.4",
    ),
    DisplayMenuCase(
        test_id="with_style_v34",
        items=_MENU_ITEM,
        kwargs={"style": "bg=blue"},
        min_tmux_version="3.4",
    ),
    DisplayMenuCase(
        test_id="with_border_style_v34",
        items=_MENU_ITEM,
        kwargs={"border_style": "fg=red"},
        min_tmux_version="3.4",
    ),
    DisplayMenuCase(
        test_id="with_stay_open",
        items=_MENU_ITEM,
        kwargs={"stay_open": True},
        min_tmux_version="3.2",
    ),
    DisplayMenuCase(
        test_id="with_selected_style_v34",
        items=_MENU_ITEM,
        kwargs={"selected_style": "bg=yellow"},
        min_tmux_version="3.4",
    ),
    DisplayMenuCase(
        test_id="with_mouse_v35",
        items=_MENU_ITEM,
        kwargs={"mouse": True},
        min_tmux_version="3.5",
    ),
]


@pytest.mark.parametrize(
    list(DisplayMenuCase._fields),
    DISPLAY_MENU_CASES,
    ids=[c.test_id for c in DISPLAY_MENU_CASES],
)
def test_display_menu_flags(
    test_id: str,
    items: tuple[str, ...],
    kwargs: dict[str, t.Any],
    min_tmux_version: str | None,
    monkeypatch: pytest.MonkeyPatch,
    server: Server,
) -> None:
    """Test Server.display_menu() argument construction.

    ``Server.display_menu``'s own docstring states it cannot be tested
    with :class:`ControlMode` (``tty.sy=0`` makes tmux's
    ``menu_prepare()`` return NULL and the call hangs). Without a
    TTY-backed client there is no way to invoke ``tmux display-menu``
    end-to-end, so this test stubs ``Server.cmd`` to capture and assert
    the constructed argument vector instead — the only deviation from
    the test-suite's standard "use real tmux" pattern.
    """
    from libtmux.common import has_gte_version

    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    captured: list[tuple[str, ...]] = []
    real_cmd = server.cmd

    class _StubResult:
        stderr: t.ClassVar[list[str]] = []
        stdout: t.ClassVar[list[str]] = []

    def fake_cmd(cmd: str, *args: str, **_kw: t.Any) -> t.Any:
        if cmd == "display-menu":
            captured.append((cmd, *args))
            return _StubResult()
        return real_cmd(cmd, *args, **_kw)

    monkeypatch.setattr(server, "cmd", fake_cmd)
    server.display_menu(*items, **kwargs)

    assert captured, "Server.cmd was not invoked"
    cmd, *flags = captured[0]
    assert cmd == "display-menu"
    # Items are appended at the end; every non-boolean flag value
    # should appear somewhere in the constructed argv. (Boolean
    # flags emit only the switch, not a value.)
    for value in kwargs.values():
        if isinstance(value, bool):
            continue
        assert str(value) in flags
    for item in items:
        assert item in flags


def test_lock_server(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.lock_server() runs without error."""
    with control_mode():
        server.lock_server()


def test_lock_client(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.lock_client() runs without error."""
    with control_mode():
        server.lock_client()


def test_refresh_client(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.refresh_client() runs without error."""
    with control_mode():
        server.refresh_client()


def test_refresh_client_request_clipboard(
    monkeypatch: pytest.MonkeyPatch,
    server: Server,
) -> None:
    """refresh_client(request_clipboard=True) emits -l on tmux 3.7+.

    ``refresh-client -l`` queries the client's clipboard via an xterm
    escape sequence, which has no observable effect under the headless
    test server, so verify the constructed argv instead.
    """
    from libtmux.common import has_gte_version

    if not has_gte_version("3.7"):
        pytest.skip("refresh-client -l clipboard query requires tmux 3.7+")

    captured: list[tuple[str, ...]] = []
    real_cmd = server.cmd

    class _StubResult:
        stderr: t.ClassVar[list[str]] = []
        stdout: t.ClassVar[list[str]] = []

    def fake_cmd(cmd: str, *args: str, **_kw: t.Any) -> t.Any:
        if cmd == "refresh-client":
            captured.append((cmd, *args))
            return _StubResult()
        return real_cmd(cmd, *args, **_kw)

    monkeypatch.setattr(server, "cmd", fake_cmd)
    server.refresh_client(request_clipboard=True)

    assert captured, "Server.cmd was not invoked"
    _name, *flags = captured[0]
    assert "-l" in flags


def test_suspend_client(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.suspend_client() runs without error."""
    with control_mode():
        server.suspend_client()


def test_server_access_list(server: Server) -> None:
    """Test Server.server_access() list mode."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("server-access added in tmux 3.3")

    server.new_session(session_name="access_test")
    result = server.server_access(list_access=True)
    assert isinstance(result, list)


def test_server_access_read_only_write_mutex(server: Server) -> None:
    """``read_only`` and ``write`` are mutually exclusive."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("server-access added in tmux 3.3")

    with pytest.raises(ValueError, match="mutually exclusive"):
        server.server_access(allow="someuser", read_only=True, write=True)


def test_server_access_argv(
    monkeypatch: pytest.MonkeyPatch,
    server: Server,
) -> None:
    """``server_access`` emits -r/-w when read_only/write are set.

    server-access requires real OS users and ACL state, so end-to-end
    testing of the side-effect would tie the suite to system config.
    Verify the constructed argv instead.
    """
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("server-access added in tmux 3.3")

    captured: list[tuple[str, ...]] = []
    real_cmd = server.cmd

    class _StubResult:
        stderr: t.ClassVar[list[str]] = []
        stdout: t.ClassVar[list[str]] = []

    def fake_cmd(cmd: str, *args: str, **_kw: t.Any) -> t.Any:
        if cmd == "server-access":
            captured.append((cmd, *args))
            return _StubResult()
        return real_cmd(cmd, *args, **_kw)

    monkeypatch.setattr(server, "cmd", fake_cmd)

    server.server_access(allow="alice", read_only=True)
    assert captured[-1][1:] == ("-a", "alice", "-r")

    server.server_access(allow="bob", write=True)
    assert captured[-1][1:] == ("-a", "bob", "-w")


def test_start_server(server: Server) -> None:
    """Test Server.start_server() runs without error."""
    server.new_session(session_name="startsvr_test")
    server.start_server()  # idempotent — already running


def test_bind_unbind_key(server: Server) -> None:
    """Test Server.bind_key() and unbind_key() cycle."""
    server.new_session(session_name="bind_test")

    server.bind_key("F12", "display-message bound", key_table="root")

    # Verify binding exists
    keys = server.list_keys(key_table="root")
    assert any("F12" in line for line in keys)

    # Unbind
    server.unbind_key("F12", key_table="root")

    # Verify binding gone
    keys = server.list_keys(key_table="root")
    assert not any("F12" in line and "display-message" in line for line in keys)


def test_list_keys(server: Server) -> None:
    """Test Server.list_keys() returns key bindings."""
    server.new_session(session_name="listkeys_test")
    result = server.list_keys()
    assert isinstance(result, list)
    assert len(result) > 0  # default bindings exist


def test_list_keys_format(server: Server) -> None:
    """Server.list_keys(format_=...) applies -F on tmux 3.7+; warns below."""
    from libtmux.common import has_gte_version

    server.new_session(session_name="listkeys_fmt")
    if has_gte_version("3.7"):
        result = server.list_keys(format_="fmt")
        assert result
        assert all(line == "fmt" for line in result)
    else:
        with pytest.warns(UserWarning, match=r"format requires tmux 3.7"):
            server.list_keys(format_="fmt")


def test_list_commands(server: Server) -> None:
    """Test Server.list_commands() returns command listing."""
    server.new_session(session_name="listcmds_test")

    # All commands
    result = server.list_commands()
    assert len(result) > 50  # tmux has many commands

    # Filtered
    result = server.list_commands(command_name="send-keys")
    assert len(result) >= 1
    assert "send-keys" in result[0]


def test_show_messages(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.show_messages() returns message log.

    ``tmux show-messages`` resolves the log against a target client
    (see ``cmd-show-messages.c``). In headless CI no client is
    attached, so spawn one via :func:`control_mode` and target it.
    """
    with control_mode() as ctl:
        result = server.show_messages(target_client=ctl.client_name)
    assert isinstance(result, list)


def test_show_messages_terminals_jobs(server: Server) -> None:
    """Test Server.show_messages(terminals=...) and (jobs=...) work clientless.

    tmux 3.6 added ``CMD_CLIENT_CANFAIL`` to ``cmd_show_messages_entry``
    (upstream commit b52dcff7, "Allow show-messages to work without a
    client"). On earlier tmux versions the command queue rejects the
    invocation with ``no current client`` before
    :c:func:`cmd_show_messages_exec` can take the ``-T``/``-J``
    early-return paths, so this clientless codepath is unreachable.
    """
    from libtmux.common import has_gte_version

    if not has_gte_version("3.6"):
        pytest.skip("show-messages -T/-J without a client requires tmux 3.6+")

    server.new_session(session_name="showmsg_alt_test")

    terminals = server.show_messages(terminals=True)
    assert isinstance(terminals, list)

    jobs = server.show_messages(jobs=True)
    assert isinstance(jobs, list)


def test_show_prompt_history(server: Server) -> None:
    """Test Server.show_prompt_history() returns history."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("show-prompt-history added in tmux 3.3")

    server.new_session(session_name="showph_test")
    result = server.show_prompt_history()
    assert isinstance(result, list)


def test_clear_prompt_history(server: Server) -> None:
    """Test Server.clear_prompt_history() clears history."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("clear-prompt-history added in tmux 3.3")

    server.new_session(session_name="clearph_test")
    server.clear_prompt_history()
    # Verify specific type can be cleared
    server.clear_prompt_history(prompt_type="command")


def test_wait_for_set_flag(server: Server) -> None:
    """Test Server.wait_for() with set_flag."""
    server.new_session(session_name="wait_test")
    # Just set the flag — should not block or error
    server.wait_for("test_channel_set", set_flag=True)


def test_run_shell_basic(server: Server) -> None:
    """Test Server.run_shell() executes command and returns output."""
    from libtmux.common import has_gte_version

    # tmux <3.5 does not write run-shell stdout back to the cmdq subprocess.
    # Restored by upstream commit fb37d52d, first released in 3.5.
    if not has_gte_version("3.5"):
        pytest.skip("run-shell stdout passthrough requires tmux 3.5+")

    server.new_session(session_name="run_shell_test")
    result = server.run_shell("echo hello_from_run_shell")
    assert result is not None
    assert any("hello_from_run_shell" in line for line in result)


def test_run_shell_background(server: Server) -> None:
    """Test Server.run_shell() in background mode."""
    server.new_session(session_name="run_shell_bg_test")
    result = server.run_shell("echo bg_test", background=True)
    assert result is None


def test_run_shell_cwd(server: Server, tmp_path: pathlib.Path) -> None:
    """``cwd=`` sets the working directory for the shell command."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.5"):
        pytest.skip("run-shell stdout passthrough requires tmux 3.5+")

    server.new_session(session_name="run_shell_cwd_test")
    result = server.run_shell("pwd", cwd=tmp_path)
    assert result is not None
    assert any(str(tmp_path) in line for line in result)


def test_run_shell_show_stderr(server: Server) -> None:
    """``show_stderr=True`` captures the command's stderr into the output."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.6"):
        pytest.skip("run-shell -E (JOB_SHOWSTDERR) requires tmux 3.6+")

    server.new_session(session_name="run_shell_stderr_test")
    result = server.run_shell(
        "sh -c 'echo to_stdout; echo to_stderr >&2'",
        show_stderr=True,
    )
    assert result is not None
    joined = "\n".join(result)
    assert "to_stdout" in joined
    assert "to_stderr" in joined


def test_run_shell_args(server: Server) -> None:
    """``args`` fill #{1}/#{2} in the command on tmux 3.7+; warn below."""
    from libtmux.common import has_gte_version

    server.new_session(session_name="run_shell_args_test")
    if has_gte_version("3.7"):
        result = server.run_shell("echo #{1}-#{2}", args=["alpha", "beta"])
        assert result == ["alpha-beta"]
    else:
        with pytest.warns(UserWarning, match=r"args requires tmux 3.7"):
            server.run_shell("echo plain", args=["alpha"])


def test_run_shell_cwd_warns_on_old_tmux(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """``cwd=`` emits a warning and skips ``-c`` on tmux <3.4.

    Simulates older tmux by patching ``has_gte_version`` in the
    :mod:`libtmux.server` module namespace (where it's bound at
    import time).
    """
    import libtmux.server

    monkeypatch.setattr(libtmux.server, "has_gte_version", lambda *a, **kw: False)
    server.new_session(session_name="run_shell_cwd_warn_test")
    with pytest.warns(UserWarning, match="cwd requires tmux 3.4+"):
        server.run_shell("true", cwd=tmp_path)


def test_run_shell_show_stderr_warns_on_old_tmux(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``show_stderr=True`` emits a warning and skips ``-E`` on tmux <3.6.

    Simulates older tmux by patching ``has_gte_version`` in the
    :mod:`libtmux.server` module namespace.
    """
    import libtmux.server

    monkeypatch.setattr(libtmux.server, "has_gte_version", lambda *a, **kw: False)
    server.new_session(session_name="run_shell_stderr_warn_test")
    with pytest.warns(UserWarning, match="show_stderr requires tmux 3.6+"):
        server.run_shell("true", show_stderr=True)


class BufferCase(t.NamedTuple):
    """Test case for buffer operations."""

    test_id: str
    data: str
    buffer_name: str | None
    append: bool | None
    expected_content: str


BUFFER_CASES: list[BufferCase] = [
    BufferCase(
        test_id="set_show_default",
        data="hello_buf",
        buffer_name=None,
        append=None,
        expected_content="hello_buf",
    ),
    BufferCase(
        test_id="set_show_named",
        data="named_data",
        buffer_name="mybuf",
        append=None,
        expected_content="named_data",
    ),
    BufferCase(
        test_id="set_show_append",
        # set_buffer() called twice in the test body for this case;
        # the first sets "first", the second appends "_second".
        data="_second",
        buffer_name="append_test",
        append=True,
        expected_content="first_second",
    ),
]


@pytest.mark.parametrize(
    list(BufferCase._fields),
    BUFFER_CASES,
    ids=[c.test_id for c in BUFFER_CASES],
)
def test_buffer_set_show(
    test_id: str,
    data: str,
    buffer_name: str | None,
    append: bool | None,
    expected_content: str,
    server: Server,
) -> None:
    """Test Server.set_buffer() and show_buffer() cycle."""
    server.new_session(session_name=f"buf_{test_id}")
    kwargs: dict[str, t.Any] = {}
    if buffer_name is not None:
        kwargs["buffer_name"] = buffer_name

    if append:
        # Seed the buffer with "first" so the appended *data* concatenates.
        server.set_buffer("first", buffer_name=buffer_name)
        kwargs["append"] = True

    server.set_buffer(data, **kwargs)
    result = server.show_buffer(buffer_name=buffer_name)
    assert result == expected_content


def test_buffer_delete(server: Server) -> None:
    """Test Server.delete_buffer()."""
    server.new_session(session_name="buf_delete")
    server.set_buffer("to_delete", buffer_name="del_buf")
    # Verify it exists
    assert server.show_buffer(buffer_name="del_buf") == "to_delete"

    # Delete it
    server.delete_buffer(buffer_name="del_buf")

    # Verify it's gone — show-buffer should raise
    with pytest.raises(exc.LibTmuxException):
        server.show_buffer(buffer_name="del_buf")


def test_buffer_save_load(server: Server, tmp_path: pathlib.Path) -> None:
    """Test Server.save_buffer() and load_buffer() cycle."""
    server.new_session(session_name="buf_saveload")

    # Set and save
    server.set_buffer("save_test_data")
    buf_file = tmp_path / "saved_buf.txt"
    server.save_buffer(buf_file)

    # Verify file content
    assert buf_file.read_text() == "save_test_data"

    # Load into a named buffer
    server.load_buffer(buf_file, buffer_name="loaded_buf")
    assert server.show_buffer(buffer_name="loaded_buf") == "save_test_data"


def test_buffer_save_append(server: Server, tmp_path: pathlib.Path) -> None:
    """Test Server.save_buffer() with append flag."""
    server.new_session(session_name="buf_saveappend")

    buf_file = tmp_path / "append_buf.txt"

    server.set_buffer("first_line", buffer_name="app1")
    server.save_buffer(buf_file, buffer_name="app1")

    server.set_buffer("second_line", buffer_name="app2")
    server.save_buffer(buf_file, buffer_name="app2", append=True)

    content = buf_file.read_text()
    assert "first_line" in content
    assert "second_line" in content


def test_list_buffers(server: Server) -> None:
    """Test Server.list_buffers()."""
    server.new_session(session_name="buf_list")
    server.set_buffer("buf_a", buffer_name="list_a")
    server.set_buffer("buf_b", buffer_name="list_b")

    result = server.list_buffers()
    assert len(result) >= 2


def test_list_buffers_format_returns_raw_names(server: Server) -> None:
    """``format_string`` projects raw names instead of the default template."""
    server.new_session(session_name="buf_format")
    server.set_buffer("payload_a", buffer_name="fmt_a")
    server.set_buffer("payload_b", buffer_name="fmt_b")

    names = server.list_buffers(format_string="#{buffer_name}")

    assert "fmt_a" in names
    assert "fmt_b" in names
    # Default template would contain "bytes:" — raw projection must not.
    assert not any("bytes:" in line for line in names)


def test_list_buffers_filter_pushes_predicate_into_tmux(server: Server) -> None:
    """``filter=`` pushes the match into tmux's format engine (-f flag).

    Only names matching the predicate come back from tmux; no Python-side
    post-filter is needed.
    """
    server.new_session(session_name="buf_filter")
    server.set_buffer("keep_me", buffer_name="gap6match_alpha")
    server.set_buffer("keep_me", buffer_name="gap6match_beta")
    server.set_buffer("drop_me", buffer_name="gap6miss_one")

    matches = server.list_buffers(
        format_string="#{buffer_name}",
        filter="#{m:gap6match_*,#{buffer_name}}",
    )

    assert sorted(matches) == ["gap6match_alpha", "gap6match_beta"]


def test_server_search_sessions_filter(server: Server) -> None:
    """``Server.list_sessions(filter=...)`` returns only matching sessions."""
    server.new_session(session_name="gap7_keep_alpha")
    server.new_session(session_name="gap7_keep_beta")
    server.new_session(session_name="other_drop")

    matches = server.search_sessions(filter="#{m:gap7_*,#{session_name}}")
    names = sorted(s.session_name for s in matches if s.session_name)
    assert names == ["gap7_keep_alpha", "gap7_keep_beta"]


def test_server_search_windows_filter(server: Server) -> None:
    """``Server.list_windows(filter=...)`` returns only matching windows."""
    sess = server.new_session(session_name="gap7_win_demo")
    sess.new_window(window_name="gap7_target")
    sess.new_window(window_name="other_window")

    matches = server.search_windows(filter="#{m:gap7_*,#{window_name}}")
    names = sorted(w.window_name for w in matches if w.window_name)
    # Catch-all base window starts at name 'gap7_win_demo' (matches gap7_*),
    # so we expect both the original and the new gap7_target.
    assert "gap7_target" in names
    assert "other_window" not in names


def test_server_search_panes_filter_by_id(server: Server) -> None:
    """``Server.list_panes(filter=...)`` returns only the pane id we asked for."""
    sess = server.new_session(session_name="gap7_pane_demo")
    target = sess.active_window.split()

    matches = server.search_panes(filter=f"#{{m:{target.pane_id},#{{pane_id}}}}")
    assert [p.pane_id for p in matches] == [target.pane_id]


def test_server_clients_returns_empty_on_tmux_error(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Server.clients`` returns an empty QueryList on tmux failure.

    Lenient-by-default contract: ``list-clients`` failing for any reason
    yields ``QueryList([])``, matching the historic shape of
    :attr:`Server.sessions`. Callers needing a connectivity check should
    use :meth:`Server.is_alive` or :meth:`Server.raise_if_dead`.
    """
    sentinel = exc.LibTmuxException("simulated list-clients failure")

    def _boom(**_: object) -> list[dict[str, str]]:
        raise sentinel

    monkeypatch.setattr("libtmux.server.fetch_objs", _boom)
    assert list(server.clients) == []


def test_server_search_sessions_propagates_errors(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Server.search_sessions`` re-raises tmux errors instead of swallowing them.

    Mirrors the clients-propagation contract: errors are surfaced, not
    buried as an empty QueryList that's indistinguishable from "filter
    matched nothing".
    """
    sentinel = exc.LibTmuxException("simulated list-sessions failure")

    def _boom(**_: object) -> list[dict[str, str]]:
        raise sentinel

    monkeypatch.setattr("libtmux.server.fetch_objs", _boom)
    with pytest.raises(exc.LibTmuxException, match="simulated list-sessions failure"):
        server.search_sessions(filter="#{m:keep_*,#{session_name}}")


def test_server_sessions_returns_empty_on_tmux_error(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Server.sessions`` returns an empty QueryList on tmux failure.

    Pins the lenient-by-default contract: a ``list-sessions`` failure —
    daemon down, missing socket, permission error, subprocess crash —
    yields ``QueryList([])`` rather than propagating. Callers that need
    to distinguish "no sessions" from "tmux unreachable" should use
    :meth:`Server.is_alive` or :meth:`Server.raise_if_dead`.
    """
    sentinel = exc.LibTmuxException("simulated list-sessions failure")

    def _boom(**_: object) -> list[dict[str, str]]:
        raise sentinel

    monkeypatch.setattr("libtmux.server.fetch_objs", _boom)
    assert list(server.sessions) == []


def test_server_sessions_missing_socket_returns_empty(tmp_path: pathlib.Path) -> None:
    """A not-yet-created tmux socket preserves the empty-list contract."""
    missing_server = Server(socket_path=tmp_path / "missing.sock")

    assert list(missing_server.sessions) == []


def test_server_sessions_permission_error_returns_empty(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection errors are absorbed into the empty-list contract too."""
    sentinel = exc.LibTmuxException(
        "error connecting to /root/libtmux-review.sock (Permission denied)"
    )

    def _boom(**_: object) -> list[dict[str, str]]:
        raise sentinel

    monkeypatch.setattr("libtmux.server.fetch_objs", _boom)
    assert list(server.sessions) == []


def test_if_shell_true(server: Server) -> None:
    """Test Server.if_shell() with true condition."""
    server.new_session(session_name="ifshell_test")
    server.if_shell("true", "set -g @if_test_true yes")

    result = server.cmd("show-options", "-gv", "@if_test_true")
    assert result.stdout[0] == "yes"


def test_if_shell_false_with_else(server: Server) -> None:
    """Test Server.if_shell() with false condition and else branch."""
    server.new_session(session_name="ifshell_else")
    server.if_shell(
        "false",
        "set -g @if_else_test yes",
        else_command="set -g @if_else_test no",
    )

    result = server.cmd("show-options", "-gv", "@if_else_test")
    assert result.stdout[0] == "no"


def test_source_file(server: Server, tmp_path: pathlib.Path) -> None:
    """Test Server.source_file() sources a config file."""
    server.new_session(session_name="source_test")

    conf = tmp_path / "source_test.conf"
    conf.write_text("set -g @source_test_opt yes\n")

    server.source_file(conf)

    # Verify the option was set
    result = server.cmd("show-options", "-gv", "@source_test_opt")
    assert result.stdout[0] == "yes"


def test_source_file_quiet(server: Server) -> None:
    """Test Server.source_file() with quiet flag ignores missing files."""
    server.new_session(session_name="source_quiet")

    # Non-existent file with quiet should not raise
    server.source_file("/nonexistent/path.conf", quiet=True)


def test_list_clients(server: Server) -> None:
    """Test Server.list_clients() returns list without error."""
    server.new_session(session_name="list_clients_test")
    result = server.list_clients()
    assert isinstance(result, list)


def test_detach_client_target_client_spans_sessions(
    control_mode: t.Callable[..., t.Any],
    server: Server,
    session: Session,
) -> None:
    """``Server.detach_client(target_client=...)`` resolves names server-wide.

    tmux's ``detach-client -t`` resolves the client over the global client
    list (``cmd-find.c``), not within any session scope. The named client
    can therefore be attached to any session — that is the reason this
    method lives on ``Server`` rather than ``Session``.
    """
    other_session = server.new_session(session_name="detach_other_t")
    OtherControlMode = functools.partial(
        ControlMode,
        server=server,
        session=other_session,
    )

    with control_mode(), OtherControlMode() as elsewhere:
        before = server.cmd("list-clients", "-F", "#{client_name}").stdout
        assert len(before) == 2
        assert elsewhere.client_name in before

        server.detach_client(target_client=elsewhere.client_name)

        after = server.cmd("list-clients", "-F", "#{client_name}").stdout
        assert elsewhere.client_name not in after
        assert len(after) == 1


def test_detach_client_no_target_uses_active(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """``Server.detach_client()`` without ``-t`` falls back to active client."""
    with control_mode(), control_mode():
        before = server.cmd("list-clients", "-F", "#{client_name}").stdout
        assert len(before) == 2

        server.detach_client()

        after = server.cmd("list-clients", "-F", "#{client_name}").stdout
        assert len(after) == 1


def test_detach_all_clients_keep_client_spans_sessions(
    control_mode: t.Callable[..., t.Any],
    server: Server,
    session: Session,
) -> None:
    """``Server.detach_all_clients(keep_client=...)`` is server-wide.

    Unlike ``Session.detach_client``, ``-a`` ignores session boundaries:
    a client attached to a different session must also be detached.
    """
    other_session = server.new_session(session_name="detach_all_other")
    OtherControlMode = functools.partial(
        ControlMode,
        server=server,
        session=other_session,
    )

    with control_mode() as keep, control_mode(), OtherControlMode():
        before = server.cmd("list-clients", "-F", "#{client_name}").stdout
        assert len(before) == 3

        server.detach_all_clients(keep_client=keep.client_name)

        after = server.cmd("list-clients", "-F", "#{client_name}").stdout
        assert after == [keep.client_name]


def test_detach_all_clients_no_keep_preserves_one(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """``-a`` without ``-t`` preserves tmux's most-recently-active client."""
    with control_mode(), control_mode():
        before = server.cmd("list-clients", "-F", "#{client_name}").stdout
        assert len(before) == 2

        server.detach_all_clients()

        after = server.cmd("list-clients", "-F", "#{client_name}").stdout
        assert len(after) == 1


def test_new_session_client_flags(
    server: Server,
) -> None:
    """Test Server.new_session() with client_flags flag."""
    session = server.new_session(
        session_name="flags_test",
        client_flags="no-output",
    )
    assert session.session_name == "flags_test"


class ServerDisplayMessageCase(t.NamedTuple):
    """Test case for Server.display_message() flag variations."""

    test_id: str
    cmd: str
    kwargs: dict[str, t.Any]
    expected_in_output: str | None
    min_tmux_version: str | None


SERVER_DISPLAY_MESSAGE_CASES: list[ServerDisplayMessageCase] = [
    ServerDisplayMessageCase(
        test_id="version",
        cmd="#{version}",
        kwargs={"get_text": True},
        expected_in_output=".",
        min_tmux_version=None,
    ),
    ServerDisplayMessageCase(
        test_id="socket_path_format_string",
        cmd="",
        kwargs={"get_text": True, "format_string": "#{socket_path}"},
        expected_in_output="/",
        min_tmux_version=None,
    ),
    ServerDisplayMessageCase(
        test_id="all_formats",
        cmd="",
        kwargs={"get_text": True, "all_formats": True},
        expected_in_output="session_name",
        min_tmux_version=None,
    ),
    ServerDisplayMessageCase(
        test_id="no_expand_literal",
        cmd="#{version}",
        kwargs={"get_text": True, "no_expand": True},
        expected_in_output="#{version}",
        min_tmux_version="3.4",
    ),
]


@pytest.mark.parametrize(
    list(ServerDisplayMessageCase._fields),
    SERVER_DISPLAY_MESSAGE_CASES,
    ids=[c.test_id for c in SERVER_DISPLAY_MESSAGE_CASES],
)
def test_server_display_message_flags(
    test_id: str,
    cmd: str,
    kwargs: dict[str, t.Any],
    expected_in_output: str | None,
    min_tmux_version: str | None,
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Server.display_message() resolves server-scoped formats without a pane.

    tmux dispatches ``display-message -p`` output through a client; the wrapper
    omits ``-t <pane-id>`` but still needs a client to receive stdout. The
    headless test environment provides one via :class:`ControlMode`.

    Skipped on tmux 3.2a: ``display-message -p -c <control-mode-client>``
    returns empty stdout on that release (output dispatch via a control-mode
    client was unreliable until later versions).
    """
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip(
            "display-message -p via control-mode client unreliable on tmux 3.2a"
        )
    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    with control_mode() as ctl:
        call_kwargs = dict(kwargs)
        call_kwargs.setdefault("target_client", ctl.client_name)
        result = server.display_message(cmd, **call_kwargs)

    if expected_in_output is not None:
        assert result is not None
        output = "\n".join(result)
        assert expected_in_output in output


def test_server_display_message_no_text_returns_none(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Without ``get_text=True`` the call renders to status line and returns None."""
    with control_mode() as ctl:
        result = server.display_message(
            "hi from libtmux", target_client=ctl.client_name
        )
    assert result is None


def test_server_display_message_target_client(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """``target_client`` is plumbed through as ``-c``; get_text=True returns stdout."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip(
            "display-message -p via control-mode client unreliable on tmux 3.2a"
        )

    with control_mode() as ctl:
        result = server.display_message(
            "#{version}", get_text=True, target_client=ctl.client_name
        )
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].strip() != ""


def test_server_display_message_warns_on_tmux_error(
    server: Server,
    session: Session,
) -> None:
    """Tmux stderr on ``display-message`` surfaces as a :class:`UserWarning`.

    Passing ``cmd`` and ``format_string`` together is rejected by tmux's
    argument parser with stderr ``only one of -F or argument must be
    given``. The wrapper must surface that to the caller without silently
    swallowing it.
    """
    with pytest.warns(UserWarning, match="only one of -F or argument"):
        server.display_message("x", get_text=True, format_string="#{version}")
