"""Tests for the chainability contract."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import typing as t

import pytest

from libtmux._experimental.chain.chain import (
    DeferredCommandResult,
    DeferredOutputUnavailable,
    is_chainable,
)
from libtmux._experimental.chain.ir import CommandCall


class MinimalImportCase(t.NamedTuple):
    """A module import that must work without optional dependency groups."""

    test_id: str
    module: str


MINIMAL_IMPORT_CASES = (
    MinimalImportCase(
        test_id="chain-package",
        module="libtmux._experimental.chain",
    ),
)


@pytest.mark.parametrize(
    "case",
    MINIMAL_IMPORT_CASES,
    ids=[case.test_id for case in MINIMAL_IMPORT_CASES],
)
def test_minimal_import_without_dev_dependency_groups(
    case: MinimalImportCase,
) -> None:
    """The experimental chain package imports with only stdlib dependencies."""
    project_root = pathlib.Path(__file__).parents[3]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    proc = subprocess.run(
        [sys.executable, "-S", "-c", f"import {case.module}"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr


def test_is_chainable_uses_static_spec() -> None:
    """The static ``chainable`` flag decides what may fold into a chain."""
    assert is_chainable("rename-window") is True
    assert is_chainable("select-layout") is True
    # Output commands cannot join a one-dispatch chain.
    assert is_chainable("show-option") is False
    assert is_chainable("capture-pane") is False
    # Unknown commands are treated as chainable.
    assert is_chainable("some-unknown-command") is True


def test_deferred_result_rejects_output_access() -> None:
    """An unresolved deferred result has no output until the chain runs."""
    result = DeferredCommandResult(CommandCall("rename-window", ("work",)))

    with pytest.raises(DeferredOutputUnavailable):
        _ = result.stdout
    with pytest.raises(DeferredOutputUnavailable):
        _ = result.stderr
    with pytest.raises(DeferredOutputUnavailable):
        _ = result.returncode


class _MergedResult:
    """Minimal merged chain result for resolution tests."""

    def __init__(self) -> None:
        self.stdout = ["ok"]
        self.stderr: list[str] = []
        self.returncode = 0


def test_deferred_result_resolves_to_chain_result() -> None:
    """A resolved deferred result hands back the chain's merged result."""
    pending = DeferredCommandResult(CommandCall("rename-window", ("work",)))

    resolved = pending.resolve(_MergedResult())

    assert resolved.returncode == 0
    assert resolved.stdout == ["ok"]
    assert resolved.stderr == []
    # The original handle stays unresolved (immutable).
    with pytest.raises(DeferredOutputUnavailable):
        _ = pending.returncode
