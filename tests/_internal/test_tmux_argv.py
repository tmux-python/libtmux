"""Tests for direct tmux argv parsing and normalization."""

from __future__ import annotations

import typing as t

import pytest

from libtmux._internal.tmux_argv import (
    encode_direct_argv,
    parse_client_options,
    split_direct_argv,
)
from libtmux.engines.base import CommandSeparator

if t.TYPE_CHECKING:
    from libtmux.session import Session


class SplitCase(t.NamedTuple):
    """Expected tmux client and command argv regions.

    Attributes
    ----------
    args : tuple[object, ...]
        Arguments passed after the executable.
    global_args : tuple[str, ...]
        Expected client-global prefix.
    command_argv : tuple[str, ...]
        Expected command region.
    test_id : str
        Pytest parameter identifier.
    """

    args: tuple[object, ...]
    global_args: tuple[str, ...]
    command_argv: tuple[str, ...]
    test_id: str


SPLIT_CASES = (
    SplitCase(
        args=("display-message", "-p", ";"),
        global_args=(),
        command_argv=("display-message", "-p", ";"),
        test_id="no-client-options",
    ),
    SplitCase(
        args=(
            "-L",
            "named-socket",
            "-S/tmp/tmux.sock",
            "-f",
            "/dev/null",
            "-2u",
            "display-message",
            "-p",
            ";",
        ),
        global_args=(
            "-L",
            "named-socket",
            "-S/tmp/tmux.sock",
            "-f",
            "/dev/null",
            "-2u",
        ),
        command_argv=("display-message", "-p", ";"),
        test_id="attached-separate-values-and-flags",
    ),
    SplitCase(
        args=("-L", ";", "display-message", "-p", ";"),
        global_args=("-L", ";"),
        command_argv=("display-message", "-p", ";"),
        test_id="semicolon-client-option-value",
    ),
    SplitCase(
        args=("-uLsocket;", "-f/dev/null;", "--", "display-message"),
        global_args=("-uLsocket;", "-f/dev/null;", "--"),
        command_argv=("display-message",),
        test_id="clustered-attached-values-and-end-marker",
    ),
)


@pytest.mark.parametrize(
    SplitCase._fields,
    SPLIT_CASES,
    ids=[case.test_id for case in SPLIT_CASES],
)
def test_split_direct_argv_follows_tmux_client_getopt(
    args: tuple[object, ...],
    global_args: tuple[str, ...],
    command_argv: tuple[str, ...],
    test_id: str,
) -> None:
    """The split consumes complete client options before command data."""
    del test_id
    direct = split_direct_argv(args)

    assert direct.global_args == global_args
    assert direct.command_argv == command_argv


def test_encode_direct_argv_protects_only_untyped_command_data() -> None:
    """Only an explicit separator survives as tmux command structure."""
    encoded = encode_direct_argv(
        (
            "-Lsocket;",
            "display-message",
            ";",
            "evil;",
            r"escaped\;",
            r"double\\;",
            "interior;value",
            CommandSeparator(";"),
        ),
    )

    assert encoded == (
        "-Lsocket;",
        "display-message",
        r"\;",
        r"evil\;",
        r"escaped\;",
        r"double\\;",
        "interior;value",
        ";",
    )


def test_encode_direct_argv_rejects_forged_separator() -> None:
    """A forged typed value cannot smuggle command text past normalization."""
    forged = str.__new__(CommandSeparator, "evil;")

    with pytest.raises(ValueError, match="must be exactly"):
        encode_direct_argv(("display-message", forged))


def test_client_option_parser_rejects_nul_in_separate_value() -> None:
    """A separately consumed client value obeys the C-string invariant."""
    with pytest.raises(ValueError, match="NUL"):
        parse_client_options(("-L", "bad\0name", "display-message"))


def test_subprocess_treats_trailing_semicolon_as_literal_data(
    session: Session,
) -> None:
    """A real subprocess request receives a plain suffix literally."""
    proc = session.server.cmd("display-message", "-p", "literal;")

    assert proc.returncode == 0
    assert proc.stdout == ["literal;"]


def test_subprocess_preserves_escaped_trailing_semicolon(session: Session) -> None:
    r"""A real subprocess request preserves established ``\;`` input."""
    proc = session.server.cmd("display-message", "-p", r"escaped\;")

    assert proc.returncode == 0
    assert proc.stdout == ["escaped;"]


def test_subprocess_renders_explicit_separator_structurally(session: Session) -> None:
    """The typed separator executes two commands in one invocation."""
    proc = session.server.cmd(
        "display-message",
        "-p",
        "first",
        CommandSeparator(";"),
        "display-message",
        "-p",
        "second",
    )

    assert proc.returncode == 0
    assert proc.stdout == ["first", "second"]


def test_semicolon_suffix_cannot_inject_kill_server(session: Session) -> None:
    """A value suffix cannot turn the following token into a command."""
    result = session.server.cmd(
        "set-option",
        "-g",
        "@libtmux_injection_probe",
        "evil;",
        "kill-server",
    )

    assert result.returncode != 0
    assert session.server.is_alive()
