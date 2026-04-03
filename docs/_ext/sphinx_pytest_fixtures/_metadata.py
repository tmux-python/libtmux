"""Metadata extraction/registration and usage snippet helpers."""

from __future__ import annotations

import ast
import inspect
import re
import typing as t

from docutils import nodes
from sphinx import addnodes
from sphinx.util import logging as sphinx_logging

from sphinx_pytest_fixtures._constants import (
    _CALLOUT_MESSAGES,
    _KNOWN_KINDS,
)
from sphinx_pytest_fixtures._detection import (
    _classify_deps,
    _format_type_short,
    _get_fixture_fn,
    _get_fixture_marker,
    _get_return_annotation,
    _infer_kind,
)
from sphinx_pytest_fixtures._models import FixtureDep, FixtureMeta
from sphinx_pytest_fixtures._store import _get_spf_store

if t.TYPE_CHECKING:
    pass

logger = sphinx_logging.getLogger(__name__)


def _is_type_checking_guard(node: ast.If) -> bool:
    """Return True if *node* is an ``if TYPE_CHECKING:`` guard."""
    test = node.test
    # Handles: TYPE_CHECKING, typing.TYPE_CHECKING, t.TYPE_CHECKING, etc.
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _qualify_forward_ref(name: str, fn: t.Any) -> str | None:
    """Try to resolve a bare forward-reference string to a qualified name.

    When a fixture's return type is behind ``if TYPE_CHECKING:``, the
    annotation is a bare string like ``"Session"`` instead of the class.
    This helper inspects the fixture module's source AST to find the
    ``from X import Y`` that provides the name, even when inside a
    ``TYPE_CHECKING`` guard.

    Parameters
    ----------
    name : str
        The bare class name (e.g. ``"Session"``).
    fn : Any
        The fixture's underlying function, used to find its module.

    Returns
    -------
    str or None
        The fully-qualified name (e.g. ``"libtmux.session.Session"``),
        or ``None`` if resolution fails.
    """
    import sys

    module = getattr(fn, "__module__", None)
    if not module:
        return None
    mod = sys.modules.get(module)
    if mod is None:
        return None

    # Fast path: name is available at runtime (not behind TYPE_CHECKING).
    obj = getattr(mod, name, None)
    if obj is not None and hasattr(obj, "__module__") and hasattr(obj, "__qualname__"):
        return f"{obj.__module__}.{obj.__qualname__}"

    # Slow path: parse the module source to find TYPE_CHECKING imports.
    try:
        source = inspect.getsource(mod)
    except (OSError, TypeError):
        return None

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    # Restrict to TYPE_CHECKING blocks only so a runtime import of the same
    # name from a different module does not steal the cross-reference.
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_guard(node):
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom) and child.module:
                    for alias in child.names:
                        imported_name = alias.asname if alias.asname else alias.name
                        if imported_name == name:
                            return f"{child.module}.{alias.name}"

    return None


def _extract_summary(obj: t.Any) -> str:
    """Return the first sentence of the fixture docstring, preserving RST markup.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Returns
    -------
    str
        First sentence with RST markup intact (e.g. ``:class:`Server```),
        or empty string if no docstring.
    """
    fn = _get_fixture_fn(obj)
    doc = inspect.getdoc(fn) or ""
    first_para = doc.split("\n\n")[0].replace("\n", " ").strip()
    match = re.match(r"^(.*?[.!?])\s", first_para)
    return match.group(1) if match else first_para


def _register_fixture_meta(
    env: t.Any,
    docname: str,
    obj: t.Any,
    public_name: str,
    source_name: str,
    modname: str,
    kind: str,
    app: t.Any,
    *,
    deprecated: str | None = None,
    replacement: str | None = None,
    teardown_summary: str | None = None,
) -> FixtureMeta:
    """Build and register a FixtureMeta for *obj* in the env store.

    Parameters
    ----------
    env : Any
        The Sphinx build environment.
    docname : str
        The current document name.
    obj : Any
        The pytest fixture wrapper object.
    public_name : str
        The injection name (alias or function name).
    source_name : str
        The real module attribute name.
    modname : str
        The module name.
    kind : str
        Explicit kind override, or empty to auto-infer.
    app : Any
        The Sphinx application.

    Returns
    -------
    FixtureMeta
        The newly created and registered fixture metadata.
    """
    canonical_name = f"{modname}.{public_name}"
    marker = _get_fixture_marker(obj)
    scope = marker.scope
    autouse = marker.autouse
    params_seq = marker.params or ()
    param_reprs = tuple(repr(p) for p in params_seq)

    fn = _get_fixture_fn(obj)
    has_teardown = inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn)
    is_async = inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn)

    ret_ann = _get_return_annotation(obj)
    return_display = (
        _format_type_short(ret_ann) if ret_ann is not inspect.Parameter.empty else ""
    )
    # Simple class name for xref: only for bare names without special chars.
    # When the annotation is a forward-reference string (from TYPE_CHECKING),
    # try to qualify it via the module's TYPE_CHECKING imports so Sphinx can
    # resolve cross-references (e.g. "Session" → "libtmux.session.Session").
    return_xref_target: str | None = None
    if return_display and return_display.isidentifier():
        return_xref_target = return_display
        if isinstance(ret_ann, str):
            qualified = _qualify_forward_ref(return_display, fn)
            if qualified:
                return_xref_target = qualified
                return_display = qualified

    inferred_kind = _infer_kind(obj, kind or None)
    if inferred_kind not in _KNOWN_KINDS:
        logger.warning(
            "unknown fixture kind %r for %r; expected one of %r",
            inferred_kind,
            canonical_name,
            sorted(_KNOWN_KINDS),
        )

    # Build classified deps.
    project_deps, builtin_deps, _hidden = _classify_deps(obj, app)
    dep_list: list[FixtureDep] = []
    for dep_name in project_deps:
        dep_store = _get_spf_store(env)
        target_canon = dep_store["public_to_canon"].get(dep_name)
        dep_list.append(
            FixtureDep(
                display_name=dep_name,
                kind="fixture",
                target=target_canon,
            )
        )
    for dep_name, url in builtin_deps.items():
        dep_list.append(FixtureDep(display_name=dep_name, kind="builtin", url=url))

    meta = FixtureMeta(
        docname=docname,
        canonical_name=canonical_name,
        public_name=public_name,
        source_name=source_name,
        scope=scope,
        autouse=autouse,
        kind=inferred_kind,
        return_display=return_display,
        return_xref_target=return_xref_target,
        deps=tuple(dep_list),
        param_reprs=param_reprs,
        has_teardown=has_teardown,
        is_async=is_async,
        summary=_extract_summary(obj),
        deprecated=deprecated,
        replacement=replacement,
        teardown_summary=teardown_summary,
    )

    store = _get_spf_store(env)
    store["fixtures"][canonical_name] = meta

    # Update public_to_canon mapping (fast-path; _finalize_store is backstop).
    if public_name not in store["public_to_canon"]:
        store["public_to_canon"][public_name] = canonical_name
    elif store["public_to_canon"][public_name] != canonical_name:
        store["public_to_canon"][public_name] = None  # ambiguous

    # Build reverse_deps for each project dep.
    for dep in dep_list:
        if dep.kind == "fixture" and dep.target:
            store["reverse_deps"].setdefault(dep.target, [])
            if canonical_name not in store["reverse_deps"][dep.target]:
                store["reverse_deps"][dep.target].append(canonical_name)

    return meta


