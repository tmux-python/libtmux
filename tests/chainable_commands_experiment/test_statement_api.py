"""Tests for a SQLAlchemy-style immutable command statement API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import statement_api as api
from .shared import CommandCall


def test_statement_api_builds_command_call_genuinely() -> None:
    """Generative statement methods return a typed command call at the boundary."""
    stmt = (
        api.CommandStatement("new-window").target("$1").flag("-n", "editor").arg("vim")
    )
    call = stmt.to_call()

    assert_type(stmt, api.CommandStatement)
    assert_type(call, CommandCall)
    assert call.argv() == ("new-window", "-t", "$1", "-n", "editor", "vim")


def test_statement_api_runner_executes_statement() -> None:
    """A runner can own the execution boundary."""
    runner = api.StatementRunner()
    stmt = api.CommandStatement("display-message").arg("hello")

    result = runner.execute(stmt)

    assert result.argv == ("display-message", "hello")
    assert runner.executed == [("display-message", "hello")]
