"""Test for libtmux Session object."""
import logging
import shutil
import typing as t

import pytest

from libtmux import exc
from libtmux.common import has_gte_version, has_lt_version
from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.session import Session
from libtmux.test import TEST_SESSION_PREFIX, namer
from libtmux.window import Window

logger = logging.getLogger(__name__)


def test_has_session(server: Server, session: Session) -> None:
    """Server.has_session returns True if has session_name exists."""
    TEST_SESSION_NAME = session.get("session_name")
    assert TEST_SESSION_NAME is not None
    assert server.has_session(TEST_SESSION_NAME)
    if has_gte_version("2.1"):
        assert not server.has_session(TEST_SESSION_NAME[:-2])
        assert server.has_session(TEST_SESSION_NAME[:-2], exact=False)
    assert not server.has_session("asdf2314324321")


def test_select_window(session: Session) -> None:
    """Session.select_window moves window."""
    # get the current window_base_index, since different user tmux config
    # may start at 0 or 1, or whatever they want.
    window_idx = session.attached_window.get("window_index")
    assert window_idx is not None
    window_base_index = int(window_idx)

    session.new_window(window_name="test_window")
    window_count = len(session._windows)

    assert window_count >= 2  # 2 or more windows

    assert len(session._windows) == window_count

    # tmux selects a window, moves to it, shows it as attached_window
    selected_window1 = session.select_window(window_base_index)
    assert isinstance(selected_window1, Window)
    attached_window1 = session.attached_window

    assert selected_window1 == attached_window1
    assert selected_window1.__dict__ == attached_window1.__dict__

    # again: tmux selects a window, moves to it, shows it as
    # attached_window
    selected_window2 = session.select_window(window_base_index + 1)
    assert isinstance(selected_window2, Window)
    attached_window2 = session.attached_window

    assert selected_window2 == attached_window2
    assert selected_window2.__dict__ == attached_window2.__dict__

    # assure these windows were really different
    assert selected_window1 != selected_window2
    assert selected_window1.__dict__ != selected_window2.__dict__


def test_select_window_returns_Window(session: Session) -> None:
    """Session.select_window returns Window object."""

    window_count = len(session._windows)
    assert len(session._windows) == window_count

    window_idx = session.attached_window.get("window_index")
    assert window_idx is not None
    window_base_index = int(window_idx)
    window = session.select_window(window_base_index)
    assert isinstance(window, Window)


def test_attached_window(session: Session) -> None:
    """Session.attached_window returns Window."""
    assert isinstance(session.attached_window, Window)


def test_attached_pane(session: Session) -> None:
    """Session.attached_pane returns Pane."""
    assert isinstance(session.attached_pane, Pane)


def test_session_rename(session: Session) -> None:
    """Session.rename_session renames session."""
    session_name = session.get("session_name")
    assert session_name is not None
    TEST_SESSION_NAME = session_name

    test_name = "testingdis_sessname"
    session.rename_session(test_name)
    session_name = session.get("session_name")
    assert session_name is not None
    assert session_name == test_name
    session.rename_session(TEST_SESSION_NAME)
    session_name = session.get("session_name")
    assert session_name is not None
    assert session_name == TEST_SESSION_NAME


def test_new_session(server: Server) -> None:
    """Server.new_session creates new session."""
    new_session_name = TEST_SESSION_PREFIX + next(namer)
    new_session = server.new_session(session_name=new_session_name, detach=True)

    assert isinstance(new_session, Session)
    assert new_session.get("session_name") == new_session_name


def test_show_options(session: Session) -> None:
    """Session.show_options() returns dict."""

    options = session.show_options()
    assert isinstance(options, dict)


def test_set_show_options_single(session: Session) -> None:
    """Set option then Session.show_options(key)."""

    session.set_option("history-limit", 20)
    assert session.show_option("history-limit") == 20

    session.set_option("history-limit", 40)
    assert session.show_option("history-limit") == 40

    assert session.show_options()["history-limit"] == 40


def test_set_show_option(session: Session) -> None:
    """Set option then Session.show_option(key)."""
    session.set_option("history-limit", 20)
    assert session.show_option("history-limit") == 20

    session.set_option("history-limit", 40)

    assert session.show_option("history-limit") == 40


def test_empty_session_option_returns_None(session: Session) -> None:
    assert session.show_option("default-shell") is None


def test_show_option_unknown(session: Session) -> None:
    """Session.show_option raises UnknownOption for invalid option."""
    cmd_exception: t.Type[exc.OptionError] = exc.UnknownOption
    if has_gte_version("3.0"):
        cmd_exception = exc.InvalidOption
    with pytest.raises(cmd_exception):
        session.show_option("moooz")


def test_show_option_ambiguous(session: Session) -> None:
    """Session.show_option raises AmbiguousOption for ambiguous option."""
    with pytest.raises(exc.AmbiguousOption):
        session.show_option("default-")


def test_set_option_ambigous(session: Session) -> None:
    """Session.set_option raises AmbiguousOption for invalid option."""
    with pytest.raises(exc.AmbiguousOption):
        session.set_option("default-", 43)


def test_set_option_invalid(session: Session) -> None:
    """Session.set_option raises UnknownOption for invalid option."""
    if has_gte_version("2.4"):
        with pytest.raises(exc.InvalidOption):
            session.set_option("afewewfew", 43)
    else:
        with pytest.raises(exc.UnknownOption):
            session.set_option("afewewfew", 43)


def test_show_environment(session: Session) -> None:
    """Session.show_environment() returns dict."""

    _vars = session.show_environment()
    assert isinstance(_vars, dict)


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


@pytest.mark.parametrize(
    "session_name,raises",
    [("hey.period", True), ("hey:its a colon", True), ("hey moo", False)],
)
def test_periods_raise_badsessionname(
    server: Server, session: Session, session_name: str, raises: bool
) -> None:
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


def test_cmd_inserts_sesion_id(session: Session) -> None:
    current_session_id = session.id
    last_arg = "last-arg"
    cmd = session.cmd("not-a-command", last_arg)
    assert "-t" in cmd.cmd
    assert current_session_id in cmd.cmd
    assert cmd.cmd[-1] == last_arg


@pytest.mark.skipif(
    has_lt_version("3.0"),
    reason="needs -e flag for new-window which was introduced in 3.0",
)
@pytest.mark.parametrize(
    "environment",
    [
        {"ENV_VAR": "window"},
        {"ENV_VAR_1": "window_1", "ENV_VAR_2": "window_2"},
    ],
)
def test_new_window_with_environment(
    session: Session,
    environment: t.Dict[str, str],
) -> None:
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        attach=True,
        window_name="window_with_environment",
        window_shell=f"{env} PS1='$ ' sh",
        environment=environment,
    )
    pane = window.attached_pane
    assert pane is not None
    for k, v in environment.items():
        pane.send_keys(f"echo ${k}")
        assert pane.capture_pane()[-2] == v


@pytest.mark.skipif(
    has_gte_version("3.0"),
    reason="3.0 has the -e flag on new-window",
)
def test_new_window_with_environment_logs_warning_for_old_tmux(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="window_with_environment",
        window_shell=f"{env} PS1='$ ' sh",
        environment={"ENV_VAR": "window"},
    )

    assert any(
        "Cannot set up environment" in record.msg for record in caplog.records
    ), "Warning missing"
