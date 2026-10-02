"""Adopter-style code that ``mypy --strict`` must accept.

Nothing here runs: :func:`typing.assert_type` is a no-op at runtime. The
files exist to be type-checked, by ``uv run mypy .`` and by
``tests/test_typing_checks.py``. A line that must be *rejected* carries a
``# type: ignore[code]``; strict mode reports an unused ignore, so the line
fails the check if the API ever starts accepting it.
"""
