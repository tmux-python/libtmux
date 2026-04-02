"""Index table generation helpers for sphinx_pytest_fixtures."""

from __future__ import annotations

import typing as t

from docutils import nodes
from sphinx import addnodes
from sphinx.domains.python import PythonDomain
from sphinx.util import logging as sphinx_logging
from sphinx.util.nodes import make_refnode

from sphinx_pytest_fixtures._constants import (
    _IDENTIFIER_PATTERN,
    _INDEX_TABLE_COLUMNS,
    _RST_INLINE_PATTERN,
)
from sphinx_pytest_fixtures._css import _CSS
from sphinx_pytest_fixtures._models import FixtureMeta, autofixture_index_node
from sphinx_pytest_fixtures._store import FixtureStoreDict

if t.TYPE_CHECKING:
    from sphinx.application import Sphinx

logger = sphinx_logging.getLogger(__name__)


def _parse_rst_inline(
    text: str,
    app: Sphinx,
    docname: str,
) -> list[nodes.Node]:
    """Parse RST inline markup into doctree nodes with resolved cross-refs.

    Handles ``:class:`Target```, ``:fixture:`name```, ````literal````,
    and plain text.  Cross-references are created as ``pending_xref`` nodes
    and resolved via ``env.resolve_references()``.

    Parameters
    ----------
    text : str
        RST inline text, e.g. ``"Return new :class:`libtmux.Server`."``.
    app : Sphinx
        The Sphinx application (for builder and env access).
    docname : str
        Current document name (for relative URI resolution).

    Returns
    -------
    list[nodes.Node]
        Sequence of text, literal, and reference nodes ready for insertion.
    """
    result_nodes: list[nodes.Node] = []

    # Tokenise: :role:`content`, ``literal``, or plain text
    pattern = _RST_INLINE_PATTERN
    pos = 0
    for m in pattern.finditer(text):
        # Plain text before match
        if m.start() > pos:
            result_nodes.append(nodes.Text(text[pos : m.start()]))

        if m.group(1):
            # :role:`content` — build a pending_xref
            role = m.group(1)
            content = m.group(2)

            # Handle ~ shortening prefix
            if content.startswith("~"):
                target = content[1:]
                display = target.rsplit(".", 1)[-1]
            elif "<" in content and ">" in content:
                display = content.split("<")[0].strip()
                target = content.split("<")[1].rstrip(">").strip()
            else:
                target = content
                display = content.rsplit(".", 1)[-1]

            xref = addnodes.pending_xref(
                "",
                nodes.literal(display, display, classes=["xref", "py", f"py-{role}"]),
                refdomain="py",
                reftype=role,
                reftarget=target,
                refexplicit=True,
                refwarn=True,
            )
            xref["refdoc"] = docname
            result_nodes.append(xref)

        elif m.group(3):
            # ``literal`` — inline code
            result_nodes.append(nodes.literal(m.group(3), m.group(3), classes=["code"]))
        elif m.group(4):
            # `interpreted text` — render as inline code (Sphinx default role
            # in the Python domain is :obj:, which renders as code)
            result_nodes.append(nodes.literal(m.group(4), m.group(4)))

        pos = m.end()

    # Trailing plain text
    if pos < len(text):
        result_nodes.append(nodes.Text(text[pos:]))

    # Resolve pending_xref nodes via env.resolve_references
    if any(isinstance(n, addnodes.pending_xref) for n in result_nodes):
        from sphinx.util.docutils import new_document

        temp_doc = new_document("<autofixture-index>")
        temp_para = nodes.paragraph()
        for n in result_nodes:
            temp_para += n
        temp_doc += temp_para
        app.env.resolve_references(temp_doc, docname, app.builder)
        # Extract resolved nodes from the temp paragraph
        result_nodes = list(temp_para.children)

    return result_nodes


