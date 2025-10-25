"""Tests for ControlModeResult."""

from __future__ import annotations

from libtmux._internal.engines.control_mode.result import ControlModeResult


def test_result_has_required_attributes() -> None:
    """ControlModeResult has stdout, stderr, returncode, cmd attributes."""
    result = ControlModeResult(
        stdout=["line1", "line2"],
        stderr=[],
        returncode=0,
        cmd=["tmux", "-C", "list-sessions"],
    )

    assert hasattr(result, "stdout")
    assert hasattr(result, "stderr")
    assert hasattr(result, "returncode")
    assert hasattr(result, "cmd")


def test_result_attributes_accessible() -> None:
    """All attributes are accessible and have correct values."""
    result = ControlModeResult(
        stdout=["output1", "output2"],
        stderr=["error1"],
        returncode=1,
        cmd=["tmux", "-C", "invalid-command"],
    )

    assert result.stdout == ["output1", "output2"]
    assert result.stderr == ["error1"]
    assert result.returncode == 1
    assert result.cmd == ["tmux", "-C", "invalid-command"]


def test_result_empty_stdout() -> None:
    """ControlModeResult handles empty stdout."""
    result = ControlModeResult(
        stdout=[],
        stderr=[],
        returncode=0,
        cmd=["tmux", "-C", "some-command"],
    )

    assert result.stdout == []
    assert len(result.stdout) == 0
    assert bool(result.stdout) is False


def test_result_empty_stderr() -> None:
    """ControlModeResult handles empty stderr."""
    result = ControlModeResult(
        stdout=["output"],
        stderr=[],
        returncode=0,
        cmd=["tmux", "-C", "list-sessions"],
    )

    assert result.stderr == []
    assert bool(result.stderr) is False  # Empty list is falsy


def test_result_repr() -> None:
    """ControlModeResult has informative repr."""
    result = ControlModeResult(
        stdout=["line1", "line2", "line3"],
        stderr=["error"],
        returncode=1,
        cmd=["tmux", "-C", "test"],
    )

    repr_str = repr(result)
    assert "ControlModeResult" in repr_str
    assert "returncode=1" in repr_str
    assert "stdout_lines=3" in repr_str
    assert "stderr_lines=1" in repr_str


def test_result_duck_types_as_tmux_cmd() -> None:
    """ControlModeResult has same interface as tmux_cmd."""
    # Create both types
    result = ControlModeResult(
        stdout=["test"],
        stderr=[],
        returncode=0,
        cmd=["tmux", "-C", "list-sessions"],
    )

    # Both should have same attributes
    tmux_attrs = {"stdout", "stderr", "returncode", "cmd"}
    result_attrs = {attr for attr in dir(result) if not attr.startswith("_")}

    assert tmux_attrs.issubset(result_attrs)


def test_result_success_case() -> None:
    """ControlModeResult for successful command."""
    result = ControlModeResult(
        stdout=["0: session1 (1 windows) (created Tue Oct 1 12:00:00 2024)"],
        stderr=[],
        returncode=0,
        cmd=["tmux", "-C", "-L", "test", "list-sessions"],
    )

    assert result.returncode == 0
    assert len(result.stdout) == 1
    assert len(result.stderr) == 0
    assert "session1" in result.stdout[0]


def test_result_error_case() -> None:
    """ControlModeResult for failed command."""
    result = ControlModeResult(
        stdout=["parse error: unknown command: bad-command"],
        stderr=[],
        returncode=1,
        cmd=["tmux", "-C", "bad-command"],
    )

    assert result.returncode == 1
    assert len(result.stdout) == 1
    assert "parse error" in result.stdout[0]


def test_result_multiline_output() -> None:
    """ControlModeResult handles multi-line output."""
    lines = [f"line{i}" for i in range(100)]
    result = ControlModeResult(
        stdout=lines,
        stderr=[],
        returncode=0,
        cmd=["tmux", "-C", "test"],
    )

    assert len(result.stdout) == 100
    assert result.stdout[0] == "line0"
    assert result.stdout[99] == "line99"
