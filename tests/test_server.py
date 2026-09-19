"""Test for libtmux Server object."""

from __future__ import annotations

import contextlib
import functools
import logging
import os
import pathlib
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import typing as t

import pytest

from libtmux import common, exc
from libtmux._internal.control_mode import ControlMode
from libtmux.server import Server
from libtmux.test.retry import retry_until

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


def test_is_alive_propagates_timeout(
    hanging_tmux: tuple[str, pathlib.Path],
) -> None:
    """A wedged server is not reported ``False`` -- it is unknown, not dead.

    A bare ``except Exception: return False`` would swallow
    :exc:`~libtmux.exc.TmuxTimeout` into "dead", which is wrong for a
    server that is merely slow to answer; a caller told "dead" may start
    a second server alongside one that is still there. Bounded by
    ``Server.timeout`` rather than the stub's full 30s sleep.
    """
    binary, _pid_file = hanging_tmux
    wedged = Server(tmux_bin=binary, timeout=0.2)

    started = time.monotonic()
    with pytest.raises(exc.TmuxTimeout):
        wedged.is_alive()
    assert time.monotonic() - started < 5


def test_raise_if_dead_propagates_timeout(
    hanging_tmux: tuple[str, pathlib.Path],
) -> None:
    """``raise_if_dead`` honors ``Server.timeout`` instead of blocking.

    It used to run ``subprocess.check_call`` directly, bypassing
    ``Server.cmd`` and the server-wide timeout entirely, so this could
    block indefinitely against a wedged server. Bounded here by
    ``Server.timeout`` rather than the stub's full 30s sleep.
    """
    binary, _pid_file = hanging_tmux
    wedged = Server(tmux_bin=binary, timeout=0.2)

    started = time.monotonic()
    with pytest.raises(exc.TmuxTimeout):
        wedged.raise_if_dead()
    assert time.monotonic() - started < 5


def test_cmd_timeout_falls_back_to_server_default(
    hanging_tmux: tuple[str, pathlib.Path],
) -> None:
    """Omitting ``timeout`` on ``Server.cmd`` uses the server's own bound."""
    binary, _pid_file = hanging_tmux
    bounded = Server(tmux_bin=binary, timeout=0.2)

    with pytest.raises(exc.TmuxTimeout):
        bounded.cmd("list-sessions")


def test_cmd_timeout_none_opts_out_of_the_server_default(
    hanging_tmux: tuple[str, pathlib.Path],
) -> None:
    """An explicit ``timeout=None`` on ``Server.cmd`` overrides the server bound.

    ``timeout=self.timeout if timeout is None else timeout`` used to
    collapse an explicit opt-out onto the server default -- indistinguishable
    from omitting it -- so a caller could never run one command unbounded on
    a server that has a timeout.
    """
    binary, pid_file = hanging_tmux
    bounded = Server(tmux_bin=binary, timeout=0.2)
    outcome: list[object] = []

    def call() -> None:
        try:
            outcome.append(bounded.cmd("list-sessions", timeout=None))
        except BaseException as e:  # noqa: BLE001
            outcome.append(e)

    thread = threading.Thread(target=call, daemon=True)
    thread.start()
    thread.join(timeout=0.5)
    assert thread.is_alive(), "explicit timeout=None must not use the server bound"

    # Unblock the thread directly; libtmux's own timeout/kill path is what
    # this test verifies was never invoked.
    os.kill(int(pid_file.read_text()), signal.SIGKILL)
    thread.join(timeout=5)
    assert not thread.is_alive()

    assert len(outcome) == 1
    assert not isinstance(outcome[0], exc.TmuxTimeout)


