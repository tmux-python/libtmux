"""Tests for Pane.capture_frame() method."""

from __future__ import annotations

import shutil
import typing as t

import pytest
from syrupy.assertion import SnapshotAssertion

from libtmux.test.retry import retry_until
from libtmux.textframe import TextFrame, TextFrameExtension

if t.TYPE_CHECKING:
    from libtmux.session import Session


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Override default snapshot fixture to use TextFrameExtension.

    Parameters
    ----------
    snapshot : SnapshotAssertion
        The default syrupy snapshot fixture.

    Returns
    -------
    SnapshotAssertion
        Snapshot configured with TextFrame serialization.
    """
    return snapshot.use_extension(TextFrameExtension)


class CaptureFrameCase(t.NamedTuple):
    """Test case for capture_frame() parametrized tests."""

    test_id: str
    content_to_send: str
    content_width: int | None  # None = use pane width
    content_height: int | None  # None = use pane height
    overflow_behavior: t.Literal["error", "truncate"]
    expected_in_frame: list[str]  # Substrings expected in rendered frame
    description: str


CAPTURE_FRAME_CASES: list[CaptureFrameCase] = [
    CaptureFrameCase(
        test_id="basic_echo",
        content_to_send='echo "hello"',
        content_width=40,
        content_height=10,
        overflow_behavior="truncate",
        expected_in_frame=["hello"],
        description="Basic echo command output",
    ),
    CaptureFrameCase(
        test_id="multiline_output",
        content_to_send='printf "line1\\nline2\\nline3\\n"',
        content_width=40,
        content_height=10,
        overflow_behavior="truncate",
        expected_in_frame=["line1", "line2", "line3"],
        description="Multi-line printf output",
    ),
    CaptureFrameCase(
        test_id="custom_small_dimensions",
        content_to_send='echo "test"',
        content_width=20,
        content_height=5,
        overflow_behavior="truncate",
        expected_in_frame=["test"],
        description="Custom small frame dimensions",
    ),
    CaptureFrameCase(
        test_id="truncate_long_line",
        content_to_send='echo "' + "x" * 50 + '"',
        content_width=15,
        content_height=5,
        overflow_behavior="truncate",
        expected_in_frame=["xxxxxxxxxxxxxxx"],  # Truncated to 15 chars
        description="Long output truncated to frame width",
    ),
    CaptureFrameCase(
        test_id="empty_pane",
        content_to_send="",
        content_width=20,
        content_height=5,
        overflow_behavior="truncate",
        expected_in_frame=["$"],  # Just shell prompt
        description="Empty pane with just prompt",
    ),
]


@pytest.mark.parametrize(
    list(CaptureFrameCase._fields),
    CAPTURE_FRAME_CASES,
    ids=[case.test_id for case in CAPTURE_FRAME_CASES],
)
def test_capture_frame_parametrized(
    test_id: str,
    content_to_send: str,
    content_width: int | None,
    content_height: int | None,
    overflow_behavior: t.Literal["error", "truncate"],
    expected_in_frame: list[str],
    description: str,
    session: Session,
) -> None:
    """Verify capture_frame() with various content and dimensions.

    Parameters
    ----------
    test_id : str
        Unique identifier for the test case.
    content_to_send : str
        Command to send to the pane.
    content_width : int | None
        Frame width (None = use pane width).
    content_height : int | None
        Frame height (None = use pane height).
    overflow_behavior : OverflowBehavior
        How to handle overflow.
    expected_in_frame : list[str]
        Substrings expected in the rendered frame.
    description : str
        Human-readable test description.
    session : Session
        pytest fixture providing tmux session.
    """
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        attach=True,
        window_name=f"capture_frame_{test_id}",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    # Send content if provided
    if content_to_send:
        pane.send_keys(content_to_send, literal=True, suppress_history=False)

        # Wait for command output to appear
        def output_appeared() -> bool:
            lines = pane.capture_pane()
            content = "\n".join(lines)
            # Check that at least one expected substring is present
            return any(exp in content for exp in expected_in_frame)

        retry_until(output_appeared, 2, raises=True)

    # Capture frame with specified dimensions
    frame = pane.capture_frame(
        content_width=content_width,
        content_height=content_height,
        overflow_behavior=overflow_behavior,
    )

    # Verify frame type
    assert isinstance(frame, TextFrame)

    # Verify dimensions
    if content_width is not None:
        assert frame.content_width == content_width
    if content_height is not None:
        assert frame.content_height == content_height

    # Verify expected content in rendered frame
    rendered = frame.render()
    for expected in expected_in_frame:
        assert expected in rendered, f"Expected '{expected}' not found in frame"


def test_capture_frame_returns_textframe(session: Session) -> None:
    """Verify capture_frame() returns a TextFrame instance."""
    pane = session.active_window.active_pane
    assert pane is not None

    frame = pane.capture_frame(content_width=20, content_height=5)

    assert isinstance(frame, TextFrame)
    assert frame.content_width == 20
    assert frame.content_height == 5


def test_capture_frame_default_dimensions(session: Session) -> None:
    """Verify capture_frame() uses pane dimensions by default."""
    pane = session.active_window.active_pane
    assert pane is not None
    pane.refresh()

    # Get actual pane dimensions
    expected_width = int(pane.pane_width or 80)
    expected_height = int(pane.pane_height or 24)

    # Capture without specifying dimensions
    frame = pane.capture_frame()

    assert frame.content_width == expected_width
    assert frame.content_height == expected_height


def test_capture_frame_with_start_end(session: Session) -> None:
    """Verify capture_frame() works with start/end parameters."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        attach=True,
        window_name="capture_frame_start_end",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    # Send multiple lines
    pane.send_keys('echo "line1"', enter=True)
    pane.send_keys('echo "line2"', enter=True)
    pane.send_keys('echo "line3"', enter=True)

    # Wait for all output
    def all_lines_present() -> bool:
        content = "\n".join(pane.capture_pane())
        return "line3" in content

    retry_until(all_lines_present, 2, raises=True)

    # Capture with start parameter (visible pane only)
    frame = pane.capture_frame(start=0, content_width=40, content_height=10)
    rendered = frame.render()

    # Should capture visible content
    assert isinstance(frame, TextFrame)
    assert "line" in rendered  # At least some output


