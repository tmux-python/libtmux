"""Test for libtmux options management."""

from __future__ import annotations

import dataclasses
import textwrap
import typing as t

import pytest

from libtmux._internal.constants import (
    Options,
    PaneOptions,
    ServerOptions,
    SessionOptions,
    WindowOptions,
)
from libtmux._internal.sparse_array import SparseArray
from libtmux.common import has_gte_version
from libtmux.constants import OptionScope
from libtmux.exc import OptionError
from libtmux.pane import Pane

if t.TYPE_CHECKING:
    from typing_extensions import LiteralString

    from libtmux.server import Server


def test_options(server: Server) -> None:
    """Test basic options."""
    session = server.new_session(session_name="test")
    window = session.new_window(window_name="test")
    pane = window.split_window(attach=False)

    for obj in [server, session, window, pane]:
        obj._show_options()
        obj._show_options(_global=True)
        obj._show_options(include_inherited=True)
        obj._show_options(include_hooks=True)
        with pytest.raises(OptionError):
            obj._show_option("test")
        if has_gte_version("3.0"):
            obj._show_option("test", ignore_errors=True)
        with pytest.raises(OptionError):
            obj.set_option("test", "invalid")
        if isinstance(obj, Pane):
            if has_gte_version("3.0"):
                obj.set_option("test", "invalid", ignore_errors=True)
            else:
                with pytest.raises(OptionError):
                    obj.set_option("test", "invalid", ignore_errors=True)
        else:
            obj.set_option("test", "invalid", ignore_errors=True)


def test_options_server(server: Server) -> None:
    """Test server options."""
    session = server.new_session(session_name="test")
    window = session.new_window(window_name="test")
    pane = window.split_window(attach=False)

    server.set_option("buffer-limit", 100)
    assert server._show_option("buffer-limit") == 100
    if has_gte_version("3.0"):
        server.set_option("buffer-limit", 150, scope=OptionScope.Pane)

    if has_gte_version("3.0"):
        # set-option and show-options w/ Pane (-p) does not exist until 3.0+
        server.set_option(
            "buffer-limit",
            150,
            scope=OptionScope.Pane,
            ignore_errors=True,
        )
    server.set_option("buffer-limit", 150, scope=OptionScope.Server)

    if has_gte_version("3.0"):
        assert session._show_option("buffer-limit") == 150

    # Server option in deeper objects
    if has_gte_version("3.0"):
        pane.set_option("buffer-limit", 100)
    else:
        with pytest.raises(OptionError):
            pane.set_option("buffer-limit", 100)

    if has_gte_version("3.0"):
        assert pane._show_option("buffer-limit") == 100
        assert window._show_option("buffer-limit") == 100
        assert server._show_option("buffer-limit") == 100

    server_options = ServerOptions(**server._show_options(scope=OptionScope.Server))
    if has_gte_version("3.0"):
        assert server._show_option("buffer-limit") == 100

        assert server_options.buffer_limit == 100

        server.set_option("buffer-limit", 150, scope=OptionScope.Server)

        assert server._show_option("buffer-limit") == 150

        server.unset_option("buffer-limit")

        assert server._show_option("buffer-limit") == 50


def test_options_session(server: Server) -> None:
    """Test session options."""
    session = server.new_session(session_name="test")
    session.new_window(window_name="test")

    session_options_ = session._show_options(scope=OptionScope.Session)

    session_options = SessionOptions(**session_options_)
    assert session_options.default_size == session_options_.get("default-size")


def test_options_window(server: Server) -> None:
    """Test window options."""
    session = server.new_session(session_name="test")
    window = session.new_window(window_name="test")
    window.split_window(attach=False)

    window_options_ = window._show_options(scope=OptionScope.Window)

    window_options = WindowOptions(**window_options_)
    assert window_options.automatic_rename == window_options_.get("automatic-rename")


