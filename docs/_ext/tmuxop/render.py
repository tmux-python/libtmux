"""gp-sphinx presentation helpers for tmux operation reference."""

from __future__ import annotations

import inspect
import pathlib
import typing as t

from docutils import nodes
from sphinx import addnodes
from sphinx.errors import SphinxError
from sphinx_ux_autodoc_layout import (
    ApiFactRow,
    build_api_facts_section,
    build_api_summary_section,
    build_chip_paragraph,
    build_linked_literal,
    inject_signature_slots,
    iter_desc_nodes,
    parse_generated_markup,
)
from sphinx_ux_badges import BadgeSpec, build_badge_group_from_specs

from libtmux.experimental.ops import CatalogEntry
from libtmux.experimental.ops.registry import OpSpec

if t.TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sphinx.util.docutils import SphinxDirective


def operation_python_target(spec: OpSpec) -> str:
    """Return the public Python API target for an operation class."""
    return f"libtmux.experimental.ops.{spec.operation_cls.__name__}"


def operation_init_target(spec: OpSpec) -> str:
    """Return the public Python API target for an operation constructor."""
    return f"{operation_python_target(spec)}.__init__"


def _constructor_signature(operation_cls: type) -> inspect.Signature:
    """Return a gp-sphinx-style constructor signature."""
    signature = inspect.signature(operation_cls.__init__)
    parameters = [
        parameter.replace(annotation=inspect.Parameter.empty)
        for parameter in signature.parameters.values()
        if parameter.name != "self"
    ]
    return signature.replace(
        parameters=parameters,
        return_annotation=inspect.Signature.empty,
    )


def _operation_api_markup(directive: SphinxDirective, spec: OpSpec) -> str:
    """Return parser-native Python API markup for an operation."""
    python_target = operation_python_target(spec)
    constructor = _constructor_signature(spec.operation_cls)
    source, _ = directive.get_source_info()
    if pathlib.Path(source).suffix.lower() in {".md", ".markdown", ".myst"}:
        return (
            f"::::{{py:class}} {python_target}\n"
            ":no-index:\n"
            "\n"
            f":::{{py:method}} __init__{constructor}\n"
            ":no-index:\n"
            ":::\n"
            "::::\n"
        )
    return (
        f".. py:class:: {python_target}\n"
        "   :no-index:\n"
        "\n"
        f"   .. py:method:: __init__{constructor}\n"
        "      :no-index:\n"
    )


def _literal_fact(value: str) -> nodes.paragraph:
    """Wrap one literal value for a facts grid."""
    return build_chip_paragraph([value])


def _boolean_fact(value: bool) -> nodes.paragraph:
    """Render a boolean as user-facing reference text."""
    return _literal_fact("yes" if value else "no")


def _effect_labels(entry: CatalogEntry) -> list[str]:
    """Return compact labels for enabled operation effects."""
    labels = [
        key.replace("_", " ")
        for key, enabled in entry.effects.items()
        if enabled is True
    ]
    creates = entry.effects.get("creates")
    if creates:
        labels.append(f"creates {creates}")
    return labels


def build_operation_badges(entry: CatalogEntry) -> nodes.inline:
    """Build text-complete safety, scope, and shape badges."""
    return build_badge_group_from_specs(
        [
            BadgeSpec(
                entry.safety,
                tooltip=f"Safety: {entry.safety}",
                classes=(f"tmuxop-badge--{entry.safety}",),
                size="sm",
            ),
            BadgeSpec(
                entry.scope,
                tooltip=f"Scope: {entry.scope}",
                fill="outline",
                size="sm",
            ),
            BadgeSpec(
                "primitive" if entry.primitive else "composed",
                tooltip=(
                    "One tmux command"
                    if entry.primitive
                    else "Composed from multiple operations"
                ),
                fill="outline",
                size="sm",
            ),
        ],
        classes=["tmuxop-badge-group"],
    )


