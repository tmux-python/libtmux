"""Domain lifecycle and semantic roles for tmux operations."""

from __future__ import annotations

import typing as t

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx import addnodes
from sphinx.domains import Domain, ObjType
from sphinx.errors import SphinxError
from sphinx.roles import XRefRole
from sphinx.util.docutils import SphinxDirective
from sphinx.util.nodes import make_refnode

from libtmux.experimental.ops import CatalogEntry, catalog, registry
from libtmux.experimental.ops.exc import UnknownOperation
from tmuxop.render import build_catalog_table, build_operation_card

if t.TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence, Set

    from sphinx.builders import Builder
    from sphinx.environment import BuildEnvironment

_SCOPES = frozenset({"server", "session", "window", "pane", "client"})
_SAFETY_TIERS = frozenset({"readonly", "mutating", "destructive"})


def operation_anchor(kind: str) -> str:
    """Return the stable document target for an operation kind."""
    return f"tmuxop-operation-{nodes.make_id(kind)}"


def filter_catalog(
    entries: Sequence[CatalogEntry],
    options: Mapping[str, str | None],
) -> list[CatalogEntry]:
    """Filter registry catalog entries using validated directive options."""
    scope = options.get("scope")
    if scope is not None and scope not in _SCOPES:
        msg = f"tmuxop catalog has unknown scope {scope!r}"
        raise SphinxError(msg)

    safety = options.get("safety")
    if safety is not None and safety not in _SAFETY_TIERS:
        msg = f"tmuxop catalog has unknown safety {safety!r}"
        raise SphinxError(msg)

    return [
        entry
        for entry in entries
        if (scope is None or entry.scope == scope)
        and (safety is None or entry.safety == safety)
        and ("primitive-only" not in options or entry.primitive)
    ]


class TmuxOperationDirective(SphinxDirective):
    """Describe one registry operation."""

    required_arguments = 1
    has_content = True
    option_spec: t.ClassVar[dict[str, t.Any]] = {
        "no-index": directives.flag,
    }

    def run(self) -> list[nodes.Node]:
        """Render one operation."""
        kind = self.arguments[0].strip()
        try:
            spec = registry.get(kind)
        except UnknownOperation as error:
            msg = f"tmuxop operation references unknown kind {kind!r}"
            raise SphinxError(msg) from error

        entry = next(item for item in catalog() if item.kind == kind)
        node_id = operation_anchor(kind)
        target = nodes.target("", "", ids=[node_id])
        if "no-index" not in self.options:
            domain = self.env.domains["tmuxop"]
            t.cast("TmuxOperationDomain", domain).note_operation(
                kind,
                self.env.docname,
                node_id,
            )

        summary_nodes, messages = self.state.inline_text(entry.summary, self.lineno)
        for pending in nodes.container("", *summary_nodes).findall(
            addnodes.pending_xref
        ):
            pending["refwarn"] = False

        body = nodes.container()
        if self.content:
            self.state.nested_parse(self.content, self.content_offset, body)

        resolver = getattr(self.env.config, "linkcode_resolve", None)
        source_url = None
        if callable(resolver):
            source_url = resolver(
                "py",
                {
                    "module": spec.operation_cls.__module__,
                    "fullname": spec.operation_cls.__qualname__,
                },
            )

        card = build_operation_card(
            spec,
            entry,
            node_id=node_id,
            summary_nodes=summary_nodes,
            source_url=source_url,
            body_nodes=body.children,
        )
        return [target, card, *messages]


