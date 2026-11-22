"""Tests for :class:`libtmux.Format` and literal names, titles and directories."""

from __future__ import annotations

import typing as t

import pytest

from libtmux import Format
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