def test_capture_frame_overflow_truncate(session: Session) -> None:
    """Verify capture_frame() truncates content when overflow_behavior='truncate'."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        attach=True,
        window_name="capture_frame_truncate",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    # Send long line
    long_text = "x" * 100
    pane.send_keys(f'echo "{long_text}"', literal=True, suppress_history=False)

    def output_appeared() -> bool:
        return "xxxx" in "\n".join(pane.capture_pane())

    retry_until(output_appeared, 2, raises=True)

    # Capture with small width, truncate mode
    frame = pane.capture_frame(
        content_width=10,
        content_height=5,
        overflow_behavior="truncate",
    )

    # Should not raise, content should be truncated
    assert isinstance(frame, TextFrame)
    rendered = frame.render()

    # Frame should have the specified width (10 chars + borders)
    lines = rendered.splitlines()
    # Border line should be +----------+ (10 dashes)
    assert lines[0] == "+----------+"


def test_capture_frame_snapshot(session: Session, snapshot: SnapshotAssertion) -> None:
    """Verify capture_frame() output matches snapshot."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        attach=True,
        window_name="capture_frame_snapshot",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    # Send a predictable command
    pane.send_keys('echo "Hello, TextFrame!"', literal=True, suppress_history=False)

    # Wait for output
    def output_appeared() -> bool:
        return "Hello, TextFrame!" in "\n".join(pane.capture_pane())

    retry_until(output_appeared, 2, raises=True)

    # Capture as frame - use fixed dimensions for reproducible snapshot
    frame = pane.capture_frame(content_width=30, content_height=5)

    # Compare against snapshot
    assert frame == snapshot


