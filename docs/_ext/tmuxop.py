"""Sphinx directive that renders the experimental operation catalog.

``.. tmuxop-catalog::`` (or the MyST fenced form) walks
:func:`libtmux.experimental.ops.catalog` and emits a table of operations with
their scope, safety tier, result type, minimum tmux version, and summary. The
operation registry is the single source of truth, so the rendered reference
cannot drift from the code.

Options
-------
``:scope:`` / ``:safety:``
    Filter to one scope (``pane``/``window``/``session``/``server``/``client``)
    or safety tier (``readonly``/``mutating``/``destructive``).
``:primitive-only:``
    Show only operations that wrap a single tmux command.

This is the in-repo renderer; a full gp-sphinx ``tmuxop`` domain (cross-reference
roles + an operations index) can later replace it under the same directive name.
"""

from __future__ import annotations

import typing as t

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from sphinx.application import Sphinx

logger = logging.getLogger(__name__)

_HEADERS = ("Operation", "Command", "Scope", "Safety", "Result", "Min tmux", "Summary")


def _row(cells: Sequence[str]) -> nodes.row:
    """Build a docutils table row from string cells."""
    row = nodes.row()
    for cell in cells:
        entry = nodes.entry()
        entry += nodes.paragraph(text=cell)
        row += entry
    return row


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> nodes.table:
    """Build a simple docutils table."""
    table = nodes.table()
    tgroup = nodes.tgroup(cols=len(headers))
    table += tgroup
    for _ in headers:
        tgroup += nodes.colspec(colwidth=1)
    thead = nodes.thead()
    thead += _row(headers)
    tgroup += thead
    tbody = nodes.tbody()
    for row in rows:
        tbody += _row(row)
    tgroup += tbody
    return table


class TmuxopCatalogDirective(SphinxDirective):
    """Render the operation catalog as a table."""

    has_content = False
    option_spec: t.ClassVar[dict[str, t.Any]] = {
        "scope": directives.unchanged,
        "safety": directives.unchanged,
        "primitive-only": directives.flag,
    }

    def run(self) -> list[nodes.Node]:
        """Build the catalog table from the operation registry."""
        from libtmux.experimental.ops import catalog

        entries = catalog()
        scope = self.options.get("scope")
        safety = self.options.get("safety")
        if scope:
            entries = [entry for entry in entries if entry.scope == scope]
        if safety:
            entries = [entry for entry in entries if entry.safety == safety]
        if "primitive-only" in self.options:
            entries = [entry for entry in entries if entry.primitive]

        if not entries:
            logger.warning(
                "tmuxop-catalog: no operations matched the given filters",
                location=self.get_location(),
            )
            return []

        rows = [
            (
                entry.kind,
                entry.command,
                entry.scope,
                entry.safety,
                entry.result_type,
                entry.min_version or "-",
                entry.summary,
            )
            for entry in entries
        ]
        return [_table(_HEADERS, rows)]


def setup(app: Sphinx) -> dict[str, t.Any]:
    """Register the directive."""
    app.add_directive("tmuxop-catalog", TmuxopCatalogDirective)
    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
