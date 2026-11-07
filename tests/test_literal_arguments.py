r"""Typed entry points deliver values that end in ``;`` to tmux literally.

tmux splits an argument list into commands at an argument that ends in
``;`` and unescapes a trailing ``\;`` to a literal ``;``. These tests run
each typed entry point against a real private server with values that
exercise both rules.
"""

from __future__ import annotations

import contextlib
import pathlib
import typing as t

import pytest

from libtmux import exc
from libtmux.common import escape_trailing_separator, has_gte_version
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session

# A value ending in ";", a value ending in the escaped form, a lone ";" and
# a value whose last two characters are both separators.
VALUES = ["v;", "v\\;", ";", "v;;"]


def shown(value: str) -> str:
    """Return ``value`` as tmux prints it in a format result.

    tmux 3.8 doubles backslashes in format output.
    """
    if has_gte_version("3.8"):
        return value.replace("\\", "\\\\")
    return value


def start_command(pane: Pane) -> str:
    """Return the command a pane was started with, without tmux's quoting."""
    out = pane.display_message("#{pane_start_command}", get_text=True)
    return out[0].strip('"')


class EscapeFixture(t.NamedTuple):
    """Input and expected argument for :func:`escape_trailing_separator`."""

    test_id: str
    value: str
    expected: str


ESCAPE_FIXTURES = [
    EscapeFixture("plain", "abc", "abc"),
    EscapeFixture("empty", "", ""),
    EscapeFixture("inner_separator", "a;b", "a;b"),
    EscapeFixture("trailing", "abc;", "abc\\;"),
    EscapeFixture("lone", ";", "\\;"),
    EscapeFixture("already_escaped", "abc\\;", "abc\\\\;"),
    EscapeFixture("double", ";;", ";\\;"),
]


@pytest.mark.parametrize(
    list(EscapeFixture._fields),
    ESCAPE_FIXTURES,
    ids=[f.test_id for f in ESCAPE_FIXTURES],
)
def test_escape_trailing_separator(
    test_id: str,
    value: str,
    expected: str,
) -> None:
    """Only the final ``;`` of an argument gets a backslash."""
    assert escape_trailing_separator(value) == expected


def test_raw_cmd_keeps_separator(server: Server, session: Session) -> None:
    """``Server.cmd`` passes a bare ``;`` through as a tmux command separator."""
    proc = server.cmd(
        "display-message",
        "-p",
        "first",
        ";",
        "display-message",
        "-p",
        "second",
    )
    assert proc.stdout == ["first", "second"]


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize("scope", ["server", "session", "window", "pane"])
def test_set_option_value(
    server: Server,
    session: Session,
    scope: str,
    value: str,
) -> None:
    """``set_option`` stores the value as given at every scope."""
    obj: t.Any = {
        "server": server,
        "session": session,
        "window": session.active_window,
        "pane": session.active_pane,
    }[scope]
    obj.set_option("@semi", value)
    assert server.is_alive()
    assert obj.show_option("@semi") == value


@pytest.mark.parametrize("scope", ["server", "session", "window", "pane"])
def test_set_option_name_is_data(
    server: Server,
    session: Session,
    scope: str,
) -> None:
    """An option name ending in ``;`` is rejected; the next argument is not run."""
    obj: t.Any = {
        "server": server,
        "session": session,
        "window": session.active_window,
        "pane": session.active_pane,
    }[scope]
    with pytest.raises(exc.OptionError):
        obj.set_option("mouse;", "kill-server", global_=True)
    assert server.is_alive()


def test_set_option_status_left(server: Server, session: Session) -> None:
    """A built-in free-text option keeps its trailing ``;``."""
    session.set_option("status-left", "left;")
    assert session.show_option("status-left") == "left;"


@pytest.mark.parametrize("value", VALUES)
def test_set_environment_value(
    server: Server,
    session: Session,
    value: str,
) -> None:
    """``set_environment`` stores the value as given."""
    server.set_environment("EXAMPLE_VAR", value)
    session.set_environment("EXAMPLE_SESSION_VAR", value)
    assert server.getenv("EXAMPLE_VAR") == value
    assert session.getenv("EXAMPLE_SESSION_VAR") == value


def test_set_environment_name_is_data(server: Server, session: Session) -> None:
    """A name ending in ``;`` does not run the value as a command."""
    with contextlib.suppress(ValueError):
        server.set_environment("X;", "kill-server")
    assert server.is_alive()


