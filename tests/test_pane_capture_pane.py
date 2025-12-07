"""Tests for Pane.capture_pane() with new flag parameters.

This module provides comprehensive parametrized tests for the capture_pane() method,
covering all flag variations: -e, -C, -J, -N, -T.
"""

from __future__ import annotations

import re
import shutil
import typing as t

import pytest

from libtmux.common import has_gte_version
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.session import Session


# =============================================================================
# Test Case Definition
# =============================================================================


class CapturePaneCase(t.NamedTuple):
    """Test case for capture_pane() parameter variations.

    This NamedTuple defines the parameters for parametrized tests covering
    all combinations of capture_pane() flags.

    Attributes
    ----------
    test_id : str
        Unique identifier for the test case, used in pytest output.
    command : str
        Shell command to execute in the pane.
    escape_sequences : bool
        Whether to include ANSI escape sequences (-e flag).
    escape_non_printable : bool
        Whether to escape non-printable chars as octal (-C flag).
    join_wrapped : bool
        Whether to join wrapped lines (-J flag).
    preserve_trailing : bool
        Whether to preserve trailing spaces (-N flag).
    trim_trailing : bool
        Whether to trim trailing positions (-T flag).
    expected_pattern : str | None
        Regex pattern that must match in the output.
    not_expected_pattern : str | None
        Regex pattern that must NOT match in the output.
    min_tmux_version : str | None
        Minimum tmux version required for this test.
    """

    test_id: str
    command: str
    escape_sequences: bool
    escape_non_printable: bool
    join_wrapped: bool
    preserve_trailing: bool
    trim_trailing: bool
    expected_pattern: str | None
    not_expected_pattern: str | None
    min_tmux_version: str | None


# =============================================================================
# Test Cases
# =============================================================================


