"""Tests for :class:`libtmux.Format` and literal names, titles and directories."""

from __future__ import annotations

import typing as t

import pytest

from libtmux import Format, exc
from libtmux.common import has_gte_version
from libtmux.constants import WindowDirection
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    import pathlib

    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session

# Values tmux would rewrite as formats: ``#[`` is kept as a style when its
# ``#`` is doubled, so it needs the character-code escape.
LITERAL_VALUES = ["a#[b", "#S", "build#2", "end#", "##"]


@pytest.mark.parametrize("value", LITERAL_VALUES)
def test_str_name_and_title_are_literal(session: Session, value: str) -> None:
    """A plain ``str`` window name and pane title are stored as typed."""
    window = session.active_window
    window.rename_window(value)
    assert window.window_name == value

    pane = window.active_pane
    assert pane is not None
    pane.set_title(value)
    assert pane.pane_title == value


@pytest.mark.parametrize("value", LITERAL_VALUES)
def test_str_session_name_is_literal(server: Server, value: str) -> None:
    """A plain ``str`` session name is stored as typed."""
    session = server.new_session(session_name=value)
    assert session.session_name == value


def _has_cwd(pane: Pane) -> bool:
    pane.refresh()
    return bool(pane.pane_current_path)


def _same_cwd(source: Pane, other: Pane) -> bool:
    source.refresh()
    other.refresh()
    return bool(source.pane_current_path) and (
        other.pane_current_path == source.pane_current_path
    )