@pytest.mark.parametrize("value", VALUES)
def test_new_session_environment(server: Server, value: str) -> None:
    """``new_session(environment=...)`` stores the value as given."""
    new = server.new_session(
        session_name="env_case",
        environment={"K": value},
        window_command="sleep 30",
    )
    assert server.is_alive()
    assert new.getenv("K") == value


@pytest.mark.parametrize("value", VALUES)
def test_new_session_window_name(server: Server, value: str) -> None:
    """``new_session(window_name=...)`` names the window as given."""
    new = server.new_session(
        session_name="name_case",
        window_name=value,
        window_command="sleep 30",
    )
    assert server.is_alive()
    assert new.active_window.window_name == shown(value)


def test_new_session_start_directory(server: Server, tmp_path: pathlib.Path) -> None:
    """``new_session(start_directory=...)`` accepts a directory ending in ``;``."""
    directory = tmp_path / "dir;"
    directory.mkdir()
    new = server.new_session(
        session_name="dir_case",
        start_directory=directory,
        window_command="sleep 30",
    )
    assert server.is_alive()
    pane = new.active_pane
    assert pane is not None
    assert retry_until(
        lambda: (
            pane.display_message("#{pane_current_path}", get_text=True)
            == [str(directory)]
        ),
        raises=False,
    )


@pytest.mark.parametrize("value", VALUES)
def test_new_session_session_name(server: Server, value: str) -> None:
    """``new_session(session_name=...)`` names the session as given."""
    new = server.new_session(session_name=f"s{value}", window_command="sleep 30")
    assert server.is_alive()
    assert new.session_name == shown(f"s{value}")


def test_new_session_window_command(server: Server) -> None:
    """``new_session(window_command=...)`` runs a command ending in ``;``."""
    new = server.new_session(session_name="cmd_case", window_command="sleep 30;")
    assert server.is_alive()
    pane = new.active_pane
    assert pane is not None
    assert start_command(pane) == "sleep 30;"


@pytest.mark.parametrize("value", VALUES)
def test_new_window_window_name(session: Session, value: str) -> None:
    """``Session.new_window(window_name=...)`` names the window as given."""
    window = session.new_window(window_name=value, window_shell="sleep 30")
    assert session.server.is_alive()
    assert window.window_name == shown(value)


@pytest.mark.parametrize("value", VALUES)
def test_new_window_environment(
    session: Session,
    tmp_path: pathlib.Path,
    value: str,
) -> None:
    """``Session.new_window(environment=...)`` reaches the window's process."""
    out = tmp_path / "out"
    session.new_window(
        environment={"K": value},
        window_shell=f'printf %s "$K" > {out}; sleep 30',
    )
    assert session.server.is_alive()
    assert retry_until(lambda: out.exists() and out.read_text() == value)


