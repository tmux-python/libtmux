"""Examples for working with temporary files and directories in tmux tests."""

from __future__ import annotations

import pathlib
import tempfile
import time

import pytest


@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        project_dir = pathlib.Path(tmpdirname)

        # Create some sample files
        (project_dir / "main.py").write_text("print('Hello, world!')")
        (project_dir / "README.md").write_text(
            "# Test Project\n\nThis is a test project.",
        )
        (project_dir / "config.ini").write_text("[settings]\nverbose = true")

        yield project_dir


def test_project_file_manipulation(session, temp_project_dir) -> None:
    """Test working with files in a temporary project directory."""
    window = session.new_window(window_name="file-test")
    pane = window.active_pane

    # Navigate to the project directory
    pane.send_keys(f"cd {temp_project_dir}", enter=True)
    time.sleep(0.5)

    # List files
    pane.send_keys("ls -la", enter=True)
    time.sleep(0.5)

    # Verify files are visible
    output = pane.capture_pane()
    assert any("main.py" in line for line in output)
    assert any("README.md" in line for line in output)

    # Run a Python file
    pane.send_keys("python main.py", enter=True)
    time.sleep(0.5)

    # Verify output
    output = pane.capture_pane()
    assert any("Hello, world!" in line for line in output)

    # Create a new file through tmux
    pane.send_keys("echo 'print(\"Testing is fun\")' > test.py", enter=True)
    time.sleep(0.5)

    # Run the new file
    pane.send_keys("python test.py", enter=True)
    time.sleep(0.5)

    # Verify output from new file
    output = pane.capture_pane()
    assert any("Testing is fun" in line for line in output)
