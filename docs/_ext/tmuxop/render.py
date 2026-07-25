"""gp-sphinx presentation helpers for tmux operation reference."""

from __future__ import annotations

import inspect
import typing as t

from docutils import nodes
from sphinx import addnodes
from sphinx_ux_autodoc_layout import (
    API,
    ApiFactRow,
    api_permalink,
    build_api_card_entry,
    build_api_facts_section,
    build_api_summary_section,
    build_chip_paragraph,
    build_linked_literal,
)
from sphinx_ux_badges import BadgeSpec, build_badge_group_from_specs

from libtmux.experimental.ops import CatalogEntry
from libtmux.experimental.ops.registry import OpSpec

if t.TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


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


def build_operation_card(
    spec: OpSpec,
    entry: CatalogEntry,
    *,
    node_id: str,
    summary_nodes: Sequence[nodes.Node],
    source_url: str | None,
    body_nodes: Sequence[nodes.Node] = (),
) -> nodes.Element:
    """Render one operation from canonical registry metadata."""
    operation_cls = spec.operation_cls
    signature = inspect.signature(operation_cls).replace(
        return_annotation=inspect.Signature.empty
    )
    signature_node = nodes.literal(
        "",
        f"{operation_cls.__name__}{signature}",
        classes=["sig", "sig-object"],
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
                        f"{operation_cls.__module__}.{operation_cls.__qualname__}",
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
    if source_url is not None:
        source = nodes.paragraph()
        source += nodes.reference(
            "",
            "View source",
            refuri=source_url,
            internal=False,
        )
        facts.append(ApiFactRow("Source", source))

    summary = build_api_summary_section(
        nodes.paragraph("", "", *[node.deepcopy() for node in summary_nodes])
    )
    content: list[nodes.Node] = [summary, build_api_facts_section(facts)]
    content.extend(node.deepcopy() for node in body_nodes)

    entry = build_api_card_entry(
        profile_class="gp-sphinx-api-profile--tmux-operation",
        signature_children=(signature_node,),
        content_children=content,
        badge_group=build_operation_badges(entry),
        permalink=api_permalink(
            href=f"#{node_id}",
            title="Link to this operation",
        ),
        entry_classes=("tmuxop-operation-card",),
    )
    shell = nodes.container(
        classes=[API.CARD_SHELL, "tmuxop-operation-shell"],
    )
    shell += entry
    return shell


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