def test_context_manager_exit_kills_despite_is_alive_timeout(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``__exit__`` still attempts a kill when ``is_alive`` times out.

    A wedged server is "unknown", not "dead" -- treating the timeout as
    "dead" would skip :meth:`Server.kill` and leak the daemon. ``__exit__``
    assumes alive and attempts the kill regardless.
    """
    killed: list[bool] = []
    monkeypatch.setattr(server, "kill", lambda *a, **kw: killed.append(True))

    def _boom() -> bool:
        raise exc.TmuxTimeout(["tmux", "list-sessions"], 0.2)

    monkeypatch.setattr(server, "is_alive", _boom)

    with server:
        pass

    assert killed == [True]


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


def test_owned_server_removes_unused_socket_directory(tmp_path: pathlib.Path) -> None:
    """An unused scope needs no executable and removes its private directory."""
    directory: pathlib.Path | None = None
    try:
        with Server.owned(tmux_bin=tmp_path / "missing-tmux") as owned:
            assert owned.socket_path is not None
            socket_path = pathlib.Path(owned.socket_path)
            directory = socket_path.parent
            assert directory.is_dir()
            assert not socket_path.exists()
        assert not directory.exists()
    finally:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)


def test_owned_server_keeps_its_private_endpoint(
    server: Server,
    session: Session,
) -> None:
    """Cleanup targets the created endpoint even if the yielded handle changes."""
    with Server.owned(tmux_bin=server.tmux_bin) as owned:
        owned.new_session("temporary")
        assert owned.socket_path is not None
        socket_path = pathlib.Path(owned.socket_path)
        assert socket_path.parent.stat().st_mode & 0o777 == 0o700
        assert owned.is_alive()
        owned.socket_path = server.socket_path
        owned.socket_name = server.socket_name

    assert not socket_path.parent.exists()
    assert not Server(socket_path=socket_path).is_alive()
    assert session in server.sessions


def test_owned_server_socket_path_equals_the_same_endpoint_by_string(
    server: Server,
) -> None:
    """``Server.owned``'s endpoint compares equal to itself addressed by ``str``.

    ``owned`` builds ``socket_path`` as a ``pathlib.Path``. ``__eq__``
    compares ``socket_path`` by value, and ``Path("/x") != "/x"``, so
    passing that ``Path`` straight through used to make the owned server
    compare unequal to the identical endpoint addressed by string --
    unlike every other constructor, which only ever sees a ``str``.
    """
    with Server.owned(tmux_bin=server.tmux_bin) as owned:
        assert owned.socket_path is not None
        assert isinstance(owned.socket_path, str)
        by_string = Server(socket_path=str(owned.socket_path), tmux_bin=server.tmux_bin)
        assert owned == by_string


def test_owned_server_cleans_up_after_body_failure(server: Server) -> None:
    """An exception still terminates the private daemon and removes its socket."""
    body_error = RuntimeError("body failed")
    with (
        pytest.raises(RuntimeError, match="body failed"),
        Server.owned(tmux_bin=server.tmux_bin) as owned,
    ):
        owned.new_session("temporary")
        assert owned.socket_path is not None
        socket_path = pathlib.Path(owned.socket_path)
        raise body_error
    assert not socket_path.parent.exists()


_OWNED_SIGNAL_CHILD_SCRIPT = """\
import pathlib
import signal
import sys
import time

# Reset to the default disposition explicitly: SIG_IGN survives exec, and
# an inherited ignore would make this child immune to the very signal the
# test is about to send, hanging the test for an unrelated reason.
signal.signal(signal.SIGTERM, signal.SIG_DFL)
if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, signal.SIG_DFL)

from libtmux.server import Server

marker = pathlib.Path(sys.argv[1])
with Server.owned() as server:
    server.new_session(session_name="io")
    marker.write_text(str(server.socket_path))
    time.sleep(30)
"""


@pytest.mark.parametrize(
    "sig",
    [signal.SIGTERM, signal.SIGHUP],
    ids=["SIGTERM", "SIGHUP"],
)
def test_owned_cleans_up_on_termination_signal(
    tmp_path: pathlib.Path,
    sig: signal.Signals,
) -> None:
    """SIGTERM and SIGHUP trigger Server.owned()'s cleanup.

    Regression for a real defect: cleanup lived only in the context
    manager's own ``finally``, which never ran on the default
    disposition of SIGTERM or SIGHUP -- unlike SIGINT, which Python
    already turns into ``KeyboardInterrupt`` before this code ever sees
    it. Drives a *real* child process and sends it a *real* signal
    end to end (not a direct call to the handler function), so a fix
    that only works when invoked from within the same interpreter
    cannot pass this by accident.

    The child dies by the signal: cleanup runs from the handler
    itself, which re-raises against the process with the signal's
    default disposition restored, so ``proc.returncode`` is negative
    (``subprocess``'s convention for "killed by signal N").
    """
    script = tmp_path / "owned_signal_child.py"
    script.write_text(_OWNED_SIGNAL_CHILD_SCRIPT)
    marker = tmp_path / "socket_path.txt"

    proc = subprocess.Popen(
        [sys.executable, str(script), str(marker)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        assert marker.exists(), (
            f"child never reported its socket_path; "
            f"exited={proc.poll()!r} stderr follows on failure"
        )
        socket_path = pathlib.Path(marker.read_text())

        proc.send_signal(sig)
        try:
            returncode = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            pytest.fail(
                f"child did not exit within 5s of {sig.name}; "
                "the signal leaked the daemon it was meant to reap"
            )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        stdout, stderr = proc.communicate()

    assert returncode == -sig, (
        f"expected exit {-sig} (killed by {sig.name}), got {returncode}\n"
        f"stdout:\n{stdout}\nstderr:\n{stderr}"
    )
    assert not Server(socket_path=socket_path).is_alive(), (
        "the private tmux daemon is still running after the signal"
    )
    assert not socket_path.exists(), "the private socket file was left behind"
    assert not socket_path.parent.exists(), (
        "the private socket directory was left behind"
    )


_OWNED_SIGNAL_SWALLOWED_CHILD_SCRIPT = """\
import pathlib
import signal
import sys
import time

signal.signal(signal.SIGTERM, signal.SIG_DFL)
if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, signal.SIG_DFL)

