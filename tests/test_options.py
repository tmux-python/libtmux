"""Test for libtmux options management."""

from __future__ import annotations

import dataclasses
import textwrap
import typing as t

import pytest

from libtmux import exc
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
from libtmux.options import TerminalOverrides, convert_values, explode_arrays
from libtmux.pane import Pane

if t.TYPE_CHECKING:
    from typing_extensions import LiteralString

    from libtmux.server import Server
    from libtmux.session import Session


def test_options(server: Server) -> None:
    """Test basic options."""
    session = server.new_session(session_name="test")
    window = session.new_window(window_name="test")
    pane = window.split(attach=False)

    for obj in [server, session, window, pane]:
        obj._show_options()
        obj._show_options(global_=True)
        obj._show_options(include_inherited=True)
        obj._show_options(include_hooks=True)
        with pytest.raises(exc.OptionError):
            obj._show_option("test")
        if has_gte_version("3.0"):
            obj._show_option("test", ignore_errors=True)
        with pytest.raises(exc.OptionError):
            obj.set_option("test", "invalid")
        if isinstance(obj, Pane):
            if has_gte_version("3.0"):
                obj.set_option("test", "invalid", ignore_errors=True)
            else:
                with pytest.raises(exc.OptionError):
                    obj.set_option("test", "invalid", ignore_errors=True)
        else:
            obj.set_option("test", "invalid", ignore_errors=True)


def test_options_server(server: Server) -> None:
    """Test server options."""
    session = server.new_session(session_name="test")
    window = session.new_window(window_name="test")
    pane = window.split(attach=False)

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
        with pytest.raises(exc.OptionError):
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
    window.split(attach=False)

    window_options_ = window._show_options(scope=OptionScope.Window)

    window_options = WindowOptions(**window_options_)
    assert window_options.automatic_rename == window_options_.get("automatic-rename")


def test_options_pane(server: Server) -> None:
    """Test pane options."""
    session = server.new_session(session_name="test")
    window = session.new_window(window_name="test")
    pane = window.split(attach=False)

    pane_options_ = pane._show_options(scope=OptionScope.Pane)

    pane_options = PaneOptions(**pane_options_)
    assert pane_options.window_active_style == pane_options_.get("window-active-style")


def test_options_grid(server: Server) -> None:
    """Test options against grid."""
    session = server.new_session(session_name="test")
    window = session.new_window(window_name="test")
    pane = window.split(attach=False)

    for include_inherited in [True, False]:
        for global_ in [True, False]:
            for obj in [server, session, window, pane]:
                for scope in [
                    OptionScope.Server,
                    OptionScope.Session,
                    OptionScope.Window,
                ]:
                    objglobal__options_ = obj._show_options(
                        scope=scope,
                        include_inherited=include_inherited,
                        global_=global_,
                    )
                    objglobal__options = Options(**objglobal__options_)
                    for field in dataclasses.fields(objglobal__options):
                        expected = objglobal__options_.get(field.name.replace("_", "-"))

                        if include_inherited and expected is None:
                            expected = objglobal__options_.get(
                                f"{field.name.replace('_', '-')}*",
                                None,
                            )

                        default_value = None
                        if field.default_factory is not dataclasses.MISSING:
                            default_value = field.default_factory()
                            if expected is None:
                                default_value = None
                        assert (
                            getattr(objglobal__options, field.name, default_value)
                            == expected
                        ), (
                            f"Expect {field.name} to be {expected} when "
                            + f"scope={scope}, global_={global_}"
                        )
                    if (
                        has_gte_version("3.0")
                        and scope == OptionScope.Window
                        and global_
                    ):
                        assert objglobal__options.pane_base_index == 0


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


class TerminalOverridesMultiFeatureCase(t.NamedTuple):
    """Test fixture for terminal-overrides with multiple features per terminal."""

    test_id: str
    raw_entry: str
    expected_term: str
    expected_features: dict[str, str | int | None]


