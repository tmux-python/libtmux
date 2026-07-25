"""Semantic Sphinx reference for experimental tmux operations."""

from __future__ import annotations

import typing as t

from .domain import (
    TmuxOperationCatalogDirective,
    TmuxOperationDirective,
    TmuxOperationDomain,
    filter_catalog,
    operation_anchor,
)

if t.TYPE_CHECKING:
    from sphinx.application import Sphinx
    from sphinx.util.typing import ExtensionMetadata

__all__ = [
    "TmuxOperationCatalogDirective",
    "TmuxOperationDirective",
    "TmuxOperationDomain",
    "filter_catalog",
    "operation_anchor",
]


def setup(app: Sphinx) -> ExtensionMetadata:
    """Register the tmux operation domain."""
    app.setup_extension("sphinx_ux_badges")
    app.setup_extension("sphinx_ux_autodoc_layout")
    app.add_domain(TmuxOperationDomain)
    return {
        "version": "0.2",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