from libtmux.server import Server

marker = pathlib.Path(sys.argv[1])
survived = pathlib.Path(sys.argv[2])
with Server.owned() as server:
    server.new_session(session_name="io")
    marker.write_text(str(server.socket_path))
    try:
        time.sleep(30)
    except BaseException:
        pass
    survived.write_text("survived")
    time.sleep(5)
"""


def test_owned_cleanup_and_death_survive_a_bare_except_in_the_block(
    tmp_path: pathlib.Path,
) -> None:
    """A broad ``except`` inside the block cannot keep the process alive.

    Cleanup runs from the signal handler itself, and the process is
    killed by the signal directly afterward, so a bare ``except:`` (or
    ``except BaseException:``) wrapping code *inside* the
    ``with Server.owned():`` body never gets a chance to catch
    anything on this path -- the daemon is gone and the process is
    dead before the block's own ``except`` could run.
    """
    script = tmp_path / "owned_signal_swallowed_child.py"
    script.write_text(_OWNED_SIGNAL_SWALLOWED_CHILD_SCRIPT)
    marker = tmp_path / "socket_path.txt"
    survived = tmp_path / "survived.txt"

    proc = subprocess.Popen(
        [sys.executable, str(script), str(marker), str(survived)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        assert marker.exists(), (
            f"child never reported its socket_path; "
            f"exited={proc.poll()!r} stderr follows on failure"
        )
        socket_path = pathlib.Path(marker.read_text())

        proc.send_signal(signal.SIGTERM)
        try:
            returncode = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            pytest.fail(
                "child did not exit within 5s of SIGTERM; its own bare "
                "except swallowed the exit"
            )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        stdout, stderr = proc.communicate()

    assert returncode == -signal.SIGTERM, (
        f"expected exit {-signal.SIGTERM} (killed by SIGTERM despite the "
        f"block's own bare except), got {returncode}\n"
        f"stdout:\n{stdout}\nstderr:\n{stderr}"
    )
    assert not survived.exists(), (
        "the block's bare except ran past the signal and wrote its marker"
    )
    assert not Server(socket_path=socket_path).is_alive(), (
        "the private tmux daemon is still running after the signal"
    )
    assert not socket_path.exists(), "the private socket file was left behind"
    assert not socket_path.parent.exists(), (
        "the private socket directory was left behind"
    )


_OWNED_CLEANUP_FAILURE_CHILD_SCRIPT = """\
import pathlib
import signal
import sys
import time

signal.signal(signal.SIGTERM, signal.SIG_DFL)
if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, signal.SIG_DFL)

from libtmux.server import Server

# Force the signal handler's own cleanup to fail, so the test proves
# os.kill() still runs afterward rather than being skipped by the
# exception cleanup raised.
_real_cmd = Server.cmd


def _cmd_fails_kill_server(self, cmd, *args, **kwargs):
    if cmd == "kill-server":
        msg = "simulated kill-server failure"
        raise RuntimeError(msg)
    return _real_cmd(self, cmd, *args, **kwargs)


Server.cmd = _cmd_fails_kill_server

marker = pathlib.Path(sys.argv[1])
with Server.owned() as server:
    server.new_session(session_name="io")
    marker.write_text(str(server.socket_path))
    time.sleep(30)