class TmuxOperationCatalogDirective(SphinxDirective):
    """List registry operations."""

    has_content = False
    option_spec: t.ClassVar[dict[str, t.Any]] = {
        "scope": directives.unchanged,
        "safety": directives.unchanged,
        "primitive-only": directives.flag,
        "toctree": directives.flag,
    }

    def run(self) -> list[nodes.Node]:
        """Render a registry catalog."""
        entries = filter_catalog(catalog(), self.options)
        if not entries:
            msg = "tmuxop catalog filters matched no registered operations"
            raise SphinxError(msg)

        summaries: dict[str, Sequence[nodes.Node]] = {}
        messages: list[nodes.system_message] = []
        for entry in entries:
            summary_nodes, summary_messages = self.state.inline_text(
                entry.summary,
                self.lineno,
            )
            for pending in nodes.container("", *summary_nodes).findall(
                addnodes.pending_xref
            ):
                pending["refwarn"] = False
            summaries[entry.kind] = summary_nodes
            messages.extend(summary_messages)

        rendered: list[nodes.Node] = [
            build_catalog_table(entries, summaries=summaries),
            *messages,
        ]
        if "toctree" in self.options:
            markup = ".. toctree::\n   :hidden:\n\n" + "\n".join(
                f"   {entry.kind}" for entry in entries
            )
            rendered.extend(self.parse_text_to_nodes(markup))
        return rendered


class TmuxOperationDomain(Domain):
    """Sphinx domain for registry-backed tmux operations."""

    name = "tmuxop"
    label = "tmux operation"
    object_types: t.ClassVar[dict[str, t.Any]] = {
        "operation": ObjType("operation", "op")
    }
    directives: t.ClassVar[dict[str, t.Any]] = {
        "operation": TmuxOperationDirective,
        "catalog": TmuxOperationCatalogDirective,
    }
    roles: t.ClassVar[dict[str, t.Any]] = {"op": XRefRole(warn_dangling=True)}
    initial_data: t.ClassVar[dict[str, object]] = {"operations": {}}

    @property
    def operations(self) -> dict[str, tuple[str, str]]:
        """Return registered documentation targets keyed by operation kind."""
        return t.cast("dict[str, tuple[str, str]]", self.data["operations"])

    def note_operation(self, kind: str, docname: str, node_id: str) -> None:
        """Register one operation documentation target."""
        if kind in self.operations:
            existing_docname, _ = self.operations[kind]
            msg = (
                f"tmux operation {kind!r} is already documented in {existing_docname!r}"
            )
            raise SphinxError(msg)
        self.operations[kind] = (docname, node_id)

    def clear_doc(self, docname: str) -> None:
        """Remove targets belonging to a document before it is reread."""
        self.data["operations"] = {
            kind: location
            for kind, location in self.operations.items()
            if location[0] != docname
        }

    def merge_domaindata(
        self,
        docnames: Set[str],
        otherdata: dict[str, t.Any],
    ) -> None:
        """Merge targets read by one parallel Sphinx worker."""
        other_operations = t.cast(
            "dict[str, tuple[str, str]]",
            otherdata.get("operations", {}),
        )
        for kind, (docname, node_id) in other_operations.items():
            if docname in docnames:
                self.note_operation(kind, docname, node_id)

    def resolve_xref(
        self,
        env: BuildEnvironment,
        fromdocname: str,
        builder: Builder,
        typ: str,
        target: str,
        node: addnodes.pending_xref,
        contnode: nodes.Element,
    ) -> nodes.reference | None:
        """Resolve an operation role to its documented target."""
        location = self.operations.get(target)
        if location is None:
            return None
        docname, node_id = location
        return make_refnode(
            builder,
            fromdocname,
            docname,
            node_id,
            contnode,
            target,
        )

    def resolve_any_xref(
        self,
        env: BuildEnvironment,
        fromdocname: str,
        builder: Builder,
        target: str,
        node: addnodes.pending_xref,
        contnode: nodes.Element,
    ) -> list[tuple[str, nodes.reference]]:
        """Resolve an operation through Sphinx's any role."""
        reference = self.resolve_xref(
            env,
            fromdocname,
            builder,
            "operation",
            target,
            node,
            contnode,
        )
        if reference is None:
            return []
        return [("tmuxop:op", reference)]

    def get_objects(
        self,
    ) -> Iterator[tuple[str, str, str, str, str, int]]:
        """Yield operation objects for the Sphinx inventory."""
        for kind, (docname, node_id) in sorted(self.operations.items()):
            yield kind, kind, "operation", docname, node_id, 1
