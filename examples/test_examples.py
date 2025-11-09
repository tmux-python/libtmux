"""Integration tests for example scripts.

Ensures all example scripts execute successfully and can be run by users.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent


@pytest.mark.parametrize(
    "script",
    [
        "async_demo.py",
        "hybrid_async_demo.py",
    ],
)
def test_example_script_executes(script: str) -> None:
    """Test that example script runs without error.

    This validates that:
    1. The example is syntactically correct
    2. All imports work
    3. The script completes successfully
    4. Users can run it directly

    Parameters
    ----------
    script : str
        Name of the example script to test
    """
    script_path = EXAMPLES_DIR / script
    assert script_path.exists(), f"Example script not found: {script}"

    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=EXAMPLES_DIR.parent,  # Run from project root
    )

    assert result.returncode == 0, (
        f"Example script {script} failed with exit code {result.returncode}\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )

    # Verify expected output patterns
    if "async_demo" in script:
        assert "Demo" in result.stdout, "Expected demo output not found"
        assert "Getting tmux version" in result.stdout or "version" in result.stdout

    if "hybrid" in script:
        assert "Pattern" in result.stdout or "Speedup" in result.stdout


def test_examples_directory_structure() -> None:
    """Verify examples directory has expected structure."""
    assert EXAMPLES_DIR.exists(), "Examples directory not found"
    assert (EXAMPLES_DIR / "async_demo.py").exists(), "async_demo.py not found"
    assert (
        EXAMPLES_DIR / "hybrid_async_demo.py"
    ).exists(), "hybrid_async_demo.py not found"


def test_example_has_docstring() -> None:
    """Verify example scripts have documentation."""
    for script in ["async_demo.py", "hybrid_async_demo.py"]:
        script_path = EXAMPLES_DIR / script
        content = script_path.read_text()

        # Check for module docstring
        assert '"""' in content, f"{script} missing docstring"

        # Check for shebang (makes it executable)
        assert content.startswith("#!/usr/bin/env python"), (
            f"{script} missing shebang"
        )


def test_example_is_self_contained() -> None:
    """Verify examples can run standalone.

    Examples should either:
    1. Import from installed libtmux
    2. Have fallback to development version
    """
    for script in ["async_demo.py", "hybrid_async_demo.py"]:
        script_path = EXAMPLES_DIR / script
        content = script_path.read_text()

        # Should have imports
        assert "import" in content, f"{script} has no imports"

        # Should have libtmux imports
        assert "libtmux" in content or "from libtmux" in content, (
            f"{script} doesn't import libtmux"
        )


@pytest.mark.slow
def test_all_examples_can_be_executed() -> None:
    """Run all Python files in examples directory.

    This is a comprehensive test to ensure every example works.
    """
    python_files = list(EXAMPLES_DIR.glob("*.py"))
    # Exclude test files and __init__.py
    example_scripts = [
        f
        for f in python_files
        if not f.name.startswith("test_") and f.name != "__init__.py"
    ]

    assert len(example_scripts) >= 2, "Expected at least 2 example scripts"

    for script_path in example_scripts:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=EXAMPLES_DIR.parent,
        )

        assert result.returncode == 0, (
            f"Example {script_path.name} failed:\n{result.stderr}"
        )
