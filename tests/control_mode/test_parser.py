"""Tests for control mode protocol parser."""

from __future__ import annotations

import io

import pytest

from libtmux._internal.engines.control_mode.parser import ProtocolParser


def test_parser_success_response() -> None:
    """Parse successful %begin/%end block."""
    stdout = io.StringIO(
        "%begin 1234 1 0\noutput line 1\noutput line 2\n%end 1234 1 0\n"
    )

    parser = ProtocolParser(stdout)
    result = parser.parse_response(["list-sessions"])

    assert result.stdout == ["output line 1", "output line 2"]
    assert result.stderr == []
    assert result.returncode == 0


def test_parser_error_response() -> None:
    """Parse error %begin/%error block."""
    stdout = io.StringIO(
        "%begin 1234 2 0\nparse error: unknown command\n%error 1234 2 0\n"
    )

    parser = ProtocolParser(stdout)
    result = parser.parse_response(["bad-command"])

    assert result.stdout == ["parse error: unknown command"]
    assert result.returncode == 1


def test_parser_empty_output() -> None:
    """Handle response with no output lines."""
    stdout = io.StringIO("%begin 1234 3 0\n%end 1234 3 0\n")

    parser = ProtocolParser(stdout)
    result = parser.parse_response(["some-command"])

    assert result.stdout == []
    assert result.returncode == 0


def test_parser_with_notifications() -> None:
    """Queue notifications between responses."""
    stdout = io.StringIO(
        "%session-changed $0 mysession\n"
        "%window-add @1\n"
        "%begin 1234 4 0\n"
        "output\n"
        "%end 1234 4 0\n"
    )

    parser = ProtocolParser(stdout)
    result = parser.parse_response(["list-windows"])

    assert result.stdout == ["output"]
    assert result.returncode == 0
    # Notifications should be queued
    assert len(parser.notifications) == 2
    assert parser.notifications[0] == "%session-changed $0 mysession"
    assert parser.notifications[1] == "%window-add @1"


def test_parser_notification_during_response() -> None:
    """Handle notification that arrives during response."""
    stdout = io.StringIO(
        "%begin 1234 5 0\n"
        "line 1\n"
        "%sessions-changed\n"  # Notification mid-response
        "line 2\n"
        "%end 1234 5 0\n"
    )

    parser = ProtocolParser(stdout)
    result = parser.parse_response(["test"])

    # Output lines should not include notification
    assert result.stdout == ["line 1", "line 2"]
    # Notification should be queued
    assert "%sessions-changed" in parser.notifications


def test_parser_connection_closed() -> None:
    """Raise ConnectionError on EOF."""
    stdout = io.StringIO("")  # Empty stream = EOF

    parser = ProtocolParser(stdout)

    with pytest.raises(ConnectionError, match="connection closed"):
        parser.parse_response(["test"])


def test_parser_connection_closed_mid_response() -> None:
    """Raise ConnectionError if EOF during response."""
    stdout = io.StringIO(
        "%begin 1234 6 0\npartial output\n"
        # No %end - connection closed
    )

    parser = ProtocolParser(stdout)

    with pytest.raises(ConnectionError):
        parser.parse_response(["test"])


def test_parser_multiline_output() -> None:
    """Handle response with many output lines."""
    lines = [f"line {i}" for i in range(50)]
    output = "\n".join(["%begin 1234 7 0", *lines, "%end 1234 7 0"]) + "\n"

    stdout = io.StringIO(output)
    parser = ProtocolParser(stdout)
    result = parser.parse_response(["test"])

    assert len(result.stdout) == 50
    assert result.stdout[0] == "line 0"
    assert result.stdout[49] == "line 49"


def test_parser_multiple_responses_sequential() -> None:
    """Parse multiple responses sequentially."""
    stdout = io.StringIO(
        "%begin 1234 1 0\n"
        "response 1\n"
        "%end 1234 1 0\n"
        "%begin 1234 2 0\n"
        "response 2\n"
        "%end 1234 2 0\n"
    )

    parser = ProtocolParser(stdout)

    result1 = parser.parse_response(["cmd1"])
    assert result1.stdout == ["response 1"]

    result2 = parser.parse_response(["cmd2"])
    assert result2.stdout == ["response 2"]


def test_parser_preserves_empty_lines() -> None:
    """Empty lines in output are preserved."""
    stdout = io.StringIO(
        "%begin 1234 8 0\n"
        "line 1\n"
        "\n"  # Empty line
        "line 3\n"
        "%end 1234 8 0\n"
    )

    parser = ProtocolParser(stdout)
    result = parser.parse_response(["test"])

    assert len(result.stdout) == 3
    assert result.stdout[0] == "line 1"
    assert result.stdout[1] == ""
    assert result.stdout[2] == "line 3"


def test_parser_complex_output() -> None:
    """Handle complex real-world output."""
    # Simulates actual tmux list-sessions output
    stdout = io.StringIO(
        "%begin 1363006971 2 1\n"
        "0: ksh* (1 panes) [80x24] [layout b25f,80x24,0,0,2] @2 (active)\n"
        "1: bash (2 panes) [80x24] [layout b25f,80x24,0,0,3] @3\n"
        "%end 1363006971 2 1\n"
    )

    parser = ProtocolParser(stdout)
    result = parser.parse_response(["list-sessions"])

    assert len(result.stdout) == 2
    assert "ksh*" in result.stdout[0]
    assert "bash" in result.stdout[1]
    assert result.returncode == 0


def test_parser_error_with_multiline_message() -> None:
    """Handle error with multi-line error message."""
    stdout = io.StringIO(
        "%begin 1234 9 0\n"
        "error: command failed\n"
        "reason: invalid argument\n"
        "suggestion: try --help\n"
        "%error 1234 9 0\n"
    )

    parser = ProtocolParser(stdout)
    result = parser.parse_response(["bad-cmd"])

    assert result.returncode == 1
    assert len(result.stdout) == 3
    assert "error: command failed" in result.stdout[0]
