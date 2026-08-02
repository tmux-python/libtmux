"""Tests for a Hamilton-style command DAG API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import dag_api as api
from .shared import CommandCall, CommandSequence


@api.command_step("new_window")
def _new_window() -> CommandCall:
    """Build the first command in the DAG."""
    return CommandCall("new-window", ("-d", "-n", "work"))


@api.command_step("split_window", depends_on=("new_window",))
def _split_window() -> CommandCall:
    """Build the dependent command in the DAG."""
    return CommandCall("split-window", ("-h",))


def test_dag_api_orders_steps_by_dependencies() -> None:
    """The requested output determines the command dependency order."""
    dag = api.CommandDag((_split_window, _new_window), outputs=("split_window",))

    sequence = dag.sequence()

    assert_type(sequence, CommandSequence)
    assert sequence.argv() == (
        "new-window",
        "-d",
        "-n",
        "work",
        ";",
        "split-window",
        "-h",
    )


def test_dag_api_rejects_missing_dependencies() -> None:
    """DAG validation catches incomplete output plans."""
    missing = api.CommandDag((_split_window,), outputs=("split_window",))

    assert missing.missing_dependencies() == ("new_window",)
