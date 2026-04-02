"""Sphinx directive classes for sphinx_pytest_fixtures."""

from __future__ import annotations

import typing as t

from docutils import nodes
from docutils.parsers.rst import Directive, directives
from docutils.statemachine import ViewList
from sphinx import addnodes
from sphinx.domains.python import PyFunction
from sphinx.util import logging as sphinx_logging
from sphinx.util.docfields import Field, GroupedField
from sphinx.util.docutils import SphinxDirective

from sphinx_pytest_fixtures._constants import (
    _CALLOUT_MESSAGES,
    _CONFIG_BUILTIN_LINKS,
    _CONFIG_EXTERNAL_LINKS,
    _DEFAULTS,
    _FIELD_LABELS,
    _KNOWN_KINDS,
    PYTEST_BUILTIN_LINKS,
)
from sphinx_pytest_fixtures._css import _CSS
from sphinx_pytest_fixtures._detection import (
    _get_fixture_fn,
    _get_fixture_marker,
    _is_pytest_fixture,
)
from sphinx_pytest_fixtures._metadata import (
    _build_usage_snippet,
    _has_authored_example,
    _summary_insert_index,
)
from sphinx_pytest_fixtures._models import (
    FixtureDep,
    FixtureMeta,
    autofixture_index_node,
)
from sphinx_pytest_fixtures._store import _get_spf_store, _resolve_builtin_url

if t.TYPE_CHECKING:
    pass

logger = sphinx_logging.getLogger(__name__)