def test_options_pane(server: Server) -> None:
    """Test pane options."""
    session = server.new_session(session_name="test")
    window = session.new_window(window_name="test")
    pane = window.split_window(attach=False)

    pane_options_ = pane._show_options(scope=OptionScope.Pane)

    pane_options = PaneOptions(**pane_options_)
    assert pane_options.window_active_style == pane_options_.get("window-active-style")


def test_options_grid(server: Server) -> None:
    """Test options against grid."""
    session = server.new_session(session_name="test")
    window = session.new_window(window_name="test")
    pane = window.split_window(attach=False)

    for include_inherited in [True, False]:
        for _global in [True, False]:
            for obj in [server, session, window, pane]:
                for scope in [
                    OptionScope.Server,
                    OptionScope.Session,
                    OptionScope.Window,
                ]:
                    obj_global_options_ = obj._show_options(
                        scope=scope,
                        include_inherited=include_inherited,
                        _global=_global,
                    )
                    obj_global_options = Options(**obj_global_options_)
                    for field in dataclasses.fields(obj_global_options):
                        expected = obj_global_options_.get(field.name.replace("_", "-"))

                        if include_inherited and expected is None:
                            expected = obj_global_options_.get(
                                f"{field.name.replace('_', '-')}*",
                                None,
                            )

                        default_value = None
                        if field.default_factory is not dataclasses.MISSING:
                            default_value = field.default_factory()
                            if expected is None:
                                default_value = None
                        assert (
                            getattr(obj_global_options, field.name, default_value)
                            == expected
                        ), (
                            f"Expect {field.name} to be {expected} when "
                            + f"scope={scope}, _global={_global}"
                        )
                    if (
                        has_gte_version("3.0")
                        and scope == OptionScope.Window
                        and _global
                    ):
                        assert obj_global_options.pane_base_index == 0


def test_custom_options(
    server: Server,
) -> None:
    """Test tmux's user (custom) options."""
    session = server.new_session(session_name="test")
    session.set_option("@custom-option", "test")
    assert session._show_option("@custom-option") == "test"


MOCKED_GLOBAL_OPTIONS: list[LiteralString] = """
backspace C-?
buffer-limit 50
command-alias[0] split-pane=split-window
command-alias[1] splitp=split-window
command-alias[2] "server-info=show-messages -JT"
command-alias[3] "info=show-messages -JT"
command-alias[4] "choose-window=choose-tree -w"
command-alias[5] "choose-session=choose-tree -s"
copy-command ''
default-terminal xterm-256color
editor vim
escape-time 50
exit-empty on
exit-unattached off
extended-keys off
focus-events off
history-file ''
message-limit 1000
prompt-history-limit 100
set-clipboard external
terminal-overrides[0] xterm-256color:Tc
terminal-features[0] xterm*:clipboard:ccolour:cstyle:focus
terminal-features[1] screen*:title
user-keys
""".strip().split("\n")


@dataclasses.dataclass
class MockedCmdResponse:
    """Mocked tmux_cmd response."""

    stdout: list[LiteralString] | None
    stderr: list[str] | None


def cmd_mocked(*args: object) -> MockedCmdResponse:
    """Mock command response for show-options -s (server)."""
    return MockedCmdResponse(
        stdout=MOCKED_GLOBAL_OPTIONS,
        stderr=None,
    )


def fake_cmd(
    stdout: list[str] | None,
    stderr: list[str] | None = None,
) -> t.Callable[
    [tuple[object, ...]],
    MockedCmdResponse,
]:
    """Mock command response for show-options -s (server)."""

    def _cmd(*args: object) -> MockedCmdResponse:
        return MockedCmdResponse(
            stdout=stdout,
            stderr=stderr,
        )

    return _cmd


