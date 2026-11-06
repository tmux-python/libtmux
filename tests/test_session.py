"""Test for libtmux Session object."""

from __future__ import annotations

import logging
import pathlib
import shutil
import typing as t
from contextlib import nullcontext as does_not_raise

import pytest

from libtmux import common, exc
from libtmux.constants import WindowDirection
from libtmux.pane import Pane
from libtmux.session import Session
from libtmux.test.constants import TEST_SESSION_PREFIX
from libtmux.test.random import namer
from libtmux.window import Window

if t.TYPE_CHECKING:
    from libtmux.server import Server

if t.TYPE_CHECKING:
    from typing import TypeAlias

    try:
        from _pytest.raises import RaisesExc
    except ImportError:
        from _pytest.python_api import RaisesContext  # type: ignore[attr-defined]

        RaisesExc: TypeAlias = RaisesContext[Exception]  # type: ignore[no-redef]

    from libtmux._internal.types import StrPath
    from libtmux.server import Server

logger = logging.getLogger(__name__)


def test_has_session(server: Server, session: Session) -> None:
    """Server.has_session returns True if has session_name exists."""
    TEST_SESSION_NAME = session.session_name
    assert TEST_SESSION_NAME is not None
    assert server.has_session(TEST_SESSION_NAME)
    assert not server.has_session(TEST_SESSION_NAME[:-2])
    assert server.has_session(TEST_SESSION_NAME[:-2], exact=False)
    assert not server.has_session("asdf2314324321")


def test_select_window(session: Session) -> None:
    """Session.select_window moves window."""
    # get the current window_base_index, since different user tmux config
    # may start at 0 or 1, or whatever they want.
    window_idx = session.active_window.window_index
    assert window_idx is not None
    window_base_index = int(window_idx)

    session.new_window(window_name="test_window")
    window_count = len(session.windows)

    assert window_count >= 2  # 2 or more windows

    assert len(session.windows) == window_count

    # tmux selects a window, moves to it, shows it as active_window
    selected_window1 = session.select_window(window_base_index)
    assert isinstance(selected_window1, Window)
    active_window1 = session.active_window

    assert selected_window1.id == active_window1.id

    # again: tmux selects a window, moves to it, shows it as
    # active_window
    selected_window2 = session.select_window(window_base_index + 1)
    assert isinstance(selected_window2, Window)
    active_window2 = session.active_window

    assert selected_window2.id == active_window2.id

    # assure these windows were really different
    assert selected_window1.id != selected_window2.id


def test_select_window_returns_Window(session: Session) -> None:
    """Session.select_window returns Window object."""
    window_count = len(session.windows)
    assert len(session.windows) == window_count

    window_idx = session.active_window.window_index
    assert window_idx is not None
    window_base_index = int(window_idx)
    window = session.select_window(window_base_index)
    assert isinstance(window, Window)


def test_active_window(session: Session) -> None:
    """Session.active_window returns Window."""
    assert isinstance(session.active_window, Window)


def test_active_pane(session: Session) -> None:
    """Session.active_pane returns Pane."""
    assert isinstance(session.active_pane, Pane)


def test_session_rename(session: Session) -> None:
    """Session.rename_session renames session."""
    session_name = session.session_name
    assert session_name is not None
    TEST_SESSION_NAME = session_name

    test_name = "testingdis_sessname"
    session.rename_session(test_name)
    session_name = session.session_name
    assert session_name is not None
    assert session_name == test_name
    session.rename_session(TEST_SESSION_NAME)
    session_name = session.session_name
    assert session_name is not None
    assert session_name == TEST_SESSION_NAME


def test_new_session(server: Server) -> None:
    """Server.new_session creates new session."""
    new_session_name = TEST_SESSION_PREFIX + next(namer)
    new_session = server.new_session(session_name=new_session_name, detach=True)

    assert isinstance(new_session, Session)
    assert new_session.session_name == new_session_name


def test_show_options(session: Session) -> None:
    """Session._show_options() returns dict."""
    options = session._show_options()
    assert isinstance(options, dict)


def test_set_show_options_single(session: Session) -> None:
    """Set option then Session._show_options(key)."""
    session.set_option("history-limit", 20)
    assert session._show_option("history-limit") == 20

    session.set_option("history-limit", 40)
    assert session._show_option("history-limit") == 40

    assert session._show_options()["history-limit"] == 40