def test_new_window_start_directory(
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """``Session.new_window(start_directory=...)`` accepts a ``;`` suffix."""
    directory = tmp_path / "dir;"
    directory.mkdir()
    window = session.new_window(start_directory=directory, window_shell="sleep 30")
    pane = window.active_pane
    assert pane is not None
    assert session.server.is_alive()
    assert retry_until(
        lambda: (
            pane.display_message("#{pane_current_path}", get_text=True)
            == [str(directory)]
        ),
        raises=False,
    )


@pytest.mark.parametrize("value", VALUES)
def test_split_environment(
    session: Session,
    tmp_path: pathlib.Path,
    value: str,
) -> None:
    """``Pane.split(environment=...)`` reaches the pane's process."""
    out = tmp_path / "out"
    pane = session.active_pane
    assert pane is not None
    pane.split(
        environment={"K": value},
        shell=f'printf %s "$K" > {out}; sleep 30',
    )
    assert session.server.is_alive()
    assert retry_until(lambda: out.exists() and out.read_text() == value)


def test_split_start_directory(session: Session, tmp_path: pathlib.Path) -> None:
    """``Pane.split(start_directory=...)`` accepts a directory ending in ``;``."""
    directory = tmp_path / "dir;"
    directory.mkdir()
    pane = session.active_pane
    assert pane is not None
    new = pane.split(start_directory=directory, shell="sleep 30")
    assert session.server.is_alive()
    assert retry_until(
        lambda: (
            new.display_message("#{pane_current_path}", get_text=True)
            == [str(directory)]
        ),
        raises=False,
    )


def test_split_shell(session: Session) -> None:
    """``Pane.split(shell=...)`` runs a command ending in ``;``."""
    pane = session.active_pane
    assert pane is not None
    new = pane.split(shell="sleep 30;")
    assert session.server.is_alive()
    assert start_command(new) == "sleep 30;"


@pytest.mark.parametrize("value", VALUES)
def test_pane_respawn_environment(
    session: Session,
    tmp_path: pathlib.Path,
    value: str,
) -> None:
    """``Pane.respawn(environment=...)`` reaches the respawned process."""
    out = tmp_path / "out"
    pane = session.active_pane
    assert pane is not None
    pane.respawn(
        kill=True,
        environment={"K": value},
        shell=f'printf %s "$K" > {out}; sleep 30',
    )
    assert session.server.is_alive()
    assert retry_until(lambda: out.exists() and out.read_text() == value)


@pytest.mark.parametrize("value", VALUES)
def test_window_respawn_environment(
    session: Session,
    tmp_path: pathlib.Path,
    value: str,
) -> None:
    """``Window.respawn(environment=...)`` reaches the respawned process."""
    out = tmp_path / "out"
    session.active_window.respawn(
        kill=True,
        environment={"K": value},
        shell=f'printf %s "$K" > {out}; sleep 30',
    )
    assert session.server.is_alive()
    assert retry_until(lambda: out.exists() and out.read_text() == value)


@pytest.mark.skipif(
    not has_gte_version("3.7"),
    reason="floating panes need tmux 3.7+",
)
@pytest.mark.parametrize("value", VALUES)
def test_new_pane_environment(
    session: Session,
    tmp_path: pathlib.Path,
    value: str,
) -> None:
    """``Pane.new_pane(environment=...)`` reaches the floating pane's process."""
    out = tmp_path / "out"
    pane = session.active_pane
    assert pane is not None
    pane.new_pane(
        environment={"K": value},
        shell=f'printf %s "$K" > {out}; sleep 30',
    )
    assert session.server.is_alive()
    assert retry_until(lambda: out.exists() and out.read_text() == value)


@pytest.mark.parametrize("literal", [True, False])
@pytest.mark.parametrize("value", ["abc;", "abc\\;", ";"])
def test_send_keys(session: Session, value: str, literal: bool) -> None:
    """``Pane.send_keys`` delivers the final ``;`` to the pane."""
    pane = session.active_pane
    assert pane is not None
    pane.send_keys(f"{value}", enter=False, literal=literal)
    assert session.server.is_alive()
    expected = value
    assert retry_until(
        lambda: any(line.rstrip().endswith(expected) for line in pane.capture_pane()),
        raises=False,
    )


@pytest.mark.parametrize("value", VALUES)
def test_rename_window(session: Session, value: str) -> None:
    """``Window.rename_window`` names the window as given."""
    window = session.active_window
    window.rename_window(value)
    assert session.server.is_alive()
    window.refresh()
    assert window.window_name == shown(value)


@pytest.mark.parametrize("value", VALUES)
def test_rename_session(session: Session, value: str) -> None:
    """``Session.rename_session`` names the session as given."""
    session.rename_session(f"r{value}")
    assert session.server.is_alive()
    assert session.session_name == shown(f"r{value}")


@pytest.mark.parametrize("value", VALUES)
def test_set_title(session: Session, value: str) -> None:
    """``Pane.set_title`` sets the title as given."""
    pane = session.active_pane
    assert pane is not None
    pane.set_title(value)
    assert session.server.is_alive()
    assert pane.pane_title == shown(value)


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize("scope", ["server", "window", "pane"])
def test_display_message(
    server: Server,
    session: Session,
    scope: str,
    value: str,
) -> None:
    """``display_message(get_text=True)`` returns the message as given."""
    obj: t.Any = {
        "server": server,
        "window": session.active_window,
        "pane": session.active_pane,
    }[scope]
    assert obj.display_message(value, get_text=True, no_expand=False) == [value]
    assert server.is_alive()


@pytest.mark.parametrize("scope", ["server", "window", "pane"])
def test_display_message_format_string(
    server: Server,
    session: Session,
    scope: str,
) -> None:
    """``format_string`` ending in ``;`` is delivered literally."""
    obj: t.Any = {
        "server": server,
        "window": session.active_window,
        "pane": session.active_pane,
    }[scope]
    assert obj.display_message("", get_text=True, format_string="f;") == ["f;"]
    assert server.is_alive()


def expected_argument(value: str) -> str:
    """Return the argument tmux needs to read ``value`` back as data."""
    return value[:-1] + "\\;" if value.endswith(";") else value


class CapturedCmd(t.NamedTuple):
    """Arguments of the one command a method sent through ``cmd()``."""

    name: str
    args: tuple[t.Any, ...]


def capture_cmd(
    monkeypatch: pytest.MonkeyPatch,
    obj: t.Any,
    command: str,
) -> list[CapturedCmd]:
    """Record calls to ``command`` on ``obj`` instead of sending them to tmux."""
    captured: list[CapturedCmd] = []
    real_cmd = obj.cmd

    class _Result:
        stderr: t.ClassVar[list[str]] = []
        stdout: t.ClassVar[list[str]] = []
        returncode = 0

    def fake_cmd(name: str, *args: t.Any, **kwargs: t.Any) -> t.Any:
        if name == command:
            captured.append(CapturedCmd(name, args))
            return _Result()
        return real_cmd(name, *args, **kwargs)

    monkeypatch.setattr(obj, "cmd", fake_cmd)
    return captured


def flag_value(args: tuple[t.Any, ...], flag: str) -> str:
    """Return the argument that follows ``flag``."""
    return str(args[args.index(flag) + 1])


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize(
    ("kwarg", "flag"),
    [
        ("title", "-T"),
        ("border_lines", "-b"),
        ("style", "-s"),
        ("border_style", "-S"),
        ("start_directory", "-d"),
        ("command", ""),
    ],
)
def test_display_popup_arguments(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    kwarg: str,
    flag: str,
    value: str,
) -> None:
    """``Pane.display_popup`` escapes each free-text value.

    A popup needs a terminal client, so the argument vector is captured.
    """
    pane = session.active_pane
    assert pane is not None
    captured = capture_cmd(monkeypatch, pane, "display-popup")
    popup_kwargs: dict[str, t.Any] = {kwarg: value}
    pane.display_popup(**popup_kwargs)
    (call,) = captured
    sent = str(call.args[-1]) if not flag else flag_value(call.args, flag)
    if kwarg == "start_directory":
        sent = sent.replace(str(pathlib.Path(value).expanduser()), value)
    assert sent == expected_argument(value)


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize(
    ("kwarg", "flag"),
    [
        ("title", "-T"),
        ("border_lines", "-b"),
        ("style", "-s"),
        ("border_style", "-S"),
        ("selected_style", "-H"),
    ],
)
def test_display_menu_arguments(
    monkeypatch: pytest.MonkeyPatch,
    server: Server,
    kwarg: str,
    flag: str,
    value: str,
) -> None:
    """``Server.display_menu`` escapes each free-text value."""
    captured = capture_cmd(monkeypatch, server, "display-menu")
    menu_kwargs: dict[str, t.Any] = {kwarg: value}
    server.display_menu("name", "k", "display-message x", **menu_kwargs)
    (call,) = captured
    assert flag_value(call.args, flag) == expected_argument(value)


@pytest.mark.parametrize("value", VALUES)
def test_display_menu_items(
    monkeypatch: pytest.MonkeyPatch,
    server: Server,
    value: str,
) -> None:
    """Item names and keys are escaped; the item command is left as given."""
    captured = capture_cmd(monkeypatch, server, "display-menu")
    server.display_menu(value, value, "display-message x;")
    (call,) = captured
    assert call.args == (
        expected_argument(value),
        expected_argument(value),
        "display-message x;",
    )


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize(
    ("kwarg", "flag"),
    [
        ("style", "-s"),
        ("active_border_style", "-S"),
        ("inactive_border_style", "-R"),
        ("message", "-m"),
    ],
)
def test_new_pane_arguments(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    kwarg: str,
    flag: str,
    value: str,
) -> None:
    """``Pane.new_pane`` escapes each free-text value."""
    if not has_gte_version("3.7"):
        pytest.skip("floating panes need tmux 3.7+")
    pane = session.active_pane
    assert pane is not None
    new_pane_kwargs: dict[str, t.Any] = {kwarg: value}
    captured = capture_cmd(monkeypatch, pane, "new-pane")
    with contextlib.suppress(Exception):
        pane.new_pane(**new_pane_kwargs)
    (call,) = captured
    assert flag_value(call.args, flag) == expected_argument(value)


def test_new_pane_message_real(session: Session) -> None:
    """A floating pane message ending in ``;`` does not chain a command."""
    if not has_gte_version("3.7"):
        pytest.skip("floating panes need tmux 3.7+")
    pane = session.active_pane
    assert pane is not None
    pane.new_pane(message="m;", shell="sleep 30")
    assert session.server.is_alive()