@pytest.mark.parametrize(
    TerminalOverridesMultiFeatureCase._fields,
    [
        TerminalOverridesMultiFeatureCase(
            test_id="two_flags",
            raw_entry="xterm*:smcup@:rmcup@",
            expected_term="xterm*",
            expected_features={"smcup@": None, "rmcup@": None},
        ),
        TerminalOverridesMultiFeatureCase(
            test_id="flag_and_keyval",
            raw_entry="xterm*:XT:Ms=clipboard",
            expected_term="xterm*",
            expected_features={"XT": None, "Ms": "clipboard"},
        ),
        TerminalOverridesMultiFeatureCase(
            test_id="multiple_keyvals",
            raw_entry="screen*:Tc:RGB:setab=test",
            expected_term="screen*",
            expected_features={
                "Tc": None,
                "RGB": None,
                "setab": "test",
            },
        ),
        TerminalOverridesMultiFeatureCase(
            test_id="integer_value",
            raw_entry="tmux*:colors=256:Tc",
            expected_term="tmux*",
            expected_features={"colors": 256, "Tc": None},
        ),
    ],
    ids=lambda x: x.test_id if isinstance(x, TerminalOverridesMultiFeatureCase) else x,
)
def test_terminal_overrides_multi_feature(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    test_id: str,
    raw_entry: str,
    expected_term: str,
    expected_features: dict[str, str | int | None],
) -> None:
    """Test terminal-overrides parsing with multiple features per terminal.

    Per tmux.1 (lines 4311-4326), terminal-overrides entries are colon-separated
    strings: terminal pattern followed by a LIST of features (not just one).
    For example, 'xterm*:XT:Ms=value' should parse as two features: XT and Ms.
    """
    mock_options = [f"terminal-overrides[0] {raw_entry}"]
    monkeypatch.setattr(server, "cmd", fake_cmd(stdout=mock_options))
    options_ = server._show_options()

    assert "terminal-overrides" in options_
    term_overrides = t.cast(TerminalOverrides, options_["terminal-overrides"])
    assert expected_term in term_overrides
    assert term_overrides[expected_term] == expected_features


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
        expected={
            "split-pane": "split-window",
            "splitp": "split-window",
            "server-info": "show-messages -JT",
            "info": "show-messages -JT",
            "choose-window": "choose-tree -w",
            "choose-session": "choose-tree -s",
        },
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
    pane = window.split(attach=False)

    monkeypatch.setattr(pane, "cmd", fake_cmd(stdout=mocked_cmd_stdout))

    result = pane.show_option(tmux_option)

    assert result == expected


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

    # Terminal overrides differ by version
    # tmux 3.0a-3.1b: has default values (xterm*, screen*)
    # tmux 3.2+: defaults removed, returns None unless explicitly set
    if has_gte_version("3.2"):
        terminal_overrides = server.show_option("terminal-overrides")
        assert isinstance(terminal_overrides, (dict, type(None)))
    elif has_gte_version("3.0"):
        # tmux 3.0a/3.1b have defaults like "xterm*:XT:Ms=...,screen*:XT"
        terminal_overrides = server.show_option("terminal-overrides")
        assert isinstance(terminal_overrides, dict)
        assert "screen*" in terminal_overrides or "xterm*" in terminal_overrides
    else:
        terminal_overrides = server.show_option("terminal-overrides")
        assert isinstance(terminal_overrides, dict)
        assert "screen*" in terminal_overrides
        assert "xterm*" in terminal_overrides

    assert server.show_option("user-keys") is None

    # status-format was added in tmux 2.9
    if has_gte_version("2.9"):
        status_format = server.show_option("status-format")
        assert isinstance(status_format, (dict, type(None)))
    else:
        with pytest.raises(exc.OptionError):
            server.show_option("status-format")

    # update-environment was added in tmux 3.0
    if has_gte_version("3.0"):
        update_env = server.show_option("update-environment")
        assert isinstance(update_env, (list, type(None)))
    else:
        with pytest.raises(exc.OptionError):
            server.show_option("update-environment")

    # List variables: Pane (pane-colours added in tmux 3.3)
    pane = session.active_pane
    assert pane is not None
    if has_gte_version("3.3"):
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

    # Test option inheritance (only for tmux >= 3.0)
    if has_gte_version("3.0"):
        # Capture the inherited value (from global scope). Need include_inherited
        # because without an explicit session-level value, show_option returns None
        inherited_val = session.show_option("status-style", include_inherited=True)
        session.set_option("status-style", "fg=red")
        assert session.show_option("status-style") == "fg=red"
        assert session.show_option("status-style", include_inherited=True) == "fg=red"
        session.unset_option("status-style")
        # After unsetting, should get inherited value back
        assert (
            session.show_option("status-style", include_inherited=True) == inherited_val
        )


