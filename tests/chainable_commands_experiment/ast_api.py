"""AST-assisted command-chain experiment."""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Callable

from .shared import (
    CommandCall,
    CommandSequence,
    new_window_call,
    split_window_call,
)


class UnsupportedAstShape(ValueError):
    """Raised when a callable uses syntax outside the AST prototype."""


class AstCommandProxy:
    """Typed proxy used by the AST experiment."""

    def __init__(self) -> None:
        """Initialize an empty proxy call list."""
        self._calls: list[CommandCall] = []

    def to_sequence(self) -> CommandSequence:
        """Return accumulated calls as a command sequence."""
        return CommandSequence(tuple(self._calls))

    def new_window(
        self,
        *,
        window_name: str | None = None,
        detach: bool = True,
    ) -> CommandCall:
        """Add a ``new-window`` proxy call."""
        call = new_window_call(window_name=window_name, detach=detach)
        self._calls.append(call)
        return call

    def split_window(
        self,
        *,
        horizontal: bool = False,
        percentage: int | None = None,
    ) -> CommandCall:
        """Add a ``split-window`` proxy call."""
        call = split_window_call(
            horizontal=horizontal,
            percentage=percentage,
        )
        self._calls.append(call)
        return call


def command_names_from_ast(
    function: Callable[[AstCommandProxy], object],
) -> tuple[str, ...]:
    """Extract command method names from a restricted callable AST."""
    function_def = _function_def_from_source(function)
    if any(
        isinstance(node, ast.For | ast.While | ast.If | ast.Match)
        for node in ast.walk(function_def)
    ):
        msg = "control flow is outside this AST prototype"
        raise UnsupportedAstShape(msg)

    names = [
        node.func.attr
        for node in ast.walk(function_def)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    if not names:
        msg = "no proxy command calls found"
        raise UnsupportedAstShape(msg)
    return tuple(names)


def from_callable(function: Callable[[AstCommandProxy], object]) -> CommandSequence:
    """Validate a callable's AST, then execute it against a typed proxy."""
    command_names_from_ast(function)
    proxy = AstCommandProxy()
    function(proxy)
    return proxy.to_sequence()


def _function_def_from_source(
    function: Callable[[AstCommandProxy], object],
) -> ast.FunctionDef:
    source = textwrap.dedent(inspect.getsource(function))
    module = ast.parse(source)
    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        msg = "expected a single function definition"
        raise UnsupportedAstShape(msg)
    return module.body[0]
