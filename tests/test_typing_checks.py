"""Run ``mypy --strict`` over the adopter-style files in ``tests/typing_checks``."""

from __future__ import annotations

import pathlib

import pytest
from mypy import api as mypy_api

CHECKS = pathlib.Path(__file__).parent / "typing_checks"
PYPROJECT = pathlib.Path(__file__).parent.parent / "pyproject.toml"


@pytest.mark.slow
def test_adopter_code_passes_mypy_strict() -> None:
    """Adopter code types cleanly, and rejected lines stay rejected.

    Slow: starts a mypy run (about 8 s cold) inside the test process.
    """
    stdout, stderr, status = mypy_api.run(
        [
            "--config-file",
            str(PYPROJECT),
            "--strict",
            "--no-error-summary",
            "--cache-dir",
            str(pathlib.Path(__file__).parent.parent / ".mypy_cache"),
            str(CHECKS),
        ]
    )
    assert status == 0, stdout + stderr