def test_style_option_validation(server: Server) -> None:
    """Test style option validation."""
    session = server.new_session(session_name="test")

    # Valid style (format differs between tmux versions)
    # tmux ≤3.1: Styles are normalized when stored (bold→bright, bg=default omitted)
    # tmux ≥3.2: Styles stored as strings (literal input, allows format expansion)
    session.set_option("status-style", "fg=red,bg=default,bold")
    style = session.show_option("status-style")
    assert isinstance(style, str)
    assert "fg=red" in str(style)

    if has_gte_version("3.2"):
        # tmux 3.2+: literal string output
        assert "bg=default" in str(style)
        assert "bold" in str(style)
    else:
        # tmux <3.2: normalized output (bold→bright, bg=default omitted)
        assert "bright" in str(style)
        assert "bg=default" not in str(style)

    # Invalid style should raise OptionError
    with pytest.raises(exc.OptionError):
        session.set_option("status-style", "invalid-style")

    # Test complex style with multiple attributes (tmux >= 3.0)
    if has_gte_version("3.0"):
        session.set_option(
            "status-style",
            "fg=colour240,bg=#525252,bold,underscore",
        )
        style = session.show_option("status-style")
        assert isinstance(style, str)
        if has_gte_version("3.2"):
            # tmux 3.2+: literal string output
            assert style == "fg=colour240,bg=#525252,bold,underscore"
        else:
            # tmux <3.2: bold→bright
            assert style == "fg=colour240,bg=#525252,bright,underscore"

        # Test style with variables (format expansion added in tmux 3.2)
        if has_gte_version("3.2"):
            session.set_option("status-style", "fg=#{?pane_in_mode,red,green}")
            style = session.show_option("status-style")
            assert isinstance(style, str)
            assert style == "fg=#{?pane_in_mode,red,green}"


def test_option_error_handling(server: Server) -> None:
    """Test error handling for options."""
    session = server.new_session(session_name="test")

    # Test invalid/unknown option (tmux 3.0+ returns 'invalid option')
    with pytest.raises(exc.OptionError) as exc_info:
        session.show_option("non-existent-option")
    error_msg = str(exc_info.value).lower()
    assert any(msg in error_msg for msg in ["unknown option", "invalid option"])

    # Test invalid option value
    with pytest.raises(exc.OptionError):
        session.set_option("aggressive-resize", "invalid")

    # Test ambiguous option (if supported by tmux version)
    if has_gte_version("2.4"):
        with pytest.raises(exc.OptionError) as exc_info:
            # Use a partial name that could match multiple options
            session.show_option(
                "window-"
            )  # Ambiguous: could be window-size, window-style, etc.
        assert "ambiguous option" in str(exc_info.value).lower()