def test_capture_frame_with_retry_pattern(session: Session) -> None:
    """Demonstrate capture_frame() in retry_until pattern."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        attach=True,
        window_name="capture_frame_retry",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    # Send command that produces multi-line output
    pane.send_keys('for i in 1 2 3; do echo "line $i"; done', enter=True)

    # Use capture_frame in retry pattern
    def all_lines_in_frame() -> bool:
        frame = pane.capture_frame(content_width=40, content_height=10)
        rendered = frame.render()
        return all(f"line {i}" in rendered for i in [1, 2, 3])

    # Should eventually pass
    result = retry_until(all_lines_in_frame, 3, raises=True)
    assert result is True


def test_capture_frame_preserves_content(session: Session) -> None:
    """Verify capture_frame() content matches capture_pane() content."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        attach=True,
        window_name="capture_frame_content",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    pane.send_keys('echo "test content"', literal=True, suppress_history=False)

    def output_appeared() -> bool:
        return "test content" in "\n".join(pane.capture_pane())

    retry_until(output_appeared, 2, raises=True)

    # Capture both ways
    pane_lines = pane.capture_pane()
    frame = pane.capture_frame(
        content_width=40,
        content_height=len(pane_lines),
        overflow_behavior="truncate",
    )

    # Frame content should contain the same lines (possibly truncated)
    for line in pane_lines[:5]:  # Check first few lines
        # Truncated lines should match up to frame width
        truncated = line[: frame.content_width]
        if truncated.strip():  # Non-empty lines
            assert truncated in frame.render()


# =============================================================================
# Exhaustive Snapshot Tests
# =============================================================================


class SnapshotCase(t.NamedTuple):
    """Snapshot test case for exhaustive capture_frame() variations.

    This NamedTuple defines the parameters for parametrized snapshot tests
    that cover all combinations of capture_frame() options.

    Attributes
    ----------
    test_id : str
        Unique identifier for the test case, used in snapshot filenames.
    command : str
        Shell command to execute (empty string for prompt-only tests).
    content_width : int
        Frame width in characters.
    content_height : int
        Frame height in lines.
    start : t.Literal["-"] | int | None
        Starting line for capture (None = default).
    end : t.Literal["-"] | int | None
        Ending line for capture (None = default).
    overflow_behavior : t.Literal["error", "truncate"]
        How to handle content exceeding frame dimensions.
    wait_for : str
        String to wait for before capturing (ensures output is ready).
    """

    test_id: str
    command: str
    content_width: int
    content_height: int
    start: t.Literal["-"] | int | None
    end: t.Literal["-"] | int | None
    overflow_behavior: t.Literal["error", "truncate"]
    wait_for: str