class PyFixtureDirective(PyFunction):
    """Sphinx directive for documenting pytest fixtures: ``.. py:fixture::``.

    Registered as ``fixture`` in the Python domain. Renders as::

        fixture server -> Server

    instead of::

        server(request, monkeypatch, config_file) -> Server
    """

    option_spec = PyFunction.option_spec.copy()
    option_spec.update(
        {
            "scope": directives.unchanged,
            "autouse": directives.flag,
            "depends": directives.unchanged,
            "factory": directives.flag,
            "overridable": directives.flag,
            "kind": directives.unchanged,  # explicit kind override
            "return-type": directives.unchanged,
            "usage": directives.unchanged,  # "auto" (default) or "none"
            "params": directives.unchanged,  # e.g. ":params: val1, val2"
            "teardown": directives.flag,  # ":teardown:" flag for yield fixtures
            "async": directives.flag,  # ":async:" flag for async fixtures
            "deprecated": directives.unchanged,  # version string
            "replacement": directives.unchanged,  # canonical replacement fixture
            "teardown-summary": directives.unchanged,  # teardown description
        },
    )

    doc_field_types = [  # noqa: RUF012
        Field(
            "scope",
            label=_FIELD_LABELS["scope"],
            has_arg=False,
            names=("scope",),
        ),
        GroupedField(
            "depends",
            label=_FIELD_LABELS["depends"],
            rolename="fixture",
            names=("depends", "depend"),
            can_collapse=True,
        ),
        Field(
            "factory",
            label="Factory",
            has_arg=False,
            names=("factory",),
        ),
        Field(
            "overridable",
            label="Override hook",
            has_arg=False,
            names=("overridable",),
        ),
    ]

    def needs_arglist(self) -> bool:
        """Suppress ``()`` — fixtures are not called with arguments."""
        return False

    def get_signature_prefix(
        self,
        sig: str,
    ) -> t.Sequence[addnodes.desc_sig_element]:
        """Render the ``fixture`` keyword before the fixture name.

        Parameters
        ----------
        sig : str
            The raw signature string from the directive.

        Returns
        -------
        Sequence[addnodes.desc_sig_element]
            Prefix nodes rendering as ``fixture `` before the fixture name.
        """
        return [
            addnodes.desc_sig_keyword("", "fixture"),
            addnodes.desc_sig_space(),
        ]

    def handle_signature(
        self,
        sig: str,
        signode: addnodes.desc_signature,
    ) -> tuple[str, str]:
        """Store fixture metadata on signode for badge injection.

        Parameters
        ----------
        sig : str
            The raw signature string from the directive.
        signode : addnodes.desc_signature
            The signature node to annotate.

        Returns
        -------
        tuple[str, str]
            ``(fullname, prefix)`` from the parent implementation.
        """
        result = super().handle_signature(sig, signode)
        signode["spf_scope"] = self.options.get("scope", _DEFAULTS["scope"])
        signode["spf_kind"] = self.options.get("kind", _DEFAULTS["kind"])
        signode["spf_autouse"] = "autouse" in self.options
        signode["spf_deprecated"] = "deprecated" in self.options
        signode["spf_ret_type"] = self.options.get("return-type", "")
        return result

    def get_index_text(self, modname: str, name_cls: tuple[str, str]) -> str:
        """Return index entry text for the fixture.

        Parameters
        ----------
        modname : str
            The module name containing the fixture.
        name_cls : tuple[str, str]
            ``(fullname, classname_prefix)`` from ``handle_signature``.

        Returns
        -------
        str
            Index entry in the form ``name (pytest fixture in modname)``.
        """
        name, _cls = name_cls
        return f"{name} (pytest fixture in {modname})"

    def transform_content(
        self,
        content_node: addnodes.desc_content,
    ) -> None:
        """Inject fixture metadata as doctree nodes before DocFieldTransformer.

        ``transform_content`` runs at line 108 of ``ObjectDescription.run()``;
        ``DocFieldTransformer.transform_all()`` runs at line 112 — so
        ``nodes.field_list`` entries inserted here ARE processed by
        ``DocFieldTransformer`` and receive full field styling.

        Parameters
        ----------
        content_node : addnodes.desc_content
            The content node to prepend metadata into.
        """
        scope = self.options.get("scope", _DEFAULTS["scope"])
        depends_str = self.options.get("depends", "")
        ret_type = self.options.get("return-type", "")
        show_usage = self.options.get("usage", _DEFAULTS["usage"]) != "none"
        kind = self.options.get("kind", "")
        autouse = "autouse" in self.options
        has_teardown = "teardown" in self.options
        is_async = "async" in self.options

        field_list = nodes.field_list()

        # Scope field removed — badges communicate scope at a glance,
        # the index table provides comparison.  See P2-2 in the enhancement spec.

        # --- Autouse field ---
        if autouse:
            field_list += nodes.field(
                "",
                nodes.field_name("", _FIELD_LABELS["autouse"]),
                nodes.field_body(
                    "",
                    nodes.paragraph("", "yes \u2014 runs automatically for every test"),
                ),
            )

        # --- Kind field (only for custom/nonstandard kinds not covered by badges) ---
        if kind and kind not in _KNOWN_KINDS:
            field_list += nodes.field(
                "",
                nodes.field_name("", _FIELD_LABELS["kind"]),
                nodes.field_body("", nodes.paragraph("", kind)),
            )

        # --- Depends-on fields — project deps as :fixture: xrefs,
        #     builtin/external deps as external hyperlinks ---
        if depends_str:
            # Resolve builtin/external link mapping from config
            app_obj = getattr(getattr(self, "env", None), "app", None)
            builtin_links: dict[str, str] = (
                getattr(
                    app_obj.config,
                    _CONFIG_BUILTIN_LINKS,
                    PYTEST_BUILTIN_LINKS,
                )
                if app_obj is not None
                else PYTEST_BUILTIN_LINKS
            )
            external_links: dict[str, str] = (
                getattr(app_obj.config, _CONFIG_EXTERNAL_LINKS, {})
                if app_obj is not None
                else {}
            )
            all_links = {**builtin_links, **external_links}

            # Collect all dep nodes, then emit one comma-separated row
            # (matches the "Used by" pattern in _on_doctree_resolved).
            dep_ref_nodes: list[nodes.Node] = []
            for dep in (d.strip() for d in depends_str.split(",") if d.strip()):
                # Resolve URL: intersphinx → config → hardcoded fallback
                url: str | None = None
                if dep in all_links:
                    url = _resolve_builtin_url(dep, app_obj) or all_links[dep]
                if url:
                    dep_ref_nodes.append(
                        nodes.reference(dep, "", nodes.literal(dep, dep), refuri=url)
                    )
                else:
                    ref_ns, _ = self.state.inline_text(
                        f":fixture:`{dep}`",
                        self.lineno,
                    )
                    dep_ref_nodes.extend(ref_ns)

            if dep_ref_nodes:
                body_para = nodes.paragraph()
                for i, dn in enumerate(dep_ref_nodes):
                    body_para += dn
                    if i < len(dep_ref_nodes) - 1:
                        body_para += nodes.Text(", ")
                field_list += nodes.field(
                    "",
                    nodes.field_name("", _FIELD_LABELS["depends"]),
                    nodes.field_body("", body_para),
                )

        # --- Deprecation warning (before lifecycle callouts) ---
        deprecated_version = self.options.get("deprecated")
        replacement_name = self.options.get("replacement")

        if deprecated_version is not None:
            warning = nodes.warning()
            dep_text = f"Deprecated since version {deprecated_version}."
            if replacement_name:
                dep_text += f" Use :fixture:`{replacement_name}` instead."
            warning += nodes.paragraph("", dep_text)
            # Add spf-deprecated class to the parent desc node for CSS muting
            for parent in self.state.document.findall(addnodes.desc):
                for sig in parent.findall(addnodes.desc_signature):
                    if sig.get("spf_deprecated"):
                        parent["classes"].append(_CSS.DEPRECATED)
                        break

        # --- Lifecycle callouts (session note + override hook tip) ---
        callout_nodes: list[nodes.Node] = []

        if deprecated_version is not None:
            callout_nodes.append(warning)

        if scope == "session":
            note = nodes.note()
            note += nodes.paragraph("", _CALLOUT_MESSAGES["session_scope"])
            callout_nodes.append(note)

        if kind == "override_hook":
            tip = nodes.tip()
            tip += nodes.paragraph("", _CALLOUT_MESSAGES["override_hook"])
            callout_nodes.append(tip)

        if has_teardown:
            note = nodes.note()
            note += nodes.paragraph("", _CALLOUT_MESSAGES["yield_fixture"])
            teardown_text = self.options.get("teardown-summary", "")
            if teardown_text:
                note += nodes.paragraph(
                    "",
                    "",
                    nodes.strong("", "Teardown: "),
                    nodes.Text(teardown_text),
                )
            callout_nodes.append(note)

        if is_async:
            note = nodes.note()
            note += nodes.paragraph("", _CALLOUT_MESSAGES["async_fixture"])
            callout_nodes.append(note)

        # --- Usage snippet (five-zone insertion after first paragraph) ---
        raw_arg = self.arguments[0] if self.arguments else ""
        fixture_name = raw_arg.split("(")[0].strip()

        snippet: nodes.Node | None = None
        if show_usage and fixture_name and not _has_authored_example(content_node):
            snippet = _build_usage_snippet(
                fixture_name,
                ret_type or None,
                kind or _DEFAULTS["kind"],
                scope,
                autouse,
            )

        # Collect generated nodes and insert in five-zone order after summary.
        # Insertion uses reversed() so nodes end up in forward order.
        generated: list[nodes.Node] = [*callout_nodes]
        if field_list.children:
            generated.append(field_list)
        if snippet is not None:
            generated.append(snippet)

        if generated:
            insert_idx = _summary_insert_index(content_node)
            for node in reversed(generated):
                content_node.insert(insert_idx, node)

    def add_target_and_index(
        self,
        name_cls: tuple[str, str],
        sig: str,
        signode: addnodes.desc_signature,
    ) -> None:
        """Register the fixture target and index entry.

        Notes
        -----
        Bypasses ``PyFunction.add_target_and_index``, which always appends a
        ``name() (in module X)`` index entry — wrong for fixtures. Calls
        ``PyObject.add_target_and_index`` directly so only the fixture-style
        ``get_index_text`` entry is produced.

        Stores ``spf_canonical_name`` on *signode* for metadata-driven
        rendering in :func:`_on_doctree_resolved`.
        """
        modname = self.options.get("module", self.env.ref_context.get("py:module", ""))
        name = name_cls[0]
        canonical = f"{modname}.{name}" if modname else name
        signode["spf_canonical_name"] = canonical
        super(PyFunction, self).add_target_and_index(name_cls, sig, signode)

        # Scope/kind-qualified pair index entries for the general index.
        node_id = signode.get("ids", [""])[0] if signode.get("ids") else ""
        scope = self.options.get("scope", _DEFAULTS["scope"])
        kind = self.options.get("kind", _DEFAULTS["kind"])
        if scope != "function" and node_id:
            self.indexnode["entries"].append(
                ("pair", f"{scope}-scoped fixtures; {name}", node_id, "", None)
            )
        if kind not in ("resource",) and node_id:
            kind_label = {
                "factory": "factory fixtures",
                "override_hook": "override hooks",
            }.get(kind, f"{kind} fixtures")
            self.indexnode["entries"].append(
                ("pair", f"{kind_label}; {name}", node_id, "", None)
            )

        # Register minimal FixtureMeta for manual directives so they
        # participate in short-name xrefs, "Used by", and reverse_deps.
        # Guard: don't overwrite richer autodoc-generated metadata.
        store = _get_spf_store(self.env)
        if canonical not in store["fixtures"]:
            public = canonical.rsplit(".", 1)[-1]
            deps: list[FixtureDep] = []
            if depends_str := self.options.get("depends"):
                deps.extend(
                    FixtureDep(display_name=d.strip(), kind="fixture")
                    for d in depends_str.split(",")
                    if d.strip()
                )
            store["fixtures"][canonical] = FixtureMeta(
                docname=self.env.docname,
                canonical_name=canonical,
                public_name=public,
                source_name=public,
                scope=self.options.get("scope", _DEFAULTS["scope"]),
                autouse="autouse" in self.options,
                kind=self.options.get("kind", _DEFAULTS["kind"]),
                return_display=self.options.get("return-type", ""),
                return_xref_target=None,
                deps=tuple(deps),
                param_reprs=(),
                has_teardown="teardown" in self.options,
                is_async="async" in self.options,
                summary="",
                deprecated=self.options.get("deprecated"),
                replacement=self.options.get("replacement"),
                teardown_summary=self.options.get("teardown-summary"),
            )