def build_operation_description(
    directive: SphinxDirective,
    spec: OpSpec,
    entry: CatalogEntry,
    *,
    node_id: str,
    summary_nodes: Sequence[nodes.Node],
    body_nodes: Sequence[nodes.Node] = (),
) -> addnodes.desc:
    """Render one operation from canonical registry metadata."""
    operation_cls = spec.operation_cls
    rendered = parse_generated_markup(directive, _operation_api_markup(directive, spec))
    descriptions = [
        desc
        for desc in iter_desc_nodes(rendered)
        if desc.get("domain") == "py" and desc.get("objtype") == "class"
    ]
    if len(descriptions) != 1:
        msg = (
            f"Expected one Python class description for {operation_cls.__name__}, "
            f"found {len(descriptions)}"
        )
        raise SphinxError(msg)
    description = descriptions[0]
    description["classes"].append("tmuxop-operation-card")

    signature_node = next(
        (
            child
            for child in description.children
            if isinstance(child, addnodes.desc_signature)
        ),
        None,
    )
    if signature_node is None:
        msg = f"Missing Python class signature for {operation_cls.__name__}"
        raise SphinxError(msg)
    signature_node["ids"] = [node_id]
    inject_signature_slots(
        signature_node,
        marker_attr="tmuxop_badges_injected",
        badge_node=build_operation_badges(entry),
        extract_source_link=False,
    )

    result_target = (
        f"{entry.result_type.__module__}.{entry.result_type.__qualname__}"
        if isinstance(entry.result_type, type)
        else f"libtmux.experimental.ops.results.{entry.result_type}"
    )
    facts = [
        ApiFactRow(
            "Python class",
            build_chip_paragraph(
                [
                    build_linked_literal(
                        operation_python_target(spec),
                        operation_cls.__name__,
                    )
                ]
            ),
        ),
        ApiFactRow("tmux command", _literal_fact(entry.command)),
        ApiFactRow(
            "Result",
            build_chip_paragraph(
                [build_linked_literal(result_target, entry.result_type)]
            ),
        ),
        ApiFactRow(
            "Minimum tmux",
            _literal_fact(entry.min_version or "any supported version"),
        ),
        ApiFactRow("Chainable", _boolean_fact(entry.chainable)),
        ApiFactRow(
            "Version-gated flags",
            build_chip_paragraph(
                [
                    f"{flag} >= {version}"
                    for flag, version in sorted(entry.flag_version_gates.items())
                ]
            ),
        ),
        ApiFactRow("Effects", build_chip_paragraph(_effect_labels(entry))),
    ]

    summary = build_api_summary_section(
        nodes.paragraph("", "", *[node.deepcopy() for node in summary_nodes])
    )
    content_node = next(
        (
            child
            for child in description.children
            if isinstance(child, addnodes.desc_content)
        ),
        None,
    )
    if content_node is None:
        msg = f"Missing Python class content for {operation_cls.__name__}"
        raise SphinxError(msg)
    member_descriptions = [
        child.deepcopy()
        for child in content_node.children
        if isinstance(child, addnodes.desc)
    ]
    if not member_descriptions:
        msg = f"Missing __init__ API description for {operation_cls.__name__}"
        raise SphinxError(msg)
    member_signature = next(
        member_descriptions[0].findall(addnodes.desc_signature),
        None,
    )
    if member_signature is None:
        msg = f"Missing __init__ signature for {operation_cls.__name__}"
        raise SphinxError(msg)
    member_signature["ids"] = [f"{node_id}-init"]

    content_node.children.clear()
    content_node += summary
    content_node += build_api_facts_section(facts)
    content_node.extend(node.deepcopy() for node in body_nodes)
    content_node.extend(member_descriptions)
    return description


def operation_xref(kind: str) -> addnodes.pending_xref:
    """Build one explicit operation cross-reference."""
    literal = nodes.literal("", kind)
    return addnodes.pending_xref(
        "",
        literal,
        refdomain="tmuxop",
        reftype="op",
        reftarget=kind,
        refexplicit=True,
        refwarn=True,
    )


def _table_row(cells: Sequence[nodes.Node]) -> nodes.row:
    """Build one catalog table row."""
    row = nodes.row()
    for cell in cells:
        table_entry = nodes.entry()
        table_entry += cell
        row += table_entry
    return row


def build_catalog_table(
    entries: Sequence[CatalogEntry],
    *,
    summaries: Mapping[str, Sequence[nodes.Node]],
) -> nodes.table:
    """Build a linked registry catalog table."""
    headers = ("Operation", "Command", "Safety", "Result", "Min tmux", "Summary")
    table = nodes.table(classes=["tmuxop-catalog"])
    group = nodes.tgroup(cols=len(headers))
    table += group
    for width in (2, 2, 1, 2, 1, 5):
        group += nodes.colspec(colwidth=width)

    head = nodes.thead()
    head += _table_row([nodes.paragraph(text=header) for header in headers])
    group += head
    body = nodes.tbody()
    for entry in entries:
        summary = nodes.paragraph(
            "",
            "",
            *[node.deepcopy() for node in summaries[entry.kind]],
        )
        body += _table_row(
            [
                nodes.paragraph("", "", operation_xref(entry.kind)),
                _literal_fact(entry.command),
                nodes.paragraph(text=entry.safety),
                _literal_fact(entry.result_type),
                nodes.paragraph(text=entry.min_version or "—"),
                summary,
            ]
        )
    group += body
    return table