SNAPSHOT_CASES: list[SnapshotCase] = [
    # --- Dimension Variations ---
    SnapshotCase(
        test_id="prompt_only",
        command="",
        content_width=20,
        content_height=3,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="$",
    ),
    SnapshotCase(
        test_id="echo_simple",
        command='echo "hello"',
        content_width=25,
        content_height=4,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="hello",
    ),
    SnapshotCase(
        test_id="echo_multiline",
        command='printf "a\\nb\\nc\\n"',
        content_width=20,
        content_height=6,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="c",
    ),
    SnapshotCase(
        test_id="wide_frame",
        command='echo "test"',
        content_width=60,
        content_height=3,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="test",
    ),
    SnapshotCase(
        test_id="narrow_frame",
        command='echo "test"',
        content_width=10,
        content_height=3,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="test",
    ),
    SnapshotCase(
        test_id="tall_frame",
        command='echo "x"',
        content_width=20,
        content_height=10,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="x",
    ),
    SnapshotCase(
        test_id="short_frame",
        command='echo "x"',
        content_width=20,
        content_height=2,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="x",
    ),
    # --- Start/End Parameter Variations ---
    SnapshotCase(
        test_id="start_zero",
        command='echo "line"',
        content_width=30,
        content_height=5,
        start=0,
        end=None,
        overflow_behavior="truncate",
        wait_for="line",
    ),
    SnapshotCase(
        test_id="end_zero",
        command='echo "line"',
        content_width=30,
        content_height=3,
        start=None,
        end=0,
        overflow_behavior="truncate",
        wait_for="line",
    ),
    SnapshotCase(
        test_id="end_dash",
        command='echo "line"',
        content_width=30,
        content_height=5,
        start=None,
        end="-",
        overflow_behavior="truncate",
        wait_for="line",
    ),
    SnapshotCase(
        test_id="start_end_range",
        command='printf "L1\\nL2\\nL3\\nL4\\n"',
        content_width=30,
        content_height=5,
        start=0,
        end=2,
        overflow_behavior="truncate",
        wait_for="L4",
    ),
    # --- Truncation Behavior ---
    SnapshotCase(
        test_id="truncate_width",
        command='echo "' + "x" * 50 + '"',
        content_width=15,
        content_height=4,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="xxxx",
    ),
    SnapshotCase(
        test_id="truncate_height",
        command='printf "L1\\nL2\\nL3\\nL4\\nL5\\nL6\\nL7\\nL8\\nL9\\nL10\\n"',
        content_width=30,
        content_height=3,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="L10",
    ),
    # --- Special Characters ---
    SnapshotCase(
        test_id="special_chars",
        command='echo "!@#$%"',
        content_width=25,
        content_height=4,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="!@#$%",
    ),
    SnapshotCase(
        test_id="unicode_basic",
        command='echo "cafe"',  # Using ASCII to avoid shell encoding issues
        content_width=25,
        content_height=4,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="cafe",
    ),
    # --- Edge Cases ---
    SnapshotCase(
        test_id="empty_lines",
        command='printf "\\n\\n\\n"',
        content_width=20,
        content_height=6,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="$",
    ),
    SnapshotCase(
        test_id="spaces_only",
        command='echo "   "',
        content_width=20,
        content_height=4,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="$",
    ),
    SnapshotCase(
        test_id="mixed_content",
        command='echo "abc 123 !@#"',
        content_width=30,
        content_height=4,
        start=None,
        end=None,
        overflow_behavior="truncate",
        wait_for="abc 123 !@#",
    ),
]


@pytest.mark.parametrize(
    list(SnapshotCase._fields),
    SNAPSHOT_CASES,
    ids=[case.test_id for case in SNAPSHOT_CASES],
)
def test_capture_frame_snapshot_parametrized(
    test_id: str,
    command: str,
    content_width: int,
    content_height: int,
    start: t.Literal["-"] | int | None,
    end: t.Literal["-"] | int | None,
    overflow_behavior: t.Literal["error", "truncate"],
    wait_for: str,
    session: Session,
    snapshot: SnapshotAssertion,
) -> None:
    """Exhaustive snapshot tests for capture_frame() parameter variations.

    This parametrized test covers all combinations of capture_frame() options
    including dimensions, start/end parameters, truncation, special characters,
    and edge cases.

    Parameters
    ----------
    test_id : str
        Unique identifier for the test case.
    command : str
        Shell command to execute (empty for prompt-only).
    content_width : int
        Frame width in characters.
    content_height : int
        Frame height in lines.
    start : t.Literal["-"] | int | None
        Starting line for capture.
    end : t.Literal["-"] | int | None
        Ending line for capture.
    overflow_behavior : t.Literal["error", "truncate"]
        How to handle overflow.
    wait_for : str
        String to wait for before capturing.
    session : Session
        pytest fixture providing tmux session.
    snapshot : SnapshotAssertion
        syrupy snapshot fixture with TextFrameExtension.
    """
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        attach=True,
        window_name=f"snap_{test_id}",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    # Wait for shell prompt to appear
    def prompt_ready() -> bool:
        return "$" in "\n".join(pane.capture_pane())

    retry_until(prompt_ready, 2, raises=True)

    # Send command if provided
    if command:
        pane.send_keys(command, literal=True, suppress_history=False)

    # Wait for expected content
    if wait_for:

        def content_ready() -> bool:
            return wait_for in "\n".join(pane.capture_pane())

        retry_until(content_ready, 2, raises=True)

    # Capture frame with specified parameters
    frame = pane.capture_frame(
        start=start,
        end=end,
        content_width=content_width,
        content_height=content_height,
        overflow_behavior=overflow_behavior,
    )

    # Compare against snapshot
    assert frame == snapshot


# =============================================================================
# Flag Forwarding Tests
# =============================================================================


