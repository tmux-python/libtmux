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