class AutofixturesDirective(Directive):
    """Bulk fixture autodoc directive: ``.. autofixtures:: module.name``.

    Scans *module.name* for all pytest fixtures and emits one
    ``.. autofixture::`` directive per fixture found.  This eliminates
    the need to list every fixture manually in docs.

    Usage::

        .. autofixtures:: libtmux.pytest_plugin
           :order: source
           :exclude: clear_env

    Options
    -------
    order : str, optional
        ``"source"`` (default) preserves module attribute order.
        ``"alpha"`` sorts fixtures alphabetically by public name.
    exclude : str, optional
        Comma-separated list of fixture public names to skip.
    """

    required_arguments = 1
    optional_arguments = 0
    has_content = False
    option_spec: t.ClassVar[dict[str, t.Any]] = {
        "order": directives.unchanged,
        "exclude": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        """Scan the module and emit autofixture directives."""
        import importlib

        modname = self.arguments[0].strip()
        order = self.options.get("order", "source")
        exclude_str = self.options.get("exclude", "")
        excluded: set[str] = {
            name.strip() for name in exclude_str.split(",") if name.strip()
        }

        try:
            module = importlib.import_module(modname)
        except ImportError:
            logger.warning(
                "autofixtures: cannot import module %r — skipping.",
                modname,
            )
            return []

        # Register the module file as a dependency so incremental rebuilds
        # re-process this page when the scanned module changes.
        env = self.state.document.settings.env
        if hasattr(module, "__file__") and module.__file__:
            env.note_dependency(module.__file__)

        # Collect all (attr_name, public_name, fixture_obj) triples.
        entries: list[tuple[str, str, t.Any]] = []
        seen_public: set[str] = set()
        for attr_name, value in vars(module).items():
            if not _is_pytest_fixture(value):
                continue
            try:
                marker = _get_fixture_marker(value)
            except AttributeError:
                continue
            public_name = marker.name or _get_fixture_fn(value).__name__
            if public_name in excluded:
                continue
            if public_name in seen_public:
                logger.warning(
                    "autofixtures: duplicate public name %r in %s; skipping duplicate.",
                    public_name,
                    modname,
                )
                continue
            seen_public.add(public_name)
            entries.append((attr_name, public_name, value))

        if order == "alpha":
            entries.sort(key=lambda e: e[1])

        # Build RST content: one ``autofixture::`` directive per fixture.
        source = f"<autofixtures:{modname}>"
        lines: list[str] = []
        for _attr_name, public_name, _value in entries:
            lines.append(f".. autofixture:: {modname}.{public_name}")
            lines.append("")
        rst_lines = ViewList(lines, source=source)

        # Parse the generated RST into a container node.
        # ViewList is compatible with nested_parse at runtime even though
        # docutils stubs declare StringList — suppress the type mismatch.
        container = nodes.section()
        container.document = self.state.document
        self.state.nested_parse(
            rst_lines,  # type: ignore[arg-type]
            self.content_offset,
            container,
        )
        return container.children


class AutofixtureIndexDirective(SphinxDirective):
    """Generate a fixture index table from the :class:`FixtureStoreDict`.

    Emits a :class:`autofixture_index_node` placeholder at parse time.
    The placeholder is resolved into a ``nodes.table`` during
    ``doctree-resolved``, when the store has been finalized by ``env-updated``.

    Usage::

        .. autofixture-index:: libtmux.pytest_plugin
           :exclude: _internal_helper
    """

    required_arguments = 1
    optional_arguments = 0
    has_content = False
    option_spec: t.ClassVar[dict[str, t.Any]] = {
        "exclude": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        """Return a placeholder node with module and exclude metadata."""
        node = autofixture_index_node()
        node["module"] = self.arguments[0].strip()
        node["exclude"] = {
            s.strip() for s in self.options.get("exclude", "").split(",") if s.strip()
        }
        return [node]