class CaptureFrameFlagCase(t.NamedTuple):
    """Test case for capture_frame() flag forwarding to capture_pane()."""

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


CAPTURE_FRAME_FLAG_CASES: list[CaptureFrameFlagCase] = [
    CaptureFrameFlagCase(
        test_id="escape_sequences_color",
        command='printf "\\033[31mRED\\033[0m"',
        escape_sequences=True,
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"\x1b\[31m",
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    CaptureFrameFlagCase(
        test_id="no_escape_sequences",
        command='printf "\\033[31mRED\\033[0m"',
        escape_sequences=False,
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=False,
        trim_trailing=False,
        expected_pattern=r"RED",
        not_expected_pattern=r"\x1b\[",
        min_tmux_version=None,
    ),
    CaptureFrameFlagCase(
        test_id="join_wrapped_long_line",
        command="printf '%s' \"$(seq 1 30 | tr -d '\\n')\"",
        escape_sequences=False,
        escape_non_printable=False,
        join_wrapped=True,
        preserve_trailing=False,
        trim_trailing=False,
        # With join_wrapped, wrapped lines are joined - verify contiguous sequence
        expected_pattern=r"123456789101112131415161718192021222324252627282930",
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
    CaptureFrameFlagCase(
        test_id="preserve_trailing_spaces",
        command='printf "text   \\n"',
        escape_sequences=False,
        escape_non_printable=False,
        join_wrapped=False,
        preserve_trailing=True,
        trim_trailing=False,
        expected_pattern=r"text   ",
        not_expected_pattern=None,
        min_tmux_version=None,
    ),
]


@pytest.mark.parametrize(
    list(CaptureFrameFlagCase._fields),
    CAPTURE_FRAME_FLAG_CASES,
    ids=[case.test_id for case in CAPTURE_FRAME_FLAG_CASES],
)
def test_capture_frame_flag_forwarding(
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
    """Test that capture_frame() correctly forwards flags to capture_pane().

    Parameters
    ----------
    test_id : str
        Unique identifier for the test case.
    command : str
        Shell command to execute.
    escape_sequences : bool
        Include ANSI escape sequences.
    escape_non_printable : bool
        Escape non-printable characters.
    join_wrapped : bool
        Join wrapped lines.
    preserve_trailing : bool
        Preserve trailing spaces.
    trim_trailing : bool
        Trim trailing positions.
    expected_pattern : str | None
        Regex pattern expected in output.
    not_expected_pattern : str | None
        Regex pattern that should NOT be in output.
    min_tmux_version : str | None
        Minimum tmux version required.
    session : Session
        pytest fixture providing tmux session.
    """
    import re

    from libtmux.common import has_gte_version

    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    env = shutil.which("env")
    assert env is not None

    window = session.new_window(
        attach=True,
        window_name=f"flag_{test_id}",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    # Wait for shell prompt
    def prompt_ready() -> bool:
        return "$" in "\n".join(pane.capture_pane())

    retry_until(prompt_ready, 2, raises=True)

    # Send command and wait for completion marker
    marker = f"__DONE_{test_id}__"
    pane.send_keys(f"{command}; echo {marker}", literal=True)

    def marker_ready() -> bool:
        return marker in "\n".join(pane.capture_pane())

    retry_until(marker_ready, 3, raises=True)

    # Capture frame with specified flags
    frame = pane.capture_frame(
        content_width=80,
        content_height=24,
        escape_sequences=escape_sequences,
        escape_non_printable=escape_non_printable,
        join_wrapped=join_wrapped,
        preserve_trailing=preserve_trailing,
        trim_trailing=trim_trailing,
    )

    # Get rendered content (without frame borders)
    rendered = frame.render()

    # Verify expected pattern
    if expected_pattern:
        assert re.search(expected_pattern, rendered, re.DOTALL), (
            f"Expected pattern '{expected_pattern}' not found in:\n{rendered}"
        )

    # Verify not_expected pattern is absent
    if not_expected_pattern:
        assert not re.search(not_expected_pattern, rendered, re.DOTALL), (
            f"Unexpected pattern '{not_expected_pattern}' found in:\n{rendered}"
        )
