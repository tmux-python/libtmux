"""Tests for engine base helpers."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.engines.base import (
    CommandRequest,
    CommandSeparator,
    encode_direct_argv,
    render_control_line,
)

if t.TYPE_CHECKING:
    from typing_extensions import Self


class WireCase(t.NamedTuple):
    """An argv and the control-mode wire line it should render to."""

    test_id: str
    argv: tuple[str, ...]
    expected: str


WIRE_CASES = (
    WireCase(
        test_id="plain",
        argv=("rename-window", "-t", "@1", "edit"),
        expected="rename-window -t @1 edit",
    ),
    WireCase(
        test_id="quotes_spaces",
        argv=("set-option", "@x", "a b"),
        expected="set-option @x 'a b'",
    ),
    WireCase(
        test_id="literal_exact_semicolon",
        argv=("send-keys", "-l", ";"),
        expected="send-keys -l ';'",
    ),
    WireCase(
        test_id="literal_trailing_semicolon",
        argv=("send-keys", "-l", "text;"),
        expected="send-keys -l 'text;'",
    ),
    WireCase(
        test_id="chain_keeps_bare_semicolon",
        argv=(
            "rename-window",
            "a",
            CommandSeparator(";"),
            "kill-window",
            "@2",
        ),
        expected="rename-window a ; kill-window @2",
    ),
)


@pytest.mark.parametrize(
    list(WireCase._fields),
    WIRE_CASES,
    ids=[c.test_id for c in WIRE_CASES],
)
def test_render_control_line(
    test_id: str,
    argv: tuple[str, ...],
    expected: str,
) -> None:
    """A standalone ``;`` stays a separator; other tokens are shell-quoted."""
    assert render_control_line(argv) == expected


@pytest.mark.parametrize("delimiter", ("\n", "\r"))
def test_render_control_line_encodes_physical_delimiters(delimiter: str) -> None:
    """One request always renders to one physical control-mode line."""
    rendered = render_control_line(("display-message", f"first{delimiter}second"))

    assert delimiter not in rendered


def test_render_control_line_rejects_nul() -> None:
    """A C-string command argument cannot preserve an embedded NUL."""
    with pytest.raises(ValueError, match="NUL"):
        render_control_line(("display-message", "first\0second"))


@pytest.mark.parametrize("token", ("", "x", ";;", "\nkill-server"))
def test_command_separator_rejects_non_boundary_values(token: str) -> None:
    """A structural marker can represent only tmux's exact separator token."""
    with pytest.raises(ValueError, match="exactly ';'"):
        CommandSeparator(token)


def test_command_request_rejects_nul() -> None:
    """Every engine receives only C-string-compatible command arguments."""
    with pytest.raises(ValueError, match="NUL"):
        CommandRequest.from_args("display-message", "first\0second")


def test_command_request_constructor_rejects_nul() -> None:
    """Direct construction cannot bypass the command argument invariant."""
    with pytest.raises(ValueError, match="NUL"):
        CommandRequest(args=("display-message", "first\0second"))


def test_command_request_does_not_infer_separator_from_value() -> None:
    """Only planner-authored separator tokens are structural."""
    request = CommandRequest.from_args("send-keys", "-l", ";")

    assert type(request.args[-1]) is str


def test_command_request_normalizes_hostile_string_subclass() -> None:
    """Custom string behavior cannot bypass direct-argv literal encoding."""

    class _LyingString(str):
        def endswith(
            self,
            suffix: str | tuple[str, ...],
            start: t.SupportsIndex | None = None,
            end: t.SupportsIndex | None = None,
            /,
        ) -> bool:
            return False

    request = CommandRequest.from_args(
        "display-message",
        _LyingString("literal;"),
    )

    assert type(request.args[-1]) is str
    assert encode_direct_argv(request.args)[-1] == "literal\\;"


def test_command_request_normalizes_forged_separator_subclass() -> None:
    """Only the exact structural marker type can bypass control quoting."""

    class _ForgedSeparator(CommandSeparator):
        def __new__(cls, value: str) -> Self:
            return str.__new__(cls, value)

    request = CommandRequest.from_args(
        "display-message",
        "safe",
        _ForgedSeparator("\nkill-server"),
    )
    rendered = render_control_line(request.args)

    assert type(request.args[-1]) is str
    assert "\n" not in rendered


def test_command_request_rejects_constructor_bypassed_separator() -> None:
    """Low-level string construction cannot forge an invalid exact marker."""
    forged = str.__new__(CommandSeparator, "\nkill-server")

    with pytest.raises(ValueError, match="exactly ';'"):
        CommandRequest.from_args("display-message", forged)


def test_command_request_preserves_exact_separator_marker() -> None:
    """Planner-authored markers retain their exact provenance."""
    request = CommandRequest.from_args(
        "display-message",
        CommandSeparator(";"),
        "list-sessions",
    )

    assert type(request.args[1]) is CommandSeparator


@pytest.mark.parametrize(
    "global_args",
    (
        ("-L", "socket;"),
        ("-Lsocket;",),
        ("-S", "/tmp/socket;"),
        ("-f", "tmux.conf;"),
        ("-T", "feature;"),
        ("-c", "shell-command;"),
    ),
)
def test_encode_direct_argv_preserves_global_option_values(
    global_args: tuple[str, ...],
) -> None:
    """Only subcommand arguments reach tmux's semicolon-splitting parser."""
    request = CommandRequest.from_args(
        *global_args,
        "display-message",
        "literal;",
    )

    assert encode_direct_argv(request.args) == (
        *global_args,
        "display-message",
        "literal\\;",
    )