def _build_return_type_nodes(
    meta: FixtureMeta,
    py_domain: PythonDomain,
    app: Sphinx,
    docname: str,
) -> list[nodes.Node]:
    """Build doctree nodes for the return type, with linked class/builtin names.

    Tokenises the ``return_display`` string and wraps every identifier in a
    ``:class:`` cross-reference.  ``env.resolve_references()`` then resolves
    identifiers it knows (``str`` \u2192 Python docs via intersphinx, ``Server`` \u2192
    local API page) and leaves unknown ones as plain code literals.

    Parameters
    ----------
    meta : FixtureMeta
        Fixture metadata containing ``return_display``.
    py_domain : PythonDomain
        Python domain for object lookup.
    app : Sphinx
        Sphinx application.
    docname : str
        Current document name.

    Returns
    -------
    list[nodes.Node]
        Nodes for the return type cell with cross-referenced identifiers.
    """
    display = meta.return_display
    if not display:
        return [nodes.Text("")]

    # Tokenise: identifiers (including dotted) vs punctuation/whitespace.
    # Every identifier gets wrapped in :class:`~name` so intersphinx and
    # the Python domain can resolve it.  Punctuation passes through as text.
    rst_parts: list[str] = []
    for token in _IDENTIFIER_PATTERN.split(display):
        if not token:
            continue
        if _IDENTIFIER_PATTERN.fullmatch(token):
            rst_parts.append(f":class:`~{token}`")
        else:
            rst_parts.append(token)

    rst_text = "".join(rst_parts)
    return _parse_rst_inline(rst_text, app, docname)


def _resolve_fixture_index(
    node: autofixture_index_node,
    store: FixtureStoreDict,
    py_domain: PythonDomain,
    app: Sphinx,
    docname: str,
) -> None:
    """Replace a :class:`autofixture_index_node` with a docutils table.

    Builds a 5-column table (Fixture, Scope, Kind, Returns, Description).
    Fixture names and return types are cross-referenced; description text
    has RST inline markup parsed and rendered.

    Parameters
    ----------
    node : autofixture_index_node
        The placeholder node to replace.
    store : FixtureStoreDict
        The finalized fixture store.
    py_domain : PythonDomain
        Python domain for cross-reference resolution.
    app : Sphinx
        The Sphinx application.
    docname : str
        Current document name.
    """
    modname = node["module"]
    exclude: set[str] = node.get("exclude", set())

    fixtures = [
        meta
        for canon, meta in sorted(store["fixtures"].items())
        if canon.startswith(f"{modname}.") and meta.public_name not in exclude
    ]

    if not fixtures:
        node.replace_self([])
        return

    table = nodes.table(classes=[_CSS.FIXTURE_INDEX])
    tgroup = nodes.tgroup(cols=len(_INDEX_TABLE_COLUMNS))
    table += tgroup
    for _header, width in _INDEX_TABLE_COLUMNS:
        tgroup += nodes.colspec(colwidth=width)

    thead = nodes.thead()
    tgroup += thead
    header_row = nodes.row()
    thead += header_row
    for header, _width in _INDEX_TABLE_COLUMNS:
        entry = nodes.entry()
        entry += nodes.paragraph("", header)
        header_row += entry

    tbody = nodes.tbody()
    tgroup += tbody
    for meta in fixtures:
        row = nodes.row()
        tbody += row

        # --- Fixture name: cross-ref link ---
        name_entry = nodes.entry()
        obj_entry = py_domain.objects.get(meta.canonical_name)
        if obj_entry is not None:
            ref_node: nodes.Node = make_refnode(
                app.builder,
                docname,
                obj_entry.docname,
                obj_entry.node_id,
                nodes.literal(meta.public_name, meta.public_name),
            )
        else:
            ref_node = nodes.literal(meta.public_name, meta.public_name)
        name_para = nodes.paragraph()
        name_para += ref_node
        name_entry += name_para
        row += name_entry

        # --- Scope, Kind: plain text ---
        for text in (meta.scope, meta.kind):
            entry = nodes.entry()
            entry += nodes.paragraph("", text)
            row += entry

        # --- Returns: linked type name ---
        ret_entry = nodes.entry()
        ret_para = nodes.paragraph()
        for ret_node in _build_return_type_nodes(meta, py_domain, app, docname):
            ret_para += ret_node
        ret_entry += ret_para
        row += ret_entry

        # --- Description: parsed RST inline markup ---
        desc_entry = nodes.entry()
        desc_para = nodes.paragraph()
        if meta.summary:
            for desc_node in _parse_rst_inline(meta.summary, app, docname):
                desc_para += desc_node
        desc_entry += desc_para
        row += desc_entry

    scroll_wrapper = nodes.container(classes=[_CSS.TABLE_SCROLL])
    scroll_wrapper += table
    node.replace_self([scroll_wrapper])