# ---------------------------------------------------------------------------
# Usage snippet and layout helpers
# ---------------------------------------------------------------------------


def _has_authored_example(content_node: nodes.Element) -> bool:
    """Return True if *content_node* already contains authored examples.

    Only inspects direct children — does not recurse into nested containers.
    This keeps the detection narrow and predictable: a ``rubric`` titled
    "Example" buried inside an unrelated admonition will not suppress the
    auto-generated usage snippet.
    """
    for child in content_node.children:
        if isinstance(child, nodes.doctest_block):
            return True
        if isinstance(child, nodes.rubric) and child.astext() in {
            "Example",
            "Examples",
        }:
            return True
    return False


def _build_usage_snippet(
    fixture_name: str,
    ret_type: str | None,
    kind: str,
    scope: str,
    autouse: bool,
) -> nodes.Node | None:
    """Return a doctree node for the kind-appropriate usage example.

    Parameters
    ----------
    fixture_name : str
        The fixture's injection name.
    ret_type : str | None
        The fixture's return type string, or empty/None when absent.
    kind : str
        One of ``"resource"``, ``"factory"``, or ``"override_hook"``.
    scope : str
        The fixture scope (used in the conftest decorator for override hooks).
    autouse : bool
        When True, returns a note admonition instead of a test snippet.

    Returns
    -------
    nodes.Node | None
        A ``literal_block`` or ``note`` node, or ``None`` for autouse fixtures.

    Notes
    -----
    * ``resource``  → ``None`` (trivially obvious to pytest users)
    * ``factory``   → ``def test_example(Name) -> None: obj = Name(); ...``
    * ``override_hook`` → ``conftest.py`` snippet with ``@pytest.fixture`` override
    * ``autouse``   → ``nodes.note`` (no test snippet needed)
    """
    if autouse:
        note = nodes.note()
        note += nodes.paragraph(
            "",
            _CALLOUT_MESSAGES["autouse"],
        )
        return note

    if kind == "override_hook":
        scope_decorator = (
            f'@pytest.fixture(scope="{scope}")\n'
            if scope != "function"
            else "@pytest.fixture\n"
        )
        ret_ann = f" -> {ret_type}" if ret_type else ""
        code = (
            "# conftest.py\n"
            "import pytest\n\n\n"
            f"{scope_decorator}"
            f"def {fixture_name}(){ret_ann}:\n"
            "    return ...  # your value here\n"
        )
    elif kind == "factory":
        type_ann = f": {ret_type}" if ret_type else ""
        code = (
            f"def test_example({fixture_name}{type_ann}) -> None:\n"
            f"    obj = {fixture_name}()\n"
            "    assert obj is not None\n"
        )
    else:
        # Resource fixtures — generic snippet like
        # ``def test_example(server: Server): ...`` is trivially obvious
        # to any pytest user and adds nothing beyond the signature.
        return None

    return nodes.literal_block(code, code, language="python")


def _summary_insert_index(content_node: addnodes.desc_content) -> int:
    """Return insertion index just after the first paragraph in content_node.

    The first paragraph is the docstring summary sentence. Metadata and
    snippets should follow it (five-zone layout: sig → summary → metadata
    → usage → body).

    Parameters
    ----------
    content_node : addnodes.desc_content
        The directive's content node.

    Returns
    -------
    int
        Index of the node slot immediately after the first paragraph child,
        or ``0`` when no paragraph is found.
    """
    for i, child in enumerate(content_node.children):
        if isinstance(child, nodes.paragraph):
            return i + 1
    return 0
