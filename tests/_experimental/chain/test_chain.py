"""Tests for the chainability contract."""

from __future__ import annotations

import pytest

from libtmux._experimental.chain.chain import (
    DeferredCommandResult,
    DeferredOutputUnavailable,
    is_chainable,
)
from libtmux._experimental.chain.ir import CommandCall


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
    """A deferred result has no output until the chain runs."""
    result = DeferredCommandResult(CommandCall("rename-window", ("work",)))

    with pytest.raises(DeferredOutputUnavailable):
        _ = result.stdout
    with pytest.raises(DeferredOutputUnavailable):
        _ = result.stderr
    with pytest.raises(DeferredOutputUnavailable):
        _ = result.returncode