CAPTURE_PANE_CASES: list[CapturePaneCase] = [
    # --- Basic Tests (no flags) ---
    CapturePaneCase(
        test_id="basic_capture",
        command='echo "hello world"',
        escape_sequences=False,
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"hello world",
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    CapturePaneCase(
        test_id="basic_multiline",
        command='printf "line1\\nline2\\nline3\\n"',
        escape_sequences=False,
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"line1.*line2.*line3",
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    # --- escape_sequences (-e) Tests ---
    CapturePaneCase(
        test_id="escape_sequences_red",
        command='printf "\\033[31mRED\\033[0m"',
        escape_sequences=True,
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"\x1b\[31m",  # Should contain ANSI red code
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    CapturePaneCase(
        test_id="escape_sequences_green",
        command='printf "\\033[32mGREEN\\033[0m"',
        escape_sequences=True,
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"\x1b\[32m",  # Should contain ANSI green code
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    CapturePaneCase(
        test_id="escape_sequences_bold",
        command='printf "\\033[1mBOLD\\033[0m"',
        escape_sequences=True,
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"\x1b\[1m",  # Should contain ANSI bold code
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    CapturePaneCase(
        test_id="no_escape_sequences",
        command='printf "\\033[31mRED\\033[0m"',
        escape_sequences=False,  # Should NOT include ANSI codes
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"RED",
        not_expected_pattern=r"\x1b",  # Should NOT have escape char
        min_tmux_version=None,
    ),
    # --- escape_non_printable (-C) Tests ---
    CapturePaneCase(
        test_id="escape_non_printable_basic",
        command='printf "\\001\\002\\003"',
        escape_sequences=False,
        escape_non_printable=True,
        join_wrapped=False,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"\\00[123]",  # Octal escapes like \001, \002, \003
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    CapturePaneCase(
        test_id="escape_non_printable_tab",
        command='printf "a\\tb"',
        escape_sequences=False,
        escape_non_printable=True,
        join_wrapped=False,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"a.*b",  # Tab may be preserved or escaped
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    # --- join_wrapped (-J) Tests ---
    CapturePaneCase(
        test_id="join_wrapped_long_line",
        command='printf "%s" "$(python3 -c \'print("x" * 200)\')"',
        escape_sequences=False,
        escape_non_printable=False,
        join_wrapped=True,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"x{100,}",  # Should have many x's joined
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    CapturePaneCase(
        test_id="join_wrapped_numbers",
        command='printf "%s" "$(seq -s "" 1 100)"',
        escape_sequences=False,
        escape_non_printable=False,
        join_wrapped=True,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"123.*99100",  # Numbers should be joined
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    # --- preserve_trailing (-N) Tests ---
    CapturePaneCase(
        test_id="preserve_trailing_spaces",
        command='printf "text   \\n"',  # 3 trailing spaces
        escape_sequences=False,
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=True,
        trim_trailing=False,
        expected_pattern=r"text   ",  # Should have trailing spaces
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    CapturePaneCase(
        test_id="no_preserve_trailing",
        command='printf "text   \\n"',  # 3 trailing spaces
        escape_sequences=False,
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=False,  # Should trim trailing spaces
        trim_trailing=False,
        expected_pattern=r"text",
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    # --- trim_trailing (-T) Tests ---
    CapturePaneCase(
        test_id="trim_trailing_basic",
        command='echo "short"',
        escape_sequences=False,
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=False,
        trim_trailing=True,
        expected_pattern=r"short",
        not_expected_pattern=None,
        min_tmux_version="3.4",  # -T flag requires tmux 3.4+
    ),
    # --- Combination Tests ---
    CapturePaneCase(
        test_id="escape_sequences_with_join",
        command='printf "\\033[32mGREEN TEXT\\033[0m"',
        escape_sequences=True,
        escape_non_printable=False,
        join_wrapped=True,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"\x1b\[32m",  # Should have ANSI codes
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    CapturePaneCase(
        test_id="join_with_preserve_trailing",
        command='printf "%s   " "$(python3 -c \'print("z" * 100)\')"',
        escape_sequences=False,
        escape_non_printable=False,
        join_wrapped=True,
        preserve_trailing=True,
        trim_trailing=False,
        expected_pattern=r"z{50,}",  # Should have z's
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    CapturePaneCase(
        test_id="all_flags_except_trim",
        command='printf "\\033[34mBLUE: %s   \\033[0m" "test"',
        escape_sequences=True,
        escape_non_printable=True,
        join_wrapped=True,
        preserve_trailing=True,
        trim_trailing=False,
        expected_pattern=r"\x1b\[34m|BLUE",  # Should have color or text
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
]


# =============================================================================
# Parametrized Test
# =============================================================================


@pytest.mark.parametrize(
    list(CapturePaneCase._fields),
    CAPTURE_PANE_CASES,
    ids=[case.test_id for case in CAPTURE_PANE_CASES],
)
def test_capture_pane_flags(
    test_id: str,
    command: str,
    escape_sequences: bool,
    escape_non_printable: bool,
    join_wrapped: bool,
    preserve_trailing: bool,
    trim_trailing: bool,
    expected_pattern: str | None,
    not_expected_pattern: str | None,
    min_tmux_version: str | None,
    session: Session,
) -> None:
    """Test capture_pane() with various flag combinations.

    This parametrized test covers all combinations of capture_pane() flags
    including escape_sequences, escape_non_printable, join_wrapped,
    preserve_trailing, and trim_trailing.

    Parameters
    ----------
    test_id : str
        Unique identifier for the test case.
    command : str
        Shell command to execute.
    escape_sequences : bool
        Whether to include ANSI escape sequences.
    escape_non_printable : bool
        Whether to escape non-printable chars.
    join_wrapped : bool
        Whether to join wrapped lines.
    preserve_trailing : bool
        Whether to preserve trailing spaces.
    trim_trailing : bool
        Whether to trim trailing positions.
    expected_pattern : str | None
        Regex pattern that must match.
    not_expected_pattern : str | None
        Regex pattern that must NOT match.
    min_tmux_version : str | None
        Minimum tmux version required.
    session : Session
        pytest fixture providing tmux session.
    """
    # Skip if tmux version too old
    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    # Find env for predictable shell
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    # Create pane with predictable shell
    window = session.new_window(
        attach=True,
        window_name=f"cap_{test_id[:10]}",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    # Wait for shell prompt
    def prompt_ready() -> bool:
        return "$" in "\n".join(pane.capture_pane())

    retry_until(prompt_ready, 2, raises=True)

    # Send command with a unique marker to detect completion
    marker = f"__DONE_{test_id}__"
    full_command = f'{command}; echo "{marker}"'
    pane.send_keys(full_command, literal=False, suppress_history=False)

    # Wait for marker to appear
    def command_complete() -> bool:
        output = "\n".join(pane.capture_pane())
        return marker in output

    retry_until(command_complete, 5, raises=True)

    # Capture with specified flags
    output = pane.capture_pane(
        escape_sequences=escape_sequences,
        escape_non_printable=escape_non_printable,
        join_wrapped=join_wrapped,
        preserve_trailing=preserve_trailing,
        trim_trailing=trim_trailing,
    )
    output_str = "\n".join(output)

    # Verify expected pattern matches
    if expected_pattern:
        assert re.search(expected_pattern, output_str, re.DOTALL), (
            f"Expected pattern '{expected_pattern}' not found in output:\n{output_str}"
        )

    # Verify not_expected pattern does NOT match
    if not_expected_pattern:
        assert not re.search(not_expected_pattern, output_str, re.DOTALL), (
            f"Unexpected pattern '{not_expected_pattern}' found in output"
        )


# =============================================================================
# Additional Targeted Tests
# =============================================================================


def test_capture_pane_backward_compatible(session: Session) -> None:
    """Test that capture_pane() works without any new parameters.

    This ensures backward compatibility with existing code that doesn't
    use the new flag parameters.
    """
    pane = session.active_window.split(shell="sh")

    def prompt_ready() -> bool:
        return "$" in "\n".join(pane.capture_pane())

    retry_until(prompt_ready, 2, raises=True)

    pane.send_keys('echo "backward compat test"', enter=True)

    def output_ready() -> bool:
        return "backward compat test" in "\n".join(pane.capture_pane())

    retry_until(output_ready, 2, raises=True)

    # Call with no new parameters - should work exactly as before
    output = pane.capture_pane()
    assert isinstance(output, list)
    assert any("backward compat test" in line for line in output)


def test_capture_pane_start_end_with_flags(session: Session) -> None:
    """Test that start/end parameters work with new flags."""
    pane = session.active_window.split(shell="sh")

    def prompt_ready() -> bool:
        return "$" in "\n".join(pane.capture_pane())

    retry_until(prompt_ready, 2, raises=True)

    # Generate some output
    pane.send_keys('echo "line1"; echo "line2"; echo "line3"', enter=True)

    def output_ready() -> bool:
        return "line3" in "\n".join(pane.capture_pane())

    retry_until(output_ready, 2, raises=True)

    # Capture with start/end AND new flags
    output = pane.capture_pane(
        start=0,
        end="-",
        preserve_trailing=True,
    )
    assert isinstance(output, list)
    assert len(output) > 0


def test_capture_pane_trim_trailing_warning(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that trim_trailing issues a warning on tmux < 3.4."""
    import warnings

    from libtmux import common

    # Mock has_gte_version to return False for 3.4
    monkeypatch.setattr(common, "has_gte_version", lambda v: v != "3.4")

    pane = session.active_window.split(shell="sh")

    def prompt_ready() -> bool:
        return "$" in "\n".join(pane.capture_pane())

    retry_until(prompt_ready, 2, raises=True)

    # Should issue a warning
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        pane.capture_pane(trim_trailing=True)

        # Check warning was issued
        assert len(w) == 1
        assert "trim_trailing requires tmux 3.4+" in str(w[0].message)