def test_set_show_option(session: Session) -> None:
    """Set option then Session._show_option(key)."""
    session.set_option("history-limit", 20)
    assert session._show_option("history-limit") == 20

    session.set_option("history-limit", 40)

    assert session._show_option("history-limit") == 40


def test_empty_session_option_returns_None(session: Session) -> None:
    """Verify Session._show_option returns None for unset option."""
    assert session._show_option("default-shell") is None


def test_show_option_unknown(session: Session) -> None:
    """Session.show_option raises InvalidOption for invalid option."""
    with pytest.raises(exc.InvalidOption):
        session.show_option("moooz")


def test_show_option_ambiguous(session: Session) -> None:
    """Session._show_option raises AmbiguousOption for ambiguous option."""
    with pytest.raises(exc.AmbiguousOption):
        session._show_option("default-")


def test_set_option_ambiguous(session: Session) -> None:
    """Session.set_option raises AmbiguousOption for invalid option."""
    with pytest.raises(exc.AmbiguousOption):
        session.set_option("default-", 43)


def test_set_option_invalid(session: Session) -> None:
    """Session.set_option raises InvalidOption for invalid option."""
    with pytest.raises(exc.InvalidOption):
        session.set_option("afewewfew", 43)


def test_show_environment(session: Session) -> None:
    """Session.show_environment() returns dict."""
    vars_ = session.show_environment()
    assert isinstance(vars_, dict)


def test_set_show_environment_single(session: Session) -> None:
    """Set environment then Session.show_environment(key)."""
    session.set_environment("FOO", "BAR")
    assert session.getenv("FOO") == "BAR"

    session.set_environment("FOO", "DAR")
    assert session.getenv("FOO") == "DAR"

    assert session.show_environment()["FOO"] == "DAR"


def test_show_environment_not_set(session: Session) -> None:
    """Not set environment variable returns None."""
    assert session.getenv("BAR") is None


def test_remove_environment(session: Session) -> None:
    """Remove environment variable."""
    assert session.getenv("BAM") is None
    session.set_environment("BAM", "OK")
    assert session.getenv("BAM") == "OK"
    session.remove_environment("BAM")
    assert session.getenv("BAM") is None


def test_unset_environment(session: Session) -> None:
    """Unset environment variable."""
    assert session.getenv("BAM") is None
    session.set_environment("BAM", "OK")
    assert session.getenv("BAM") == "OK"
    session.unset_environment("BAM")
    assert session.getenv("BAM") is None


class PeriodRaisesBadSessionName(t.NamedTuple):
    """Test fixture for bad session name names."""

    test_id: str
    session_name: str
    raises: bool


PERIOD_RAISES_BAD_SESSION_NAME_FIXTURES: list[PeriodRaisesBadSessionName] = [
    PeriodRaisesBadSessionName(
        test_id="period_in_name",
        session_name="hey.period",
        raises=True,
    ),
    PeriodRaisesBadSessionName(
        test_id="colon_in_name",
        session_name="hey:its a colon",
        raises=True,
    ),
    PeriodRaisesBadSessionName(
        test_id="valid_name",
        session_name="hey moo",
        raises=False,
    ),
]


@pytest.mark.parametrize(
    list(PeriodRaisesBadSessionName._fields),
    PERIOD_RAISES_BAD_SESSION_NAME_FIXTURES,
    ids=[test.test_id for test in PERIOD_RAISES_BAD_SESSION_NAME_FIXTURES],
)
def test_periods_raise_bad_session_name(
    server: Server,
    session: Session,
    test_id: str,
    session_name: str,
    raises: bool,
) -> None:
    """Verify session names with periods raise BadSessionName."""
    new_name = session_name + "moo"  # used for rename / switch
    if raises:
        with pytest.raises(exc.BadSessionName):
            session.rename_session(new_name)

        with pytest.raises(exc.BadSessionName):
            server.new_session(session_name)

        with pytest.raises(exc.BadSessionName):
            server.has_session(session_name)

        with pytest.raises(exc.BadSessionName):
            server.switch_client(new_name)

        with pytest.raises(exc.BadSessionName):
            server.attach_session(new_name)

    else:
        server.new_session(session_name)
        server.has_session(session_name)
        session.rename_session(new_name)
        with pytest.raises(exc.LibTmuxException):
            server.switch_client(new_name)