"""


def test_owned_terminates_by_signal_even_when_cleanup_fails(
    tmp_path: pathlib.Path,
) -> None:
    """The signal still kills the process when the handler's cleanup fails.

    Regression for a real defect: ``_terminate`` ran ``_cleanup()`` then
    ``os.kill()`` as two sequential statements, so a cleanup failure (here,
    a ``kill-server`` call raising) skipped ``os.kill()`` -- the exception
    took the exit path instead of the signal, so the child exited with a
    plain nonzero status from an unhandled exception rather than being
    killed by SIGTERM, letting a broad ``except`` around the block observe
    it.
    """
    script = tmp_path / "owned_cleanup_failure_child.py"
    script.write_text(_OWNED_CLEANUP_FAILURE_CHILD_SCRIPT)
    marker = tmp_path / "socket_path.txt"

    proc = subprocess.Popen(
        [sys.executable, str(script), str(marker)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    socket_path: pathlib.Path | None = None
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        assert marker.exists(), (
            f"child never reported its socket_path; "
            f"exited={proc.poll()!r} stderr follows on failure"
        )
        socket_path = pathlib.Path(marker.read_text())

        proc.send_signal(signal.SIGTERM)
        try:
            returncode = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            pytest.fail(
                "child did not exit within 5s of SIGTERM; a failing "
                "cleanup blocked the re-raised signal"
            )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        stdout, stderr = proc.communicate()
        # The simulated kill-server failure prevented the child's own
        # cleanup from reaping its real daemon; do it here so the suite
        # doesn't leak a tmux process.
        if socket_path is not None:
            Server(socket_path=socket_path).cmd("kill-server")
            shutil.rmtree(socket_path.parent, ignore_errors=True)

    assert returncode == -signal.SIGTERM, (
        f"expected exit {-signal.SIGTERM} (killed by SIGTERM even though "
        f"cleanup failed), got {returncode}\n"
        f"stdout:\n{stdout}\nstderr:\n{stderr}"
    )


def test_owned_session_cleans_up_by_id_after_rename(
    server: Server,
    session: Session,
) -> None:
    """The created session is removed while pre-existing sessions survive."""
    with server.owned_session("temporary") as owned:
        session_id = owned.session_id
        owned.rename_session("renamed")
    assert server.sessions.get(session_id=session_id, default=None) is None
    assert session in server.sessions


def test_owned_session_kills_on_identity_guard_failure(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session missing an identity field is killed, not leaked.

    ``owned_session`` used to create the session, then run asserts and
    ``int()`` conversions in a gap before its try/finally began, so a
    failure there (or a bare ``assert`` skipped under ``python -O``)
    leaked the session instead of triggering cleanup.
    """
    real_new_session = Server.new_session

    def _new_session_missing_start_time(
        self: Server,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> Session:
        created = real_new_session(self, *args, **kwargs)
        created.start_time = None
        return created

    monkeypatch.setattr(Server, "new_session", _new_session_missing_start_time)

    with (
        pytest.raises(exc.LibTmuxException, match="start_time"),
        server.owned_session("identity_guard_failure"),
    ):
        pass

    assert not server.has_session("identity_guard_failure")


def test_owned_session_refuses_an_existing_name(
    server: Server,
    session: Session,
) -> None:
    """A failed creation never adopts or destroys the existing session."""
    with (
        pytest.raises(exc.TmuxSessionExists),
        server.owned_session(session.session_name),
    ):
        pytest.fail("an existing session must not be yielded")
    assert session in server.sessions


def test_owned_session_preserves_same_name_replacement(server: Server) -> None:
    """Deleting the owned session does not transfer ownership to its old name."""
    with server.owned_session("temporary") as owned:
        owned.kill()
        replacement = server.new_session("temporary")
    assert replacement in server.sessions


def test_owned_session_preserves_restarted_daemon(server: Server) -> None:
    """Reused ids on a new daemon must not receive cleanup for the old daemon."""
    with Server.owned(tmux_bin=server.tmux_bin) as private:
        with private.owned_session("original") as owned:
            original_id = owned.session_id
            private.kill()
            replacement = private.new_session("replacement")
            assert replacement.session_id == original_id
        assert replacement in private.sessions


def test_owned_session_cleans_up_after_body_failure(server: Server) -> None:
    """Cleanup runs during exception unwinding without swallowing the body error."""
    body_error = RuntimeError("body failed")
    with (
        pytest.raises(RuntimeError, match="body failed"),
        server.owned_session("temporary") as owned,
    ):
        session_id = owned.session_id
        raise body_error
    assert server.sessions.get(session_id=session_id, default=None) is None


def test_owned_session_preserves_body_and_cleanup_errors(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cleanup timeout remains visible with the original body error chained."""
    run_command = common.run_command
    body_error = RuntimeError("body failed")

    def run(
        *args: object,
        tmux_bin: str | None = None,
        timeout: float | None = None,
    ) -> common.CommandResult:
        if "if-shell" in args:
            raise exc.TmuxTimeout([str(arg) for arg in args], 0.1)
        return run_command(*args, tmux_bin=tmux_bin, timeout=timeout)

    with (
        monkeypatch.context() as patch,
        pytest.raises(exc.TmuxTimeout) as caught,
        server.owned_session() as owned,
    ):
        patch.setattr(common, "run_command", run)
        raise body_error
    assert caught.value.__context__ is body_error
    assert caught.value.timeout == 0.1
    assert owned in server.sessions
    owned.kill()


@pytest.mark.parametrize("stderr", ["", "cleanup refused"])
def test_owned_session_preserves_completed_cleanup_failure(
    server: Server,
    tmp_path: pathlib.Path,
    stderr: str,
) -> None:
    """A real child refuses cleanup; the error keeps the body failure chained."""
    executable = server.tmux_bin or shutil.which("tmux")
    assert executable is not None
    wrapper = tmp_path / "tmux-cleanup-refusal"
    wrapper.write_text(
        "#!/bin/sh\n"
        'for arg do\nif [ "$arg" = "if-shell" ]; then\n'
        f"printf %s {shlex.quote(stderr)} >&2\nexit 7\nfi\ndone\n"
        f'exec {shlex.quote(executable)} "$@"\n'
    )
    wrapper.chmod(0o700)
    refusing = Server(
        socket_name=server.socket_name,
        socket_path=server.socket_path,
        tmux_bin=str(wrapper),
    )
    body_error = RuntimeError("body failed")

    with (
        pytest.raises(exc.LibTmuxException) as caught,
        refusing.owned_session() as owned,
    ):
        raise body_error

    assert caught.value.__context__ is body_error
    assert (stderr or "Session cleanup exited with 7") in str(caught.value)
    assert owned in server.sessions
    owned.kill()


def test_owned_server_preserves_socket_after_cleanup_failure(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed cleanup retains a reachable endpoint so the caller can retry."""
    run_command = common.run_command
    cleanup_error = PermissionError("cleanup denied")

    def run(
        *args: object,
        tmux_bin: str | None = None,
        timeout: float | None = None,
    ) -> common.CommandResult:
        if "kill-server" in args:
            raise cleanup_error
        return run_command(*args, tmux_bin=tmux_bin, timeout=timeout)

    # Bound in the try below only on success; an earlier failure (e.g. inside
    # Server.owned itself) must not make the finally block dereference an
    # unbound name and mask that failure behind an UnboundLocalError, which
    # would also skip the kill and leak the daemon.
    owned: Server | None = None
    socket_path: pathlib.Path | None = None
    try:
        with (
            monkeypatch.context() as patch,
            pytest.raises(PermissionError),
            Server.owned(tmux_bin=server.tmux_bin) as owned,
        ):
            owned.new_session()
            assert owned.socket_path is not None
            socket_path = pathlib.Path(owned.socket_path)
            patch.setattr(common, "run_command", run)
        assert socket_path is not None
        assert socket_path.exists()
        assert owned.is_alive()
    finally:
        if owned is not None:
            owned.kill()
        if socket_path is not None:
            shutil.rmtree(socket_path.parent)


@pytest.mark.parametrize(
    ("returncode", "stderr"), [(7, ""), (7, "cleanup refused"), (0, "cleanup refused")]
)
def test_owned_server_preserves_socket_after_completed_cleanup_failure(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    returncode: int,
    stderr: str,
) -> None:
    """A real cleanup refusal retains a reachable endpoint for retry."""
    executable = server.tmux_bin or shutil.which("tmux")
    assert executable is not None
    wrapper = tmp_path / "tmux-server-cleanup-refusal"
    wrapper.write_text(
        "#!/bin/sh\n"
        'for arg do\nif [ "$arg" = "kill-server" ]; then\n'
        f"printf %s {shlex.quote(stderr)} >&2\nexit {returncode}\nfi\ndone\n"
        f'exec {shlex.quote(executable)} "$@"\n'
    )
    wrapper.chmod(0o700)
    removed: list[pathlib.Path] = []
    socket_path: pathlib.Path | None = None

    try:
        with monkeypatch.context() as patch, contextlib.ExitStack() as cleanup:
            # Keep the endpoint reachable even if the assertion exposes a regression.
            patch.setattr(shutil, "rmtree", removed.append)
            owned = cleanup.enter_context(Server.owned(tmux_bin=str(wrapper)))
            assert owned.socket_path is not None
            socket_path = pathlib.Path(owned.socket_path)
            owned.new_session()
            with pytest.raises(
                exc.LibTmuxException,
                match=stderr or f"Server cleanup exited with {returncode}",
            ):
                cleanup.close()
            assert not removed
            assert socket_path.exists()
            assert owned.is_alive()
    finally:
        if socket_path is not None:
            Server(socket_path=str(socket_path), tmux_bin=executable).kill()
            shutil.rmtree(socket_path.parent)


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


def test_new_session_start_directory_with_newline(
    server: Server,
    tmp_path: pathlib.Path,
) -> None:
    """A newline in ``start_directory`` must not corrupt the ``-P -F`` record.

    ``new_session`` parses its own record straight off ``proc.stdout[0]``, so
    a value containing a newline -- here ``pane_current_path``, echoed back
    because a session row also reports its active pane's fields -- used to
    split the record across output lines. ``parse_output``'s strict ``zip``
    then rejected the truncated fragment with ``ValueError: zip() argument 2
    is shorter than argument 1`` before a ``Session`` was ever built.
    """
    weird_directory = tmp_path / "we\nird"
    weird_directory.mkdir()

    session = server.new_session(
        session_name="test_newline_start_dir",
        start_directory=weird_directory,
    )

    assert session.session_name == "test_newline_start_dir"
    active_pane = session.active_window.active_pane
    assert active_pane is not None
    active_pane.refresh()
    assert active_pane.pane_current_path is not None
    actual_path = pathlib.Path(active_pane.pane_current_path).resolve()
    assert actual_path == weird_directory.resolve()


def test_tmux_bin_default(server: Server) -> None:
    """Default tmux_bin is None, falls back to shutil.which."""
    assert server.tmux_bin is None


def test_timeout_has_class_level_default() -> None:
    """``Server.timeout`` falls back like ``tmux_bin`` for a skipped ``__init__``.

    Every other configuration attribute (``socket_name``, ``socket_path``,
    ``tmux_bin``, ...) is declared at class level, so an instance built
    without going through ``__init__`` -- ``object.__new__``, or a subclass
    whose own ``__init__`` does not call ``super().__init__()`` -- still has
    a value to read. ``timeout`` was assigned only inside ``__init__``, so
    the same construction path raised ``AttributeError`` on first use.
    """
    bare = object.__new__(Server)
    assert bare.timeout is None


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


def test_server_access_flags_precede_positional_user(server: Server) -> None:
    """Boolean flags reach tmux's user lookup instead of its argv parser.

    ``server-access``'s own arg spec (``cmd-server-access.c``) declares
    ``adlrw`` as value-less flags with the user as a single trailing
    positional. Emitting ``-a myuser -r`` used to put ``myuser`` right
    after ``-a``, so tmux's getopt-style parser stopped recognizing ``-r``
    as a flag once it saw that bare word and rejected the call as "too many
    arguments" before ever looking up the user.

    ``server-access`` also refuses to touch the server owner's own entry
    (``pw_uid == getuid()``), and this suite has no second real OS account
    to allow -- so this proves the fix by reaching tmux's *next* validation
    step (an unknown-user lookup) rather than failing on argv shape first.
    """
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("server-access added in tmux 3.3")

    server.new_session(session_name="access_argv_order_test")

    with pytest.raises(exc.LibTmuxException, match="unknown user"):
        server.server_access(allow="nonexistent-libtmux-test-user", read_only=True)


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
    assert captured[-1][1:] == ("-a", "-r", "alice")

    server.server_access(allow="bob", write=True)
    assert captured[-1][1:] == ("-a", "-w", "bob")


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


def test_wait_for_signal(server: Server) -> None:
    """Test Server.wait_for() with signal, tmux's own name for -S."""
    server.new_session(session_name="wait_test")
    # Just set the flag — should not block or error
    server.wait_for("test_channel_signal", signal=True)


def test_wait_for_set_flag_is_a_deprecated_alias_for_signal(server: Server) -> None:
    """set_flag still works and warns; signal=, its natural spelling, now also works."""
    server.new_session(session_name="wait_test_deprecated")
    with pytest.deprecated_call(match="set_flag is deprecated in favor of signal"):
        server.wait_for("test_channel_set", set_flag=True)


def test_wait_for_unsignalled_channel_times_out(server: Server) -> None:
    """wait_for() bounds an unsignalled channel instead of blocking forever.

    The signature previously had no timeout parameter at all, and
    Server.owned()/Server() default to Server.timeout=None (unbounded),
    so a caller had no way to escape a channel that is never signalled.
    Bounded here well under this suite's own per-test budget -- an
    unbounded call left in by mistake would hang the run instead of
    merely failing it.
    """
    server.new_session(session_name="wait_test_timeout")
    started = time.monotonic()
    with pytest.raises(exc.TmuxTimeout):
        server.wait_for("never-signalled-py7", timeout=1)
    elapsed = time.monotonic() - started
    assert elapsed < 5, f"wait_for(timeout=1) took {elapsed:.2f}s to raise"


def test_wait_for_rejects_a_non_positive_timeout(server: Server) -> None:
    """A zero or negative timeout is a caller error, not a silent no-op.

    ``subprocess.Popen.communicate(timeout=0)`` (or a negative value)
    never gives the freshly spawned tmux process a chance to respond,
    so it always reads as expired -- a non-positive *timeout* is
    rejected up front instead of silently raising ``TmuxTimeout``
    without ``wait-for -S`` (or any other command) ever running.
    """
    server.new_session(session_name="wait_test_zero_timeout")

    with pytest.raises(ValueError, match="timeout must be positive"):
        server.wait_for("py2_7_zero", signal=True, timeout=0)

    with pytest.raises(ValueError, match="timeout must be positive"):
        server.wait_for("py2_7_negative", signal=True, timeout=-1)

    # Control: a positive timeout still runs the command normally.
    server.wait_for("py2_7_positive", signal=True, timeout=1)


def test_wait_for_lock_timeout_wedges_the_channel(server: Server) -> None:
    """A timed-out lock wait leaves the channel unlockable afterward.

    A tmux limitation, documented on :meth:`Server.wait_for`'s *lock*
    parameter rather than fixed: ``cmd-wait-for.c`` hands a pending
    lock to the next queued locker on unlock regardless of whether that
    locker gave up, and nothing removes a locker whose own wait already
    raised ``TmuxTimeout``. A lock wait bounded by *timeout* makes this
    reachable from the library for the first time.

    A clean control on a different, untouched channel proves the
    mechanism rather than merely that timeouts fire: lock, unlock, lock
    again succeeds there.
    """
    server.new_session(session_name="wait_test_lock_wedge")

    server.wait_for("py2_6_wedge", lock=True)
    with pytest.raises(exc.TmuxTimeout):
        server.wait_for("py2_6_wedge", lock=True, timeout=0.3)
    server.wait_for("py2_6_wedge", unlock=True)
    with pytest.raises(exc.TmuxTimeout):
        server.wait_for("py2_6_wedge", lock=True, timeout=1)

    # Control: a channel nothing else contended for is not wedged.
    server.wait_for("py2_6_control", lock=True)
    server.wait_for("py2_6_control", unlock=True)
    server.wait_for("py2_6_control", lock=True, timeout=1)
    server.wait_for("py2_6_control", unlock=True)


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


def test_server_clients_propagates_record_parse_error(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Server.clients`` re-raises a malformed-record failure.

    A :exc:`~libtmux.exc.TmuxRecordParseError` means ``list-clients``
    ran and replied, but a value contained the field separator, so the
    reply itself could not be split into records -- distinct from the
    generic :exc:`~libtmux.exc.LibTmuxException` cases above, which mean
    the invocation itself failed. Swallowing it into ``QueryList([])``
    would tell a caller "no clients" when tmux may hold clients libtmux
    simply could not read back; ``Server.windows``/``Server.panes``
    already raise the same failure via ``_fetch_or_empty``.
    """
    sentinel = exc.TmuxRecordParseError("simulated malformed record")

    def _boom(**_: object) -> list[dict[str, str]]:
        raise sentinel

    monkeypatch.setattr("libtmux.server.fetch_objs", _boom)
    with pytest.raises(exc.TmuxRecordParseError, match="simulated malformed record"):
        list(server.clients)


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


def test_server_sessions_propagates_record_parse_error(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Server.sessions`` re-raises a malformed-record failure.

    Mirrors ``test_server_clients_propagates_record_parse_error``: a
    :exc:`~libtmux.exc.TmuxRecordParseError` means the reply could not
    be parsed, not that ``list-sessions`` was unreachable, so it is not
    a case the empty-by-default contract covers.
    """
    sentinel = exc.TmuxRecordParseError("simulated malformed record")

    def _boom(**_: object) -> list[dict[str, str]]:
        raise sentinel

    monkeypatch.setattr("libtmux.server.fetch_objs", _boom)
    with pytest.raises(exc.TmuxRecordParseError, match="simulated malformed record"):
        list(server.sessions)


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


def test_dead_server_reads_empty_but_a_prior_session_handle_raises(
    server: Server,
) -> None:
    """A killed server's sessions/windows/panes disagree on how to fail.

    ``Server.sessions``/``.windows``/``.panes`` are lenient by default
    (see ``src/libtmux/AGENTS.md``), so a killed server reads exactly
    like an empty live one through those. But a ``Session``/``Window``
    handle obtained *before* the kill is not lenient at all:
    ``session.windows`` propagates
    :exc:`~libtmux.exc.LibTmuxException`. ``server.sessions == []``
    alone can never tell a caller which case they are in.
    """
    session = server.new_session(session_name="py9_dead_server")
    window = session.active_window

    server.kill()

    assert list(server.sessions) == []
    assert list(server.windows) == []
    assert list(server.panes) == []
    assert server.is_alive() is False

    with pytest.raises(exc.LibTmuxException):
        list(session.windows)
    with pytest.raises(exc.LibTmuxException):
        list(window.panes)


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

        retry_until(
            lambda: len(server.cmd("list-clients", "-F", "#{client_name}").stdout) == 1,
            2,
            raises=True,
        )
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

    tmux 3.2a rejects ``display-message -c <client>`` because its option
    parser treats ``-c`` as a flag without an argument.
    """
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("display-message -c requires tmux 3.3+")
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


@pytest.mark.filterwarnings("error")
def test_server_display_message_no_text_returns_none(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Without ``get_text=True`` the call renders to status line and returns None."""
    with control_mode():
        result = server.display_message("hi from libtmux")
    assert result is None


def test_server_display_message_target_client(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """``target_client`` is plumbed through as ``-c``; get_text=True returns stdout."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("display-message -c requires tmux 3.3+")

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


def test_server_timeout_bounds_every_command(
    hanging_tmux: tuple[str, pathlib.Path],
) -> None:
    """A server-level timeout is the policy for commands through it."""
    binary, _pid_file = hanging_tmux
    server = Server(tmux_bin=binary, timeout=0.3)

    with pytest.raises(exc.TmuxTimeout):
        server.cmd("list-sessions")


@pytest.mark.parametrize("accessor", ["sessions", "windows", "panes", "clients"])
def test_a_wedged_server_is_not_reported_as_empty(
    hanging_tmux: tuple[str, pathlib.Path],
    accessor: str,
) -> None:
    """A listing must raise rather than answer empty.

    A tmux server that stopped answering has not said it has nothing.
    Returning ``[]`` sends a caller on to create a session on a server
    that already has them. Every accessor is covered because three of
    them reimplemented the "empty means not ready" rule inline instead
    of sharing it.
    """
    binary, _pid_file = hanging_tmux
    server = Server(tmux_bin=binary, timeout=0.3)

    with pytest.raises(exc.TmuxTimeout):
        _ = getattr(server, accessor)


class _IdentityStub:
    """Stand-in for a freshly created session with a field tmux never reported."""

    def __init__(
        self,
        session_id: str | None = "$0",
        pid: str | None = "123",
        start_time: str | None = "1700000000",
    ) -> None:
        self.session_id = session_id
        self.pid = pid
        self.start_time = start_time


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        pytest.param("session_id", "no session_id", id="session_id"),
        pytest.param("pid", "no pid", id="pid"),
        pytest.param("start_time", "no start_time", id="start_time"),
    ],
)
def test_owned_session_identity_names_the_field_tmux_withheld(
    missing: str,
    expected: str,
) -> None:
    """A missing identity field is named, rather than reaching an f-string as None.

    The guard cannot be a bare ``assert``: ``python -O`` strips those, and the
    predicate would then match on the literal text ``"None"`` -- against every
    session whose own field tmux also withheld.
    """
    from libtmux.server import _session_identity_predicate

    stub = _IdentityStub(**{missing: None})

    with pytest.raises(exc.LibTmuxException, match=expected):
        _session_identity_predicate(t.cast("t.Any", stub))


def test_server_access_deny_precedes_the_positional_user(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``deny`` emits its flag before the user, as ``allow`` does.

    tmux reads ``adlrw`` as value-less flags and the user as one trailing
    positional, so a user emitted before a flag ends flag parsing and the call
    is refused as "too many arguments" before the lookup runs.
    """
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("server-access added in tmux 3.3")

    captured: list[tuple[str, ...]] = []

    class _StubResult:
        stderr: t.ClassVar[list[str]] = []
        stdout: t.ClassVar[list[str]] = []

    def fake_cmd(cmd: str, *args: str, **_kw: t.Any) -> t.Any:
        captured.append((cmd, *args))
        return _StubResult()

    monkeypatch.setattr(server, "cmd", fake_cmd)
    server.server_access(deny="someone", read_only=True)

    assert captured, "Server.cmd was not invoked"
    _name, *argv = captured[0]
    assert argv.index("-d") < argv.index("someone")
    assert argv.index("-r") < argv.index("someone")


@pytest.mark.parametrize(
    "raiser",
    [
        pytest.param("getsignal", id="getsignal-refuses"),
        pytest.param("signal", id="signal-refuses"),
    ],
)
def test_owned_server_survives_a_thread_that_cannot_take_signals(
    raiser: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scope opened off the main thread still yields, and still cleans up.

    ``signal.signal`` and ``signal.getsignal`` raise ``ValueError`` outside the
    main thread. The scope's cleanup does not depend on the handler, so
    refusing to install one is not a reason to refuse the scope.
    """

    def refuse(*_args: t.Any, **_kwargs: t.Any) -> t.NoReturn:
        msg = "signal only works in main thread"
        raise ValueError(msg)

    monkeypatch.setattr(signal, raiser, refuse)

    with Server.owned() as owned:
        owned.new_session(session_name="owned_signal_fallback")
        assert owned.is_alive()
        socket_path = owned.socket_path

    assert socket_path is not None
    assert not pathlib.Path(socket_path).exists()