def test_split_start_directory_format(
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """A :class:`Format` start directory is expanded by tmux."""
    # tmux expands -c against the session's active pane, so make it active.
    window = session.new_window(start_directory=tmp_path, attach=True)
    source = window.active_pane
    assert source is not None

    new = source.split(start_directory=Format("#{pane_current_path}"))

    assert retry_until(lambda: _same_cwd(source, new))


def test_new_window_mixes_literal_and_format(
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """One call keeps a ``str`` name literal and expands a :class:`Format`."""
    window = session.new_window(start_directory=tmp_path, attach=True)
    source = window.active_pane
    assert source is not None

    new = session.new_window(
        window_name="w#1",
        start_directory=Format("#{pane_current_path}"),
    )

    assert new.window_name == "w#1"
    pane = new.active_pane
    assert pane is not None
    assert retry_until(lambda: _same_cwd(source, pane))


class ComposeFixture(t.NamedTuple):
    """A format built around user text, and the name tmux should store."""

    test_id: str
    build: t.Callable[[str], Format]
    expected: t.Callable[[str], str]


COMPOSE_FIXTURES: list[ComposeFixture] = [
    ComposeFixture(
        test_id="format_plus_str",
        build=lambda text: Format("#{session_name}-") + text,
        expected=lambda name: f"{name}-x#S",
    ),
    ComposeFixture(
        test_id="str_plus_format",
        build=lambda text: text + Format("-#{session_name}"),
        expected=lambda name: f"x#S-{name}",
    ),
    ComposeFixture(
        test_id="join",
        build=lambda text: Format("-").join([Format("#{session_name}"), text]),
        expected=lambda name: f"{name}-x#S",
    ),
    ComposeFixture(
        test_id="escape",
        build=lambda text: Format("#{session_name}-") + Format.escape(text),
        expected=lambda name: f"{name}-x#S",
    ),
]


@pytest.mark.parametrize(
    list(ComposeFixture._fields),
    COMPOSE_FIXTURES,
    ids=[fixture.test_id for fixture in COMPOSE_FIXTURES],
)
def test_composed_format_keeps_text_literal(
    session: Session,
    test_id: str,
    build: t.Callable[[str], Format],
    expected: t.Callable[[str], str],
) -> None:
    """User text combined with a :class:`Format` stays literal."""
    window = session.active_window
    window.rename_window(build("x#S"))
    assert window.window_name == expected(str(session.session_name))


def test_session_name_format(server: Server) -> None:
    """A :class:`Format` session name is expanded by tmux, as is a rename."""
    # The session does not exist yet while new-session expands its name, so
    # use a server-wide format.
    session = server.new_session(session_name=Format("run-#{pid}"))
    pid = server.cmd("display-message", "-p", "#{pid}").stdout[0]
    assert session.session_name == f"run-{pid}"

    session.rename_session(Format("#{session_id}") + "#x")
    assert session.session_name == f"{session.session_id}#x"


class UnfinishedFixture(t.NamedTuple):
    """A format that ends where tmux would read added text as syntax."""

    test_id: str
    build: t.Callable[[], Format]


UNFINISHED_FIXTURES: list[UnfinishedFixture] = [
    UnfinishedFixture("lone_hash_alias", lambda: Format("#{session_name}#") + "S"),
    UnfinishedFixture("lone_hash_brace", lambda: Format("#") + "{session_name}"),
    UnfinishedFixture("inside_conditional", lambda: Format("#{?pane_active,") + "x,y"),
    UnfinishedFixture("inside_command", lambda: Format("#(echo ") + "x"),
    UnfinishedFixture(
        "join_inside_conditional",
        lambda: Format("#{?pane_active,").join(["a", "b"]),
    ),
]


@pytest.mark.parametrize(
    list(UnfinishedFixture._fields),
    UNFINISHED_FIXTURES,
    ids=[fixture.test_id for fixture in UNFINISHED_FIXTURES],
)
def test_plain_text_after_unfinished_format_raises(
    test_id: str,
    build: t.Callable[[], Format],
) -> None:
    """Plain text cannot be added where tmux would read it as format syntax."""
    with pytest.raises(ValueError, match="cannot add plain text"):
        build()


def test_escape_is_literal_inside_expressions(session: Session) -> None:
    """``Format.escape`` text stays literal in a comparison and a time format."""
    text = "50%d a,b}c#S"
    window = session.active_window
    window.rename_window(text)
    pane = window.active_pane
    assert pane is not None

    shown = pane.display_message(Format.escape(text), get_text=True)
    assert shown == [text]

    same = Format("#{==:#{window_name},") + Format.escape(text) + Format("}")
    assert pane.display_message(same, get_text=True) == ["1"]


def test_always_expanded_command_keeps_added_text_literal(server: Server) -> None:
    """Text added to a ``run_shell`` command format reaches the shell as typed."""
    # tmux <3.5 does not write run-shell stdout back to the cmdq subprocess.
    if not has_gte_version("3.5"):
        pytest.skip("run-shell stdout passthrough requires tmux 3.5+")
    server.new_session()
    output = server.run_shell(Format("echo ") + "a#S%d")
    assert output == ["a#S%d"]


def test_new_session_refuses_format_with_kill_session(server: Server) -> None:
    """``kill_session=True`` needs a name known before tmux creates the session."""
    with pytest.raises(ValueError, match="kill_session=True needs a plain"):
        server.new_session(session_name=Format("#{pid}"), kill_session=True)


def test_run_shell_cwd(session: Session, tmp_path: pathlib.Path) -> None:
    """A ``#`` directory is literal; a ``Format`` directory needs tmux 3.8."""
    # tmux <3.5 does not write run-shell stdout back to the cmdq subprocess.
    if not has_gte_version("3.5"):
        pytest.skip("run-shell stdout passthrough requires tmux 3.5+")
    directory = tmp_path / "d#S"
    directory.mkdir()
    server = session.server

    assert server.run_shell("pwd", cwd=directory) == [str(directory)]

    window = session.new_window(start_directory=directory, attach=True)
    source = window.active_pane
    assert source is not None
    assert retry_until(lambda: _has_cwd(source))
    if has_gte_version("3.8"):
        output = server.run_shell("pwd", cwd=Format("#{pane_current_path}"))
        assert output == [str(directory)]
    else:
        with pytest.raises(exc.LibTmuxException, match=r"requires tmux 3\.8"):
            server.run_shell("pwd", cwd=Format("#{pane_current_path}"))


def test_buffer_paths(server: Server, tmp_path: pathlib.Path) -> None:
    """A ``#`` in a buffer file path is literal; ``load_buffer`` takes a Format."""
    session = server.new_session(session_name="buf")
    server.set_buffer("saved")
    target = tmp_path / "log#S.txt"

    server.save_buffer(target)
    assert target.read_text() == "saved"

    named = tmp_path / f"{session.session_name}.txt"
    named.write_text("loaded")
    path = Format.escape(str(tmp_path)) + Format("/#{session_name}.txt")
    server.load_buffer(path, buffer_name="from_format")
    assert server.show_buffer(buffer_name="from_format") == "loaded"


def test_window_new_window_start_directory(
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """``Window.new_window`` accepts a ``Format`` start directory."""
    window = session.new_window(start_directory=tmp_path, attach=True)
    source = window.active_pane
    assert source is not None

    new = window.new_window(
        start_directory=Format("#{pane_current_path}"),
        direction=WindowDirection.After,
    )

    pane = new.active_pane
    assert pane is not None
    assert retry_until(lambda: _same_cwd(source, pane))