def test_cmd_inserts_session_id(session: Session) -> None:
    """Verify Session.cmd() inserts session_id."""
    current_session_id = session.session_id
    last_arg = "last-arg"
    cmd = session.cmd("not-a-command", last_arg)
    assert "-t" in cmd.cmd
    assert current_session_id in cmd.cmd
    assert cmd.cmd[-1] == last_arg


class SessionWindowEnvironmentFixture(t.NamedTuple):
    """Test fixture for window environment variables in sessions."""

    test_id: str
    environment: dict[str, str]


SESSION_WINDOW_ENV_FIXTURES: list[SessionWindowEnvironmentFixture] = [
    SessionWindowEnvironmentFixture(
        test_id="single_env_var",
        environment={"ENV_VAR": "window"},
    ),
    SessionWindowEnvironmentFixture(
        test_id="multiple_env_vars",
        environment={"ENV_VAR_1": "window_1", "ENV_VAR_2": "window_2"},
    ),
]


@pytest.mark.parametrize(
    list(SessionWindowEnvironmentFixture._fields),
    SESSION_WINDOW_ENV_FIXTURES,
    ids=[test.test_id for test in SESSION_WINDOW_ENV_FIXTURES],
)
def test_new_window_with_environment(
    session: Session,
    test_id: str,
    environment: dict[str, str],
) -> None:
    """Verify new window with environment vars."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        attach=True,
        window_name="window_with_environment",
        window_shell=f"{env} PS1='$ ' sh",
        environment=environment,
    )
    pane = window.active_pane
    assert pane is not None
    for k, v in environment.items():
        pane.send_keys(f"echo ${k}")
        assert pane.capture_pane()[-2] == v


def test_session_new_window_with_direction(
    session: Session,
) -> None:
    """Verify new window with direction."""
    window = session.active_window
    window.refresh()

    window_initial = session.new_window(window_name="Example")
    assert window_initial.window_index == "2"

    window_before = session.new_window(
        window_name="Window before",
        direction=WindowDirection.Before,
    )
    window_initial.refresh()
    assert window_before.window_index == "1"
    assert window_initial.window_index == "3"

    window_after = session.new_window(
        window_name="Window after",
        direction=WindowDirection.After,
    )
    window_initial.refresh()
    window_after.refresh()
    assert window_after.window_index == "3"
    assert window_initial.window_index == "4"
    assert window_before.window_index == "1"


def test_session_context_manager(server: Server) -> None:
    """Test Session context manager functionality."""
    with server.new_session() as session:
        window = session.new_window()
        assert len(session.windows) >= 2  # Initial window + new window
        assert window in session.windows

    # Session should be killed after exiting context
    session_name = session.session_name
    assert session_name is not None
    assert not server.has_session(session_name)


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
def test_new_window_start_directory(
    test_id: str,
    start_directory: StrPath | None,
    description: str,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    user_path: pathlib.Path,
) -> None:
    """Test Session.new_window start_directory parameter handling."""
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
    window = session.new_window(
        window_name=f"test_window_{test_id}",
        start_directory=actual_start_directory,
    )

    assert window.window_name == f"test_window_{test_id}"
    assert window in session.windows

    # Verify working directory if we have an expected path
    if expected_path:
        active_pane = window.active_pane
        assert active_pane is not None
        active_pane.refresh()
        assert active_pane.pane_current_path is not None
        actual_path = str(pathlib.Path(active_pane.pane_current_path).resolve())
        assert actual_path == expected_path


def test_new_window_start_directory_pathlib(
    session: Session,
    user_path: pathlib.Path,
) -> None:
    """Test Session.new_window accepts pathlib.Path for start_directory."""
    # Pass pathlib.Path directly to test pathlib.Path acceptance
    window = session.new_window(
        window_name="test_pathlib_start_dir",
        start_directory=user_path,
    )

    assert window.window_name == "test_pathlib_start_dir"
    assert window in session.windows

    # Verify working directory
    active_pane = window.active_pane
    assert active_pane is not None
    active_pane.refresh()
    assert active_pane.pane_current_path is not None
    actual_path = str(pathlib.Path(active_pane.pane_current_path).resolve())
    expected_path = str(user_path.resolve())
    assert actual_path == expected_path


class SessionAttachRefreshFixture(t.NamedTuple):
    """Test fixture for Session.attach() refresh behavior regression.

    This tests the scenario where a session is killed while the user is attached,
    and then attach() tries to call refresh() which fails because the session
    no longer exists.

    See: https://github.com/tmux-python/tmuxp/issues/1002
    """

    test_id: str
    raises: type[Exception] | bool


SESSION_ATTACH_REFRESH_FIXTURES: list[SessionAttachRefreshFixture] = [
    SessionAttachRefreshFixture(
        test_id="session_killed_during_attach_should_not_raise",
        raises=False,  # attach() should NOT raise if session gone
    ),
]


@pytest.mark.parametrize(
    list(SessionAttachRefreshFixture._fields),
    SESSION_ATTACH_REFRESH_FIXTURES,
    ids=[test.test_id for test in SESSION_ATTACH_REFRESH_FIXTURES],
)
def test_session_attach_does_not_fail_if_session_killed_during_attach(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    test_id: str,
    raises: type[Exception] | bool,
) -> None:
    """Regression test: Session.attach() should not fail if session is killed.

    When a user is attached to a tmux session via `tmuxp load`, then kills the
    session from within tmux (e.g., kills all windows), and then detaches,
    the attach() method should not raise an exception.

    Currently, attach() calls self.refresh() after attach-session returns, which
    fails with TmuxObjectDoesNotExist if the session no longer exists.

    The fix is to remove the refresh() call from attach() since:
    1. attach-session is a blocking interactive command
    2. Session state can change arbitrarily while the user is attached
    3. Refreshing after such a command makes no semantic sense
    """
    from libtmux.common import tmux_cmd

    # Create a new session specifically for this test
    test_session = server.new_session(detach=True)

    # Store original cmd method
    original_cmd = test_session.cmd

    # Create a mock tmux_cmd result that simulates successful attach-session
    class MockTmuxCmd:
        def __init__(self) -> None:
            self.stdout: list[str] = []
            self.stderr: list[str] = []
            self.cmd: list[str] = ["tmux", "attach-session"]

    def patched_cmd(cmd_name: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        """Patched cmd that kills session after attach-session."""
        if cmd_name == "attach-session":
            # Simulate: attach-session succeeded, user worked, then killed session
            # This happens BEFORE refresh() is called
            test_session.kill()
            return MockTmuxCmd()  # type: ignore[return-value]
        return original_cmd(cmd_name, *args, **kwargs)

    monkeypatch.setattr(test_session, "cmd", patched_cmd)

    # Use context manager pattern for exception handling
    raises_ctx: RaisesExc = (
        pytest.raises(t.cast("type[Exception]", raises))
        if raises
        else t.cast("RaisesExc", does_not_raise())
    )
    with raises_ctx:
        test_session.attach()


def test_lock_session(session: Session) -> None:
    """Test Session.lock_session() runs without error."""
    session.lock_session()


def test_detach_client_no_target_detaches_all_session_clients(
    control_mode: t.Callable[..., t.Any],
    session: Session,
    server: Server,
) -> None:
    """Test Session.detach_client() without a target detaches all session clients.

    Without a target_client, the method uses ``-s session_id`` to scope the
    operation to this session, detaching all attached clients.
    """
    with control_mode(), control_mode():
        before = server.cmd("list-clients", "-F", "#{client_name}").stdout
        assert len(before) == 2

        session.detach_client()

        after = server.cmd("list-clients", "-F", "#{client_name}").stdout
        assert len(after) == 0


def test_last_window(session: Session) -> None:
    """Test Session.last_window() selects previous window."""
    w1 = session.new_window(window_name="last_a", attach=True)
    w2 = session.new_window(window_name="last_b", attach=True)
    session.refresh()
    assert session.active_window.window_id == w2.window_id

    result = session.last_window()
    assert result.window_id == w1.window_id


def test_next_window(session: Session) -> None:
    """Test Session.next_window() selects next window."""
    w1 = session.new_window(window_name="next_a", attach=True)
    session.new_window(window_name="next_b", attach=False)

    # Active is w1, next should go to next_b
    session.refresh()
    assert session.active_window.window_id == w1.window_id

    result = session.next_window()
    # Should have moved to a different window
    assert result.window_id != w1.window_id


def test_previous_window(session: Session) -> None:
    """Test Session.previous_window() selects previous window."""
    w1 = session.new_window(window_name="prev_a", attach=True)
    w2 = session.new_window(window_name="prev_b", attach=True)
    session.refresh()
    assert session.active_window.window_id == w2.window_id

    result = session.previous_window()
    assert result.window_id == w1.window_id


def test_new_window_kill_existing(session: Session) -> None:
    """Test Session.new_window() with kill_existing flag."""
    # Create a window at a specific index
    w1 = session.new_window(window_name="kill_orig", window_index="5")
    assert w1.window_name == "kill_orig"
    assert w1.window_index == "5"

    # Create another window at the same index with kill_existing
    w2 = session.new_window(
        window_name="kill_replace",
        window_index="5",
        kill_existing=True,
    )
    assert w2.window_name == "kill_replace"
    assert w2.window_index == "5"

    # Original window should be gone
    session.refresh()
    names = [w.window_name for w in session.windows]
    assert "kill_orig" not in names
    assert "kill_replace" in names


def test_new_window_select_existing(session: Session) -> None:
    """Test Session.new_window() with select_existing flag — new name."""
    # With a unique name and select_existing, a new window is created normally
    w = session.new_window(
        window_name="selexist_new",
        select_existing=True,
    )
    assert w.window_name == "selexist_new"


@pytest.mark.parametrize("attach", [False, True])
@pytest.mark.parametrize("name", ["logs", "reuse:logs"])
def test_new_window_reuses_existing_window(
    session: Session,
    attach: bool,
    name: str,
) -> None:
    """Reuse returns the same live window and honors selection."""
    existing = session.new_window(
        window_name=name,
        window_shell="exec /bin/cat",
    )
    pane = existing.active_pane
    assert pane is not None
    before = [(window.window_id, window.window_name) for window in session.windows]
    active_id = session.active_window.window_id

    reused = session.new_window(window_name=name, select_existing=True, attach=attach)

    assert reused.window_id == existing.window_id
    reused_pane = reused.active_pane
    assert reused_pane is not None
    assert reused_pane.pane_id == pane.pane_id
    assert reused_pane.pane_pid == pane.pane_pid
    assert reused_pane.pane_dead == "0"
    assert [
        (window.window_id, window.window_name) for window in session.windows
    ] == before
    assert session.active_window.window_id == (
        existing.window_id if attach else active_id
    )


@pytest.mark.skipif(
    not common.has_gte_version("3.8"), reason="Index reuse needs tmux 3.8"
)
@pytest.mark.parametrize("attach", [False, True])
@pytest.mark.parametrize("target_kind", ["index", "id", "other-session"])
def test_new_window_reuses_stable_target(
    session: Session, attach: bool, target_kind: str
) -> None:
    """Absolute targets retain the native choice and its program."""
    selected = session
    if target_kind == "other-session":
        selected = session.server.new_session(session_name="other-reuse")
    existing = selected.new_window(
        window_name="logs", window_index="5", window_shell="exec /bin/cat"
    )
    pane = existing.active_pane
    assert pane is not None
    before = {window.window_id for window in session.server.windows}
    target_window = None
    if target_kind == "id":
        assert existing.window_id is not None
        target_window = existing.window_id
    elif target_kind == "other-session":
        target_window = f"{selected.session_id}:"

    reused = session.new_window(
        window_name="logs",
        select_existing=True,
        attach=attach,
        window_index="5" if target_kind == "index" else "",
        target_window=target_window,
    )

    assert reused.window_id == existing.window_id
    reused_pane = reused.active_pane
    assert reused_pane is not None
    assert reused_pane.pane_pid == pane.pane_pid
    assert reused_pane.pane_dead == "0"
    assert {window.window_id for window in session.server.windows} == before


@pytest.mark.skipif(
    not common.has_gte_version("3.4"), reason="Name formats need tmux 3.4"
)
def test_new_window_reuse_does_not_guess_format_context(session: Session) -> None:
    """An unverifiable reply must not return a different live window."""
    session.new_window(window_name="logs")
    session.new_window(window_name="decoy")
    with pytest.raises(exc.LibTmuxException, match="identity of the reused window"):
        session.new_window(
            window_name="#{?session_format,logs,decoy}", select_existing=True
        )


@pytest.mark.skipif(
    not common.has_gte_version("3.4"), reason="Name formats need tmux 3.4"
)
@pytest.mark.parametrize("name", ["#{?session_format,logs,decoy}", "#{command}"])
def test_new_window_reuse_retains_native_selected_receipt(
    session: Session, name: str
) -> None:
    """A queued receipt precedes a selection hook that changes the active window."""
    expected = session.new_window(
        window_name="new-window" if name == "#{command}" else "logs",
        window_shell="exec /bin/cat",
    )
    decoy = session.new_window(window_name="decoy", window_shell="exec /bin/cat")
    pane = expected.active_pane
    assert pane is not None
    before = {window.window_id for window in session.windows}
    session.cmd(
        "set-hook", "session-window-changed", f"select-window -t {decoy.window_id}"
    )

    reused = session.new_window(window_name=name, select_existing=True, attach=True)

    assert reused.window_id == expected.window_id
    assert reused.window_name == expected.window_name
    assert reused.window_width == expected.window_width
    assert session.active_window.window_id == decoy.window_id
    reused_pane = reused.active_pane
    assert reused_pane is not None and reused_pane.pane_pid == pane.pane_pid
    assert reused_pane.pane_dead == "0"
    assert {window.window_id for window in session.windows} == before


@pytest.mark.skipif(
    not common.has_gte_version("3.8"), reason="Index reuse needs tmux 3.8"
)
@pytest.mark.parametrize("attach", [False, True])
@pytest.mark.parametrize("offset", ["+2", "-3"])
def test_new_window_reuses_relative_index_from_original_selection(
    session: Session, attach: bool, offset: str
) -> None:
    """Index arithmetic keeps its original origin across sparse native indexes."""
    origin = int(session.active_window.window_index or "0")
    expected = session.new_window(
        window_name="relative",
        window_index=str(origin + 2),
        window_shell="exec /bin/cat",
    )
    decoy = session.new_window(
        window_name="decoy", window_index=str(origin + 5), window_shell="exec /bin/cat"
    )
    if offset.startswith("-"):
        decoy.select()
    active = session.active_window.window_id
    pane = expected.active_pane
    assert pane is not None
    before = {window.window_id for window in session.windows}

    reused = session.new_window(
        window_index=offset, select_existing=True, attach=attach
    )

    assert reused.window_id == expected.window_id
    assert session.active_window.window_id == (expected.window_id if attach else active)
    reused_pane = reused.active_pane
    assert reused_pane is not None and reused_pane.pane_pid == pane.pane_pid
    assert {window.window_id for window in session.windows} == before


def test_new_window_reuse_rejects_failed_receipt(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed native status must not turn diagnostic stdout into a window."""
    session.new_window(window_name="logs", window_shell="exec /bin/cat")
    native = common.tmux_cmd

    def failed(*args: t.Any, **kwargs: t.Any) -> common.tmux_cmd:
        result = native(*args, **kwargs)
        if "new-window" in args:
            result.returncode = 1
            result.stderr = []
        return result

    monkeypatch.setattr("libtmux.server.tmux_cmd", failed)
    with pytest.raises(exc.LibTmuxException):
        session.new_window(window_name="logs", select_existing=True, attach=True)