def test_terminal_features(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test tmux's terminal-feature option destructuring."""
    monkeypatch.setattr(server, "cmd", fake_cmd(stdout=MOCKED_GLOBAL_OPTIONS))
    options_ = server._show_options()
    assert any("terminal-features" in k for k in options_)
    options = Options(**options_)
    assert options
    assert options.terminal_features
    assert options.terminal_features["screen*"] == ["title"]
    assert options.terminal_features["xterm*"] == [
        "clipboard",
        "ccolour",
        "cstyle",
        "focus",
    ]


def test_terminal_overrides(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test tmux's terminal-overrides option destructuring."""
    monkeypatch.setattr(server, "cmd", cmd_mocked)
    options_ = server._show_options()
    assert any("terminal-overrides" in k for k in options_)
    options = Options(**options_)
    assert options
    assert options.terminal_overrides
    assert options_["terminal-overrides"] is not None
    assert isinstance(options_["terminal-overrides"], dict)
    assert not isinstance(options_["terminal-overrides"], SparseArray)
    assert "xterm-256color" in options_["terminal-overrides"]
    assert isinstance(options_["terminal-overrides"]["xterm-256color"], dict)
    assert options_["terminal-overrides"]["xterm-256color"] == {"Tc": None}


def test_command_alias(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test tmux's command-alias option destructuring."""
    monkeypatch.setattr(server, "cmd", cmd_mocked)
    options_ = server._show_options()
    assert any("command-alias" in k for k in options_)
    options = Options(**options_)
    assert options
    assert options.command_alias
    assert isinstance(options_["command-alias"], dict)
    assert not isinstance(options_["command-alias"], SparseArray)
    assert isinstance(options_["command-alias"]["split-pane"], str)
    assert options_["command-alias"]["split-pane"] == "split-window"


def test_user_keys(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test tmux's user-keys option destructuring."""
    monkeypatch.setattr(server, "cmd", cmd_mocked)
    options_ = server._show_options()
    assert any("user-keys" in k for k in options_)
    options = Options(**options_)
    assert options
    assert options.user_keys is None


class OptionDataclassTestFixture(t.NamedTuple):
    """Test fixture raw show_option(s) data into typed libtmux data."""

    # pytest internal
    test_id: str

    # test data
    mocked_cmd_stdout: list[str]  # option data (raw)
    tmux_option: str  # e.g. terminal-features

    # results
    expected: t.Any  # e.g. 50, TerminalFeatures({}), etc.
    dataclass_attribute: str  # e.g. terminal_features


TEST_FIXTURES: list[OptionDataclassTestFixture] = [
    OptionDataclassTestFixture(
        test_id="terminal-features",
        mocked_cmd_stdout=textwrap.dedent(
            """
            terminal-features[0] xterm*:clipboard:ccolour:cstyle:focus
            terminal-features[1] screen*:title
            """,
        )
        .strip()
        .split("\n"),
        dataclass_attribute="terminal_features",
        tmux_option="terminal-features",
        expected={
            "screen*": ["title"],
            "xterm*": ["clipboard", "ccolour", "cstyle", "focus"],
        },
    ),
    OptionDataclassTestFixture(
        test_id="command-alias",
        mocked_cmd_stdout=textwrap.dedent(
            """
            command-alias[0] split-pane=split-window
            command-alias[1] splitp=split-window
            command-alias[2] "server-info=show-messages -JT"
            command-alias[3] "info=show-messages -JT"
            command-alias[4] "choose-window=choose-tree -w"
            command-alias[5] "choose-session=choose-tree -s"
            """,
        )
        .strip()
        .split("\n"),
        dataclass_attribute="command_alias",
        tmux_option="command-alias",
        expected=SparseArray(
            {
                "split-pane": "split-window",
                "splitp": "split-window",
                "server-info": "show-messages -JT",
                "info": "show-messages -JT",
                "choose-window": "choose-tree -w",
                "choose-session": "choose-tree -s",
            },
        ),
    ),
]


@pytest.mark.parametrize(
    list(OptionDataclassTestFixture._fields),
    TEST_FIXTURES,
    ids=[test.test_id for test in TEST_FIXTURES],
)
def test_mocked_cmd_stdoutclass_fixture(
    monkeypatch: pytest.MonkeyPatch,
    test_id: str,
    mocked_cmd_stdout: list[str],
    tmux_option: str,
    expected: t.Any,
    dataclass_attribute: str,
    server: Server,
) -> None:
    """Parametrized test grid for options."""
    monkeypatch.setattr(server, "cmd", fake_cmd(stdout=mocked_cmd_stdout))

    options_ = server._show_options()
    assert any(tmux_option in k for k in options_)
    options = Options(**options_)
    assert options
    assert hasattr(options, dataclass_attribute)
    assert getattr(options, dataclass_attribute, None) == expected


@pytest.mark.parametrize(
    list(OptionDataclassTestFixture._fields),
    TEST_FIXTURES,
    ids=[test.test_id for test in TEST_FIXTURES],
)
def test_show_option_pane_fixture(
    monkeypatch: pytest.MonkeyPatch,
    test_id: str,
    mocked_cmd_stdout: list[str],
    tmux_option: str,
    expected: t.Any,
    dataclass_attribute: str,
    server: Server,
) -> None:
    """Test Pane.show_option(s)?."""
    session = server.new_session(session_name="test")
    window = session.new_window(window_name="test")
    pane = window.split_window(attach=False)

    monkeypatch.setattr(pane, "cmd", fake_cmd(stdout=mocked_cmd_stdout))

    result = pane.show_option(tmux_option)

    assert result == expected

    if expected is None:
        assert result is not None, (
            f"Expected {expected} to be {type(expected)}, got None"
        )

    if isinstance(expected, dict):
        assert isinstance(result, dict), f'Expected dict, got "{type(result)}"'

        for k, v in expected.items():
            assert k in result

            assert result[k] == v


def test_stable_baseline_options_and_hooks(server: Server) -> None:
    """Ensure stable baseline across tmux versions."""
    session = server.new_session(session_name="test", detach=True)

    # List variables
    assert server.show_option("command-alias") == {
        "choose-session": "choose-tree -s",
        "choose-window": "choose-tree -w",
        "info": "show-messages -JT",
        "server-info": "show-messages -JT",
        "split-pane": "split-window",
        "splitp": "split-window",
    }
    if has_gte_version("3.2"):
        terminal_features = server.show_option("terminal-features")
        assert isinstance(terminal_features, dict)
        assert "screen*" in terminal_features
        assert terminal_features["screen*"] == ["title"]
        assert "xterm*" in terminal_features
        assert terminal_features["xterm*"] == [
            "clipboard",
            "ccolour",
            "cstyle",
            "focus",
            "title",
        ]
        # Additional features in tmux 3.4+
        if has_gte_version("3.4"):
            assert "rxvt*" in terminal_features
            assert terminal_features["rxvt*"] == ["ignorefkeys"]
    assert server.show_option("terminal-overrides") is None
    assert server.show_option("user-keys") is None
    assert server.show_option("status-format") is None
    assert server.show_option("update-environment") is None

    # List variables: Pane
    pane = session.active_pane
    assert pane is not None
    assert pane.show_option("pane-colours") is None


def test_high_level_api_expectations(server: Server) -> None:
    """Ensure options and hooks behave as expected."""

    # Raw input and output
    # Should be able to functionally parse raw CLI output, even outside of libtmux into
    # options.

    # Parsing steps
    # 1. Basic KV split: Should split options into key,values.
    # 2. Structure: Should decompose array-like options and dictionaries
    #    In the case of sparse arrays, which don't exist in Python, a SparseArray is
    #    used that behaves like a list but allows for sparse indexes so the indices
    #    aren't lost but the shape is still respected.
    # 3. Python Typings: Should cast the fully structured objects into types


def test_complex_option_values(server: Server) -> None:
    """Test complex option values and edge cases."""
    session = server.new_session(session_name="test")

    # Test quoted values with spaces
    session.set_option("@complex-option", "value with spaces")
    assert session.show_option("@complex-option") == "value with spaces"

    # Test escaped characters
    session.set_option("@escaped-option", "line1\\nline2")
    assert session.show_option("@escaped-option") == "line1\\nline2"

    # Test empty values
    session.set_option("@empty-option", "")
    assert session.show_option("@empty-option") == ""

    # Test option inheritance
    parent_val = session.show_option("status-style")
    session.set_option("status-style", "fg=red")
    assert session.show_option("status-style") == "fg=red"
    assert session.show_option("status-style", include_inherited=True) == "fg=red"
    session.unset_option("status-style")
    assert session.show_option("status-style", include_inherited=True) == parent_val


def test_terminal_features_edge_cases(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test edge cases for terminal-features option."""
    # Test empty features
    monkeypatch.setattr(
        server,
        "cmd",
        fake_cmd(stdout=["terminal-features[0] xterm*:"]),
    )
    options = server._show_options()
    terminal_features = t.cast(dict[str, list[str]], options["terminal-features"])
    assert isinstance(terminal_features, dict)
    xterm_features = terminal_features["xterm*"]
    assert isinstance(xterm_features, list)
    assert xterm_features == [""]  # tmux returns [''] for empty features

    # Test malformed features
    monkeypatch.setattr(
        server,
        "cmd",
        fake_cmd(stdout=["terminal-features[0] xterm*:invalid:feature:with:colons"]),
    )
    options = server._show_options()
    terminal_features = t.cast(dict[str, list[str]], options["terminal-features"])
    assert isinstance(terminal_features, dict)
    xterm_features = terminal_features["xterm*"]
    assert isinstance(xterm_features, list)
    assert any(f == "invalid" for f in xterm_features)
    assert any(f == "feature" for f in xterm_features)

    # Test features with special characters
    monkeypatch.setattr(
        server,
        "cmd",
        fake_cmd(
            stdout=[
                'terminal-features[0] "xterm*:feature with space:special*char"',
            ],
        ),
    )
    options = server._show_options()
    terminal_features = t.cast(dict[str, list[str]], options["terminal-features"])
    assert isinstance(terminal_features, dict)
    xterm_features = terminal_features["xterm*"]
    assert isinstance(xterm_features, list)
    assert any(f == "feature with space" for f in xterm_features)
    assert any(f == "special*char" for f in xterm_features)


def test_style_option_validation(server: Server) -> None:
    """Test style option validation."""
    session = server.new_session(session_name="test")

    # Valid style
    session.set_option("status-style", "fg=red,bg=default,bold")
    assert session.show_option("status-style") == "fg=red,bg=default,bold"

    # Invalid style should raise OptionError
    with pytest.raises(OptionError):
        session.set_option("status-style", "invalid-style")

    # Test complex style with multiple attributes
    session.set_option(
        "status-style",
        "fg=colour240,bg=#525252,bold,underscore",
    )
    assert (
        session.show_option("status-style") == "fg=colour240,bg=#525252,bold,underscore"
    )

    # Test style with variables
    session.set_option("status-style", "fg=#{?pane_in_mode,red,green}")
    assert session.show_option("status-style") == "fg=#{?pane_in_mode,red,green}"


def test_option_error_handling(server: Server) -> None:
    """Test error handling for options."""
    session = server.new_session(session_name="test")

    # Test invalid/unknown option (tmux 3.0+ returns 'invalid option')
    with pytest.raises(OptionError) as exc_info:
        session.show_option("non-existent-option")
    error_msg = str(exc_info.value).lower()
    assert any(msg in error_msg for msg in ["unknown option", "invalid option"])

    # Test invalid option value
    with pytest.raises(OptionError):
        session.set_option("aggressive-resize", "invalid")

    # Test ambiguous option (if supported by tmux version)
    if has_gte_version("2.4"):
        with pytest.raises(OptionError) as exc_info:
            # Use a partial name that could match multiple options
            session.show_option(
                "window-"
            )  # Ambiguous: could be window-size, window-style, etc.
        assert "ambiguous option" in str(exc_info.value).lower()