def test_terminal_features_edge_cases(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test edge cases for terminal-features option."""
    if not has_gte_version("3.2"):
        pytest.skip("terminal-features requires tmux >= 3.2")

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


# =============================================================================
# Comprehensive Option Test Grid
# =============================================================================


class OptionTestCase(t.NamedTuple):
    """Test case for option validation."""

    test_id: str
    option: str  # tmux option name (hyphenated)
    scope: OptionScope
    test_value: t.Any  # Value to set
    expected_type: type  # Expected Python type after retrieval
    min_version: str | None = None  # Minimum tmux version required
    xfail_reason: str | None = None  # Mark as expected failure with reason


# --- Server Options ---
SERVER_INTEGER_OPTIONS: list[OptionTestCase] = [
    OptionTestCase("server_buffer_limit", "buffer-limit", OptionScope.Server, 100, int),
    OptionTestCase("server_escape_time", "escape-time", OptionScope.Server, 50, int),
    OptionTestCase(
        "server_message_limit", "message-limit", OptionScope.Server, 500, int
    ),
    OptionTestCase(
        "server_prompt_history_limit",
        "prompt-history-limit",
        OptionScope.Server,
        50,
        int,
        "3.3",
    ),
]

SERVER_BOOLEAN_OPTIONS: list[OptionTestCase] = [
    # Note: exit-empty and exit-unattached are tested with "off" to avoid killing server
    OptionTestCase("server_exit_empty", "exit-empty", OptionScope.Server, "off", bool),
    OptionTestCase(
        "server_exit_unattached", "exit-unattached", OptionScope.Server, "off", bool
    ),
    OptionTestCase(
        "server_focus_events", "focus-events", OptionScope.Server, "on", bool
    ),
]

SERVER_CHOICE_OPTIONS: list[OptionTestCase] = [
    # extended-keys: "on"/"off" return bool, use "always" for str test (3.2+)
    OptionTestCase(
        "server_extended_keys",
        "extended-keys",
        OptionScope.Server,
        "always",
        str,
        "3.2",
    ),
    OptionTestCase(
        "server_set_clipboard", "set-clipboard", OptionScope.Server, "external", str
    ),
]

SERVER_STRING_OPTIONS: list[OptionTestCase] = [
    OptionTestCase(
        "server_default_terminal",
        "default-terminal",
        OptionScope.Server,
        "screen-256color",
        str,
    ),
    OptionTestCase("server_editor", "editor", OptionScope.Server, "vim", str, "3.2"),
]

# --- Session Options ---
SESSION_INTEGER_OPTIONS: list[OptionTestCase] = [
    OptionTestCase("session_base_index", "base-index", OptionScope.Session, 1, int),
    OptionTestCase(
        "session_display_panes_time",
        "display-panes-time",
        OptionScope.Session,
        2000,
        int,
    ),
    OptionTestCase(
        "session_display_time", "display-time", OptionScope.Session, 1000, int
    ),
    OptionTestCase(
        "session_history_limit", "history-limit", OptionScope.Session, 5000, int
    ),
    OptionTestCase(
        "session_lock_after_time", "lock-after-time", OptionScope.Session, 300, int
    ),
    OptionTestCase("session_repeat_time", "repeat-time", OptionScope.Session, 500, int),
    OptionTestCase(
        "session_status_interval", "status-interval", OptionScope.Session, 5, int
    ),
    OptionTestCase(
        "session_status_left_length", "status-left-length", OptionScope.Session, 20, int
    ),
    OptionTestCase(
        "session_status_right_length",
        "status-right-length",
        OptionScope.Session,
        30,
        int,
    ),
]

SESSION_BOOLEAN_OPTIONS: list[OptionTestCase] = [
    # Note: destroy-unattached is tested with "off" to avoid destroying test session
    OptionTestCase(
        "session_destroy_unattached",
        "destroy-unattached",
        OptionScope.Session,
        "off",
        bool,
    ),
    OptionTestCase("session_mouse", "mouse", OptionScope.Session, "on", bool),
    OptionTestCase(
        "session_renumber_windows", "renumber-windows", OptionScope.Session, "on", bool
    ),
    OptionTestCase("session_set_titles", "set-titles", OptionScope.Session, "on", bool),
]

SESSION_CHOICE_OPTIONS: list[OptionTestCase] = [
    OptionTestCase(
        "session_activity_action", "activity-action", OptionScope.Session, "any", str
    ),
    OptionTestCase(
        "session_bell_action", "bell-action", OptionScope.Session, "any", str
    ),
    # detach-on-destroy: "on"/"off" return bool, use "no-detached" (3.2+) for str
    OptionTestCase(
        "session_detach_on_destroy",
        "detach-on-destroy",
        OptionScope.Session,
        "no-detached",
        str,
        "3.2",
    ),
    OptionTestCase(
        "session_silence_action", "silence-action", OptionScope.Session, "none", str
    ),
    OptionTestCase(
        "session_status_keys", "status-keys", OptionScope.Session, "vi", str
    ),
    OptionTestCase(
        "session_status_justify", "status-justify", OptionScope.Session, "left", str
    ),
    OptionTestCase(
        "session_status_position", "status-position", OptionScope.Session, "bottom", str
    ),
    # visual-*: "on"/"off" return bool, use "both" for str test
    OptionTestCase(
        "session_visual_activity", "visual-activity", OptionScope.Session, "both", str
    ),
    OptionTestCase(
        "session_visual_bell", "visual-bell", OptionScope.Session, "both", str
    ),
    OptionTestCase(
        "session_visual_silence", "visual-silence", OptionScope.Session, "both", str
    ),
]

SESSION_STRING_OPTIONS: list[OptionTestCase] = [
    OptionTestCase(
        "session_default_command", "default-command", OptionScope.Session, "", str
    ),
    OptionTestCase(
        "session_status_left", "status-left", OptionScope.Session, "[#S]", str
    ),
    OptionTestCase(
        "session_status_right", "status-right", OptionScope.Session, "%H:%M", str
    ),
]

SESSION_STYLE_OPTIONS: list[OptionTestCase] = [
    OptionTestCase(
        "session_status_style", "status-style", OptionScope.Session, "fg=green", str
    ),
    OptionTestCase(
        "session_status_left_style",
        "status-left-style",
        OptionScope.Session,
        "fg=blue",
        str,
    ),
    OptionTestCase(
        "session_status_right_style",
        "status-right-style",
        OptionScope.Session,
        "fg=yellow",
        str,
    ),
    OptionTestCase(
        "session_message_style", "message-style", OptionScope.Session, "fg=red", str
    ),
]

# --- Window Options ---
WINDOW_INTEGER_OPTIONS: list[OptionTestCase] = [
    OptionTestCase(
        "window_pane_base_index", "pane-base-index", OptionScope.Window, 1, int
    ),
    OptionTestCase(
        "window_monitor_silence", "monitor-silence", OptionScope.Window, 10, int
    ),
]

WINDOW_BOOLEAN_OPTIONS: list[OptionTestCase] = [
    OptionTestCase(
        "window_aggressive_resize", "aggressive-resize", OptionScope.Window, "on", bool
    ),
    OptionTestCase(
        "window_automatic_rename", "automatic-rename", OptionScope.Window, "off", bool
    ),
    OptionTestCase(
        "window_monitor_activity", "monitor-activity", OptionScope.Window, "on", bool
    ),
    OptionTestCase(
        "window_monitor_bell", "monitor-bell", OptionScope.Window, "on", bool
    ),
    OptionTestCase("window_wrap_search", "wrap-search", OptionScope.Window, "on", bool),
]

WINDOW_CHOICE_OPTIONS: list[OptionTestCase] = [
    OptionTestCase(
        "window_clock_mode_style", "clock-mode-style", OptionScope.Window, "24", int
    ),
    OptionTestCase("window_mode_keys", "mode-keys", OptionScope.Window, "vi", str),
    # pane-border-status: "off" returns bool, use "top" for str test
    OptionTestCase(
        "window_pane_border_status",
        "pane-border-status",
        OptionScope.Window,
        "top",
        str,
    ),
    OptionTestCase(
        "window_window_size", "window-size", OptionScope.Window, "latest", str, "3.1"
    ),
]

WINDOW_STRING_OPTIONS: list[OptionTestCase] = [
    OptionTestCase(
        "window_pane_border_format",
        "pane-border-format",
        OptionScope.Window,
        "#{pane_index}",
        str,
    ),
]

WINDOW_STYLE_OPTIONS: list[OptionTestCase] = [
    OptionTestCase(
        "window_mode_style", "mode-style", OptionScope.Window, "fg=white", str
    ),
    OptionTestCase(
        "window_pane_border_style",
        "pane-border-style",
        OptionScope.Window,
        "fg=green",
        str,
    ),
    OptionTestCase(
        "window_pane_active_border_style",
        "pane-active-border-style",
        OptionScope.Window,
        "fg=red",
        str,
    ),
    OptionTestCase(
        "window_window_status_style",
        "window-status-style",
        OptionScope.Window,
        "fg=cyan",
        str,
    ),
    OptionTestCase(
        "window_window_status_current_style",
        "window-status-current-style",
        OptionScope.Window,
        "fg=magenta",
        str,
    ),
]

# --- Pane Options ---
PANE_BOOLEAN_OPTIONS: list[OptionTestCase] = [
    OptionTestCase(
        "pane_allow_rename", "allow-rename", OptionScope.Pane, "off", bool, "3.0"
    ),
    OptionTestCase(
        "pane_alternate_screen", "alternate-screen", OptionScope.Pane, "on", bool, "3.0"
    ),
    OptionTestCase(
        "pane_scroll_on_clear", "scroll-on-clear", OptionScope.Pane, "on", bool, "3.3"
    ),
    OptionTestCase(
        "pane_synchronize_panes",
        "synchronize-panes",
        OptionScope.Pane,
        "off",
        bool,
        "3.1",
    ),
]

PANE_CHOICE_OPTIONS: list[OptionTestCase] = [
    # allow-passthrough: "on"/"off" return bool, use "all" for str test (3.3+)
    OptionTestCase(
        "pane_allow_passthrough",
        "allow-passthrough",
        OptionScope.Pane,
        "all",
        str,
        "3.4",
    ),
    # remain-on-exit: "on"/"off" return bool, use "failed" for str test (3.2+)
    OptionTestCase(
        "pane_remain_on_exit",
        "remain-on-exit",
        OptionScope.Pane,
        "failed",
        str,
        "3.2",
    ),
]

PANE_STYLE_OPTIONS: list[OptionTestCase] = [
    OptionTestCase(
        "pane_window_style", "window-style", OptionScope.Pane, "default", str, "3.0"
    ),
    OptionTestCase(
        "pane_window_active_style",
        "window-active-style",
        OptionScope.Pane,
        "default",
        str,
        "3.0",
    ),
]

# Combine all option test cases
ALL_OPTION_TEST_CASES: list[OptionTestCase] = (
    SERVER_INTEGER_OPTIONS
    + SERVER_BOOLEAN_OPTIONS
    + SERVER_CHOICE_OPTIONS
    + SERVER_STRING_OPTIONS
    + SESSION_INTEGER_OPTIONS
    + SESSION_BOOLEAN_OPTIONS
    + SESSION_CHOICE_OPTIONS
    + SESSION_STRING_OPTIONS
    + SESSION_STYLE_OPTIONS
    + WINDOW_INTEGER_OPTIONS
    + WINDOW_BOOLEAN_OPTIONS
    + WINDOW_CHOICE_OPTIONS
    + WINDOW_STRING_OPTIONS
    + WINDOW_STYLE_OPTIONS
    + PANE_BOOLEAN_OPTIONS
    + PANE_CHOICE_OPTIONS
    + PANE_STYLE_OPTIONS
)


def _build_option_params() -> list[t.Any]:
    """Build pytest params with appropriate marks."""
    params = []
    for tc in ALL_OPTION_TEST_CASES:
        marks: list[t.Any] = []
        if tc.xfail_reason:
            marks.append(pytest.mark.xfail(reason=tc.xfail_reason))
        params.append(pytest.param(tc, id=tc.test_id, marks=marks))
    return params


@pytest.mark.parametrize("test_case", _build_option_params())
def test_option_set_show_cycle(server: Server, test_case: OptionTestCase) -> None:
    """Test set/show cycle for each option type."""
    if not has_gte_version("3.0"):
        pytest.skip("Option tests require tmux 3.0+")

    if test_case.min_version and not has_gte_version(test_case.min_version):
        pytest.skip(f"Requires tmux {test_case.min_version}+")

    # Get appropriate target object
    session = server.new_session(session_name="test_option_cycle")
    window = session.active_window
    assert window is not None
    pane = window.active_pane
    assert pane is not None

    targets = {
        OptionScope.Server: server,
        OptionScope.Session: session,
        OptionScope.Window: window,
        OptionScope.Pane: pane,
    }
    target = targets[test_case.scope]

    # Test set
    target.set_option(test_case.option, test_case.test_value)

    # Test show
    result = target.show_option(test_case.option)
    assert result is not None, f"Expected {test_case.option} to be set, got None"
    assert isinstance(result, test_case.expected_type), (
        f"Expected {test_case.expected_type.__name__}, got {type(result).__name__}"
    )


# =============================================================================
# show_options Tests
# =============================================================================

# Scope-specific expected keys (verified with global_=True)
SERVER_EXPECTED_KEYS = ["buffer-limit", "escape-time", "exit-empty", "focus-events"]
SESSION_EXPECTED_KEYS = ["base-index", "history-limit", "status"]
WINDOW_EXPECTED_KEYS = ["mode-keys", "pane-base-index", "automatic-rename"]


class ShowOptionsTestCase(t.NamedTuple):
    """Test case for show_options validation."""

    test_id: str
    scope: OptionScope
    expected_keys: list[str]
    global_: bool = False
    include_inherited: bool = False
    min_version: str = "3.2"


SHOW_OPTIONS_TEST_CASES: list[ShowOptionsTestCase] = [
    # Server scope tests
    ShowOptionsTestCase(
        test_id="server_global",
        scope=OptionScope.Server,
        expected_keys=SERVER_EXPECTED_KEYS,
        global_=True,
    ),
    ShowOptionsTestCase(
        test_id="server_global_inherited",
        scope=OptionScope.Server,
        expected_keys=SERVER_EXPECTED_KEYS,
        global_=True,
        include_inherited=True,
    ),
    # Session scope tests (require global_=True for defaults)
    ShowOptionsTestCase(
        test_id="session_global",
        scope=OptionScope.Session,
        expected_keys=SESSION_EXPECTED_KEYS,
        global_=True,
    ),
    ShowOptionsTestCase(
        test_id="session_global_inherited",
        scope=OptionScope.Session,
        expected_keys=SESSION_EXPECTED_KEYS,
        global_=True,
        include_inherited=True,
    ),
    # Window scope tests
    ShowOptionsTestCase(
        test_id="window_global",
        scope=OptionScope.Window,
        expected_keys=WINDOW_EXPECTED_KEYS,
        global_=True,
    ),
    ShowOptionsTestCase(
        test_id="window_global_inherited",
        scope=OptionScope.Window,
        expected_keys=WINDOW_EXPECTED_KEYS,
        global_=True,
        include_inherited=True,
    ),
]


def _build_show_options_params() -> list[t.Any]:
    """Build pytest params for show_options tests."""
    return [pytest.param(tc, id=tc.test_id) for tc in SHOW_OPTIONS_TEST_CASES]


@pytest.mark.parametrize("test_case", _build_show_options_params())
def test_show_options_returns_expected_keys(
    server: Server,
    test_case: ShowOptionsTestCase,
) -> None:
    """Test that show_options() returns dict with expected scope-specific keys."""
    if not has_gte_version(test_case.min_version):
        pytest.skip(f"Requires tmux >= {test_case.min_version}")

    session = server.new_session(session_name="test_show_options")
    window = session.active_window
    pane = window.active_pane
    assert pane is not None

    # Use server for all scopes (matches test_options_grid pattern)
    options = server.show_options(
        global_=test_case.global_,
        scope=test_case.scope,
        include_inherited=test_case.include_inherited,
    )

    assert isinstance(options, dict)
    assert len(options) > 0, (
        f"Expected non-empty dict for scope={test_case.scope.name}, "
        f"global_={test_case.global_}"
    )

    # Verify expected keys exist (with or without * suffix for inherited)
    for key in test_case.expected_keys:
        # Check for key or key* (inherited marker)
        assert key in options or f"{key}*" in options, (
            f"Expected '{key}' in {test_case.scope.name} options, "
            f"got keys: {list(options.keys())[:10]}..."
        )


# =============================================================================
# convert_values Tests
# =============================================================================


class ConvertValuesSparseTestCase(t.NamedTuple):
    """Test case for convert_values with SparseArray (via dict branch)."""

    test_id: str
    initial_values: dict[int, str]  # index -> value
    expected_converted: dict[int, t.Any]  # index -> converted value


CONVERT_SPARSE_TEST_CASES: list[ConvertValuesSparseTestCase] = [
    ConvertValuesSparseTestCase(
        "boolean_on_off",
        {0: "on", 1: "off"},
        {0: True, 1: False},
    ),
    ConvertValuesSparseTestCase(
        "numeric_conversion",
        {0: "50", 5: "100"},
        {0: 50, 5: 100},
    ),
    ConvertValuesSparseTestCase(
        "mixed_values",
        {0: "on", 1: "50", 2: "text"},
        {0: True, 1: 50, 2: "text"},
    ),
    ConvertValuesSparseTestCase(
        "sparse_indices",
        {0: "on", 10: "off", 100: "42"},
        {0: True, 10: False, 100: 42},
    ),
]


@pytest.mark.parametrize(
    "test_case",
    [pytest.param(tc, id=tc.test_id) for tc in CONVERT_SPARSE_TEST_CASES],
)
def test_convert_values_sparse_array(
    test_case: ConvertValuesSparseTestCase,
) -> None:
    """Test convert_values handles SparseArray via dict branch.

    Note: SparseArray inherits from dict, so the dict branch in convert_values
    handles it correctly. This test verifies that behavior.
    """
    sparse: SparseArray[str] = SparseArray()
    for idx, val in test_case.initial_values.items():
        sparse.add(idx, val)

    result = convert_values(sparse)

    assert isinstance(result, SparseArray)
    for idx, expected in test_case.expected_converted.items():
        assert result[idx] == expected, f"Index {idx}: {result[idx]} != {expected}"


def test_convert_values_preserves_sparse_keys() -> None:
    """Test convert_values preserves sparse array indices."""
    sparse: SparseArray[str] = SparseArray()
    sparse.add(0, "on")
    sparse.add(5, "off")
    sparse.add(99, "100")

    result = convert_values(sparse)

    # Keys should be preserved
    assert isinstance(result, SparseArray)
    assert sorted(result.keys()) == [0, 5, 99]
    assert result[0] is True
    assert result[5] is False
    assert result[99] == 100


def test_show_option_g_parameter_emits_deprecation_warning(
    session: Session,
) -> None:
    """Test show_option() emits DeprecationWarning when g parameter is used."""
    server = session.server
    with pytest.warns(DeprecationWarning, match=r"g argument is deprecated"):
        server.show_option("buffer-limit", g=True)


# =============================================================================
# show_option with Indexed Array Tests
# =============================================================================


class ShowOptionIndexedTestCase(t.NamedTuple):
    """Test case for show_option with bracketed array index."""

    test_id: str
    option: str
    expect_sparse_array: bool  # True for base name, False for indexed


SHOW_OPTION_INDEXED_TEST_CASES: list[ShowOptionIndexedTestCase] = [
    ShowOptionIndexedTestCase(
        test_id="indexed_returns_value",
        option="status-format[0]",
        expect_sparse_array=False,
    ),
    ShowOptionIndexedTestCase(
        test_id="base_name_returns_sparse_array",
        option="status-format",
        expect_sparse_array=True,
    ),
]


@pytest.mark.parametrize(
    "test_case",
    [pytest.param(tc, id=tc.test_id) for tc in SHOW_OPTION_INDEXED_TEST_CASES],
)
def test_show_option_indexed_array(
    session: Session,
    test_case: ShowOptionIndexedTestCase,
) -> None:
    """Test show_option handles bracketed array indices correctly.

    When querying an option with a bracketed index (e.g., 'status-format[0]'),
    tmux returns only that specific index's value. When querying the base name
    (e.g., 'status-format'), tmux returns all indexed values.

    This test verifies libtmux correctly:
    - Returns a single value for indexed queries
    - Returns a SparseArray for base name queries on array options
    """
    result = session.show_option(test_case.option, global_=True)
    if test_case.expect_sparse_array:
        assert isinstance(result, SparseArray), (
            f"Expected SparseArray for '{test_case.option}', "
            f"got {type(result).__name__}"
        )
    else:
        assert result is not None, (
            f"Expected a value for '{test_case.option}', got None"
        )
        assert not isinstance(result, SparseArray), (
            f"Expected single value for '{test_case.option}', got SparseArray"
        )


# =============================================================================
# explode_arrays Inherited Marker Tests
# =============================================================================


class ExplodeArraysInheritedCase(t.NamedTuple):
    """Test case for explode_arrays with inherited marker preservation."""

    test_id: str
    raw_input: dict[str, str | None]
    expected_key: str
    expected_indices: dict[int, str]


EXPLODE_ARRAYS_INHERITED_CASES: list[ExplodeArraysInheritedCase] = [
    ExplodeArraysInheritedCase(
        test_id="inherited_array_marker_preserved",
        raw_input={"status-format[0]*": "fmt0", "status-format[1]*": "fmt1"},
        expected_key="status-format*",
        expected_indices={0: "fmt0", 1: "fmt1"},
    ),
    ExplodeArraysInheritedCase(
        test_id="non_inherited_array_no_marker",
        raw_input={"status-format[0]": "fmt0", "status-format[1]": "fmt1"},
        expected_key="status-format",
        expected_indices={0: "fmt0", 1: "fmt1"},
    ),
    ExplodeArraysInheritedCase(
        test_id="mixed_inherited_indices",
        raw_input={"opt[0]*": "v0", "opt[5]*": "v5", "opt[10]*": "v10"},
        expected_key="opt*",
        expected_indices={0: "v0", 5: "v5", 10: "v10"},
    ),
]


@pytest.mark.parametrize(
    "test_case",
    [pytest.param(tc, id=tc.test_id) for tc in EXPLODE_ARRAYS_INHERITED_CASES],
)
def test_explode_arrays_preserves_inherited_marker(
    test_case: ExplodeArraysInheritedCase,
) -> None:
    """Test that explode_arrays preserves the inherited marker (*) for array options.

    When tmux returns inherited array options with the -A flag, each index includes
    a trailing asterisk (e.g., "status-format[0]*"). The explode_arrays function
    should preserve this marker in the resulting key, producing "status-format*"
    instead of stripping it to just "status-format".

    This ensures consistency with scalar inherited options, which already preserve
    the "*" marker (e.g., "visual-activity*" stays as "visual-activity*").
    """
    result = explode_arrays(test_case.raw_input)

    assert test_case.expected_key in result, (
        f"Expected key '{test_case.expected_key}' not found in result. "
        f"Got keys: {list(result.keys())}"
    )

    array_value = result[test_case.expected_key]
    # explode_arrays returns SparseArray for most options (dict-like with int keys)
    assert isinstance(array_value, SparseArray), (
        f"Expected SparseArray for array option, got {type(array_value).__name__}"
    )

    for idx, expected_val in test_case.expected_indices.items():
        assert idx in array_value, (
            f"Expected index {idx} not found in array. "
            f"Got indices: {list(array_value.keys())}"
        )
        assert array_value[idx] == expected_val, (
            f"Value at index {idx}: expected '{expected_val}', got '{array_value[idx]}'"
        )