@pytest.mark.parametrize("fault", ["prefix-only", "endpoint", "generation"])
def test_new_window_reuse_rejects_incomplete_identity(
    session: Session, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """Incomplete output or mismatched native provenance cannot select a window."""
    session.new_window(window_name="logs", window_shell="exec /bin/cat")
    native = common.tmux_cmd

    def corrupted(*args: t.Any, **kwargs: t.Any) -> common.tmux_cmd:
        result = native(*args, **kwargs)
        if "list-windows" in args and "new-window" in args:
            marker = args[args.index("-F") + 1].split("before", 1)[0]
            text = "\n".join(result.stdout)
            prefix, separator, suffix = text.partition(marker + "after" + marker)
            assert separator
            if fault == "prefix-only":
                text = prefix
            else:
                fields = suffix.split(marker)
                fields[0 if fault == "endpoint" else 1] += "9"
                text = prefix + separator + marker.join(fields)
            result.stdout = text.split("\n")
        return result

    monkeypatch.setattr("libtmux.server.tmux_cmd", corrupted)
    with pytest.raises(exc.LibTmuxException):
        session.new_window(window_name="logs", select_existing=True, attach=True)


def test_new_window_reuse_pins_observed_endpoint(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing the facade after submission must not redirect the returned window."""
    expected = session.new_window(window_name="logs", window_shell="exec /bin/cat")
    pane = expected.active_pane
    assert pane is not None
    native = common.tmux_cmd

    def redirected(*args: t.Any, **kwargs: t.Any) -> common.tmux_cmd:
        result = native(*args, **kwargs)
        if "new-window" in args:
            patch.setattr(session.server, "socket_name", "unused-reuse-endpoint")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(session.server, "config_file", "/dev/null")
        patch.setattr(session.server, "colors", 256)
        patch.setattr("libtmux.server.tmux_cmd", redirected)
        reused = session.new_window(
            window_name="logs", select_existing=True, attach=True
        )
        assert reused.window_id == expected.window_id
        assert reused == expected and reused.server is not session.server
        assert reused.server.config_file == "/dev/null"
        assert reused.server.colors == 256
        observed = reused.active_pane
        assert observed is not None and observed.pane_pid == pane.pane_pid
        reused.rename_window("retained-endpoint")
        reused.refresh()
        assert reused.window_name == "retained-endpoint"
    retained = session.windows.get(window_id=expected.window_id)
    assert retained is not None and retained.window_name == "retained-endpoint"


def test_new_window_reuse_freezes_explicit_executable(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A basename resolves once, before another caller can change PATH."""
    expected = session.new_window(window_name="logs", window_shell="exec /bin/cat")
    native = common.tmux_cmd

    def changed_path(*args: t.Any, **kwargs: t.Any) -> common.tmux_cmd:
        if "new-window" in args:
            patch.setenv("PATH", "/nonexistent-window-reuse-path")
        return native(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(session.server, "tmux_bin", "tmux")
        patch.setattr("libtmux.server.tmux_cmd", changed_path)
        reused = session.new_window(window_name="logs", select_existing=True)
        assert reused.window_id == expected.window_id
        pane = reused.active_pane
        assert pane is not None and pane.pane_dead == "0"


def test_new_window_reuse_keeps_large_native_arguments(session: Session) -> None:
    """Receipt overhead must not reject an otherwise valid native command."""
    expected = session.new_window(window_name="logs", window_shell="exec /bin/cat")
    reused = session.new_window(
        window_name="logs", window_shell="x" * 12000, select_existing=True
    )
    assert reused.window_id == expected.window_id


def test_new_window_creation_keeps_custom_dispatch(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordinary creation keeps its existing dispatcher and successful ID output."""
    native = session.server.cmd
    calls: list[tuple[t.Any, ...]] = []

    def dispatch(*args: t.Any, **kwargs: t.Any) -> common.tmux_cmd:
        calls.append(args)
        return native(*args, **kwargs)

    monkeypatch.setattr(session.server, "cmd", dispatch)
    created = session.new_window(window_name="routed", window_shell="exec /bin/cat")
    assert created.server is session.server
    assert created.window_name == "routed"
    pane = created.active_pane
    assert pane is not None and pane.pane_dead == "0"
    assert calls and calls[0][0] == "new-window"


@pytest.mark.parametrize(
    "attribute", ["session-cmd", "server-cmd", "engine", "_engine"]
)
def test_new_window_reuse_refuses_unknown_backend_before_effects(
    session: Session, monkeypatch: pytest.MonkeyPatch, attribute: str
) -> None:
    """Unknown routing must not silently become a stock native receipt."""
    before = {window.window_id for window in session.windows}
    calls: list[tuple[t.Any, ...]] = []
    native = session.server.cmd if attribute == "server-cmd" else session.cmd

    def dispatch(*args: t.Any, **kwargs: t.Any) -> common.tmux_cmd:
        calls.append(args)
        return native(*args, **kwargs)

    if attribute.endswith("cmd"):
        context = session if attribute == "session-cmd" else session.server
        monkeypatch.setattr(context, "cmd", dispatch)
    else:
        monkeypatch.setattr(session.server, attribute, object(), raising=False)
    with pytest.raises(exc.LibTmuxException, match="Window reuse receipts"):
        session.new_window(window_name="not-submitted", select_existing=True)
    assert calls == []
    assert {window.window_id for window in session.windows} == before


def test_new_window_reuse_preserves_ambiguity(session: Session) -> None:
    """Native duplicate-name errors remain visible and preserve both windows."""
    first = session.new_window(window_name="duplicate")
    second = session.new_window(window_name="duplicate")
    before = {window.window_id for window in session.windows}

    with pytest.raises(exc.LibTmuxException, match="multiple windows named duplicate"):
        session.new_window(window_name="duplicate", select_existing=True)

    assert {window.window_id for window in session.windows} == before
    assert first.window_id != second.window_id

    with pytest.raises(exc.LibTmuxException, match="can't find window"):
        session.new_window(target_window="@999999", select_existing=True)
    assert {window.window_id for window in session.windows} == before


def test_session_last_window_exception_tags_subcommand(session: Session) -> None:
    """Wrapper raises tag LibTmuxException with the originating tmux subcommand.

    Calling ``last_window()`` on a session with only one window and no prior
    selection makes tmux error. The raised exception carries
    ``.subcommand == "last-window"`` and ``str(exc)`` prefixes the
    subcommand so downstream consumers see which tmux command failed.
    """
    with pytest.raises(exc.LibTmuxException) as excinfo:
        session.last_window()
    assert excinfo.value.subcommand == "last-window"
    assert str(excinfo.value).startswith("last-window:")


def test_session_search_windows_filter(session: Session) -> None:
    """``Session.search_windows(filter=...)`` filters via tmux's native -f flag."""
    session.new_window(window_name="gap7s_keep")
    session.new_window(window_name="other_drop")

    matches = session.search_windows(filter="#{m:gap7s_*,#{window_name}}")
    names = sorted(w.window_name for w in matches if w.window_name)
    assert names == ["gap7s_keep"]


def test_session_search_panes_filter_by_id(session: Session) -> None:
    """``Session.search_panes(filter=...)`` returns only matching pane ids."""
    window = session.active_window
    target = window.split()

    matches = session.search_panes(
        filter=f"#{{m:{target.pane_id},#{{pane_id}}}}",
    )
    assert [p.pane_id for p in matches] == [target.pane_id]


SESSION_FORMAT_FIELDS = (
    "session_format",
    "session_group_attached_list",
    "session_group_many_attached",
    "session_grouped",
    "session_many_attached",
    "session_marked",
)


@pytest.mark.parametrize("field_name", SESSION_FORMAT_FIELDS)
def test_session_format_field_declared_and_hydrated(
    field_name: str,
    session: Session,
) -> None:
    """Tmux's session-scope format tokens hydrate onto the typed ``Session``."""
    assert field_name in session.__dataclass_fields__

    session.refresh()
    value = getattr(session, field_name)
    assert value is None or isinstance(value, str)


SESSION_SCOPE_OVERRIDE_FIELDS = (
    "active_window_index",
    "last_window_index",
)


@pytest.mark.parametrize("field_name", SESSION_SCOPE_OVERRIDE_FIELDS)
def test_session_scope_override_field_hydrates(
    field_name: str,
    session: Session,
) -> None:
    """Session-scope overrides admit each token into list-sessions -F.

    Callbacks dereference ``ft->s`` in tmux's ``format.c`` (verified
    across tmux 3.2a through master). A ``None`` here indicates the
    scope gate excluded the token from the format string, which is
    the regression class these overrides prevent.
    """
    session.refresh()
    value = getattr(session, field_name)
    assert value is not None, f"{field_name} should hydrate via list-sessions"
    assert isinstance(value, str)


def test_session_refresh_raises_when_session_id_is_none(server: Server) -> None:
    """``Session.refresh()`` raises ``ValueError`` when ``session_id`` is unset.

    Mirrors the Client.refresh ``-O``-safe contract: the previous
    ``assert isinstance(...)`` stripped under ``python -O`` and let
    ``None`` flow into ``_refresh``. The explicit raise keeps the
    failure mode loud regardless of optimization level.
    """
    session = Session(server=server)
    assert session.session_id is None

    with pytest.raises(ValueError, match="session_id"):
        session.refresh()


def test_kill_session_group(server: Server) -> None:
    """Session.kill(group=True) uses -g on tmux 3.7+; warn-and-ignore below."""
    from libtmux.common import has_gte_version

    session = server.new_session(session_name="kill_group_base")

    if has_gte_version("3.7"):
        session.kill(group=True)
        assert not server.has_session("kill_group_base")
    else:
        with pytest.warns(UserWarning, match="group requires tmux 3.7"):
            session.kill(group=True)
