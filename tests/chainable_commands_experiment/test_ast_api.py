"""Tests for an AST-assisted command API experiment."""

from __future__ import annotations

import pytest
from typing_extensions import assert_type

from . import ast_api as api
from .shared import CommandCall


def _script(
    proxy: api.AstCommandProxy,
) -> tuple[CommandCall, CommandCall]:
    """Return a statically visible tuple of proxy command calls."""
    return (
        proxy.new_window(window_name="work"),
        proxy.split_window(horizontal=True, percentage=50),
    )


def _unsupported_loop(proxy: api.AstCommandProxy) -> CommandCall:
    """Use control flow that the AST prototype deliberately rejects."""
    for _ in range(1):
        return proxy.new_window(window_name="work")
    msg = "unreachable"
    raise AssertionError(msg)


def test_ast_api_proxy_methods_remain_typed() -> None:
    """The proxy itself can still provide normal completion."""
    proxy = api.AstCommandProxy()

    assert_type(proxy.new_window(window_name="work"), CommandCall)


def test_ast_api_extracts_supported_call_names() -> None:
    """The AST helper discovers the simple command-call shape."""
    assert api.command_names_from_ast(_script) == ("new_window", "split_window")


def test_ast_api_builds_chain_by_executing_typed_proxy() -> None:
    """The AST API validates shape, then accumulates calls via a typed proxy."""
    chain = api.from_callable(_script)

    assert chain.argv() == (
        "new-window",
        "-d",
        "-n",
        "work",
        ";",
        "split-window",
        "-h",
        "-p",
        "50",
    )


def test_ast_api_rejects_control_flow() -> None:
    """The prototype is intentionally conservative about AST shapes."""
    with pytest.raises(api.UnsupportedAstShape):
        api.command_names_from_ast(_unsupported_loop)
