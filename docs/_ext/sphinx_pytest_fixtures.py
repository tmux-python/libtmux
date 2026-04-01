"""Sphinx extension for documenting pytest fixtures as first-class objects.

Registers ``py:fixture`` as a domain directive and ``autofixture::`` as an
autodoc documenter. Fixtures are rendered with their scope, user-visible
dependencies, and an auto-generated usage snippet rather than as plain
callable signatures.
"""

from __future__ import annotations

import collections.abc
import dataclasses
import inspect
import typing as t
from dataclasses import dataclass

from docutils import nodes
from docutils.parsers.rst import Directive, directives
from docutils.statemachine import ViewList
from sphinx import addnodes
from sphinx.domains import ObjType
from sphinx.domains.python import PyFunction, PythonDomain, PyXRefRole
from sphinx.ext.autodoc import FunctionDocumenter
from sphinx.util import logging as sphinx_logging
from sphinx.util.docfields import Field, GroupedField
from sphinx.util.nodes import make_refnode
from sphinx.util.typing import stringify_annotation

if t.TYPE_CHECKING:
    from sphinx.application import Sphinx

logger = sphinx_logging.getLogger(__name__)


class SetupDict(t.TypedDict):
    """Return type for Sphinx extension setup()."""

    version: str
    env_version: int
    parallel_read_safe: bool
    parallel_write_safe: bool


# ---------------------------------------------------------------------------
# Fixture metadata models — env-safe (all fields are pickle-safe primitives)
# ---------------------------------------------------------------------------

FixtureKind = t.Literal["resource", "factory", "override_hook"]
_KNOWN_KINDS: frozenset[str] = frozenset(t.get_args(FixtureKind))

_STORE_VERSION = 3
"""Bump whenever ``FixtureMeta`` or the store schema changes.

Used both as the Sphinx ``env_version`` (triggers full cache invalidation) and
as a runtime sentinel inside the store dict (guards against stale pickles on
incremental builds when ``env_version`` was not bumped).
"""


@dataclass(frozen=True)
class FixtureDep:
    """A classified fixture dependency.

    All fields are primitive types so that ``FixtureDep`` can be pickled
    safely when stored in the Sphinx build environment.
    """

    display_name: str
    """Short display name, e.g. ``"config_file"``."""

    kind: t.Literal["fixture", "builtin", "external", "unresolved"]
    """Classification of the dependency."""

    target: str | None = None
    """Canonical name for project fixtures (used for reverse deps)."""

    url: str | None = None
    """External URL for builtin/external deps."""


@dataclass(frozen=True)
class FixtureMeta:
    """Env-safe fixture metadata stored per fixture in the build environment.

    All fields must be pickle-safe primitives — never store raw annotation
    objects (``type``, generics) here as they are not reliably picklable.

    Stored at ``env.domaindata["sphinx_pytest_fixtures"]["fixtures"][canonical_name]``.
    """

    docname: str
    """Sphinx docname of the page where this fixture is documented."""

    canonical_name: str
    """Fully-qualified name, e.g. ``"libtmux.pytest_plugin.server"``."""

    public_name: str
    """Pytest injection name, e.g. ``"server"`` (alias or function name)."""

    source_name: str
    """Real module attribute name, e.g. ``"_server"``."""

    scope: str
    """Fixture scope: ``"function"``, ``"session"``, ``"module"``, or ``"class"``."""

    autouse: bool
    """Whether the fixture runs automatically for every test."""

    kind: str
    """Fixture kind: one of :data:`FixtureKind` values, or a custom string."""

    return_display: str
    """Short type label, e.g. ``"Server"``."""

    return_xref_target: str | None
    """Simple class name for cross-referencing, or ``None`` for complex types."""

    deps: tuple[FixtureDep, ...]
    """Classified fixture dependencies."""

    param_reprs: tuple[str, ...]
    """``repr()`` of each parametrize value from the fixture marker."""

    has_teardown: bool
    """True when the fixture is a generator (yield-based) fixture."""

    is_async: bool
    """True when the fixture is an async function or async generator."""


# ---------------------------------------------------------------------------
# Protocol for fixture marker (structural type for mypy safety)
# ---------------------------------------------------------------------------


class _FixtureMarker(t.Protocol):
    """Normalised fixture metadata — scope is ALWAYS a plain str."""

    @property
    def scope(self) -> str: ...  # never None, never Scope enum

    @property
    def autouse(self) -> bool: ...

    @property
    def params(self) -> t.Sequence[t.Any] | None: ...

    @property
    def name(self) -> str | None: ...


class _FixtureFunctionDefinitionAdapter:
    """Adapter: normalises pytest 9+ FixtureFunctionDefinition to _FixtureMarker.

    pytest 9+: .scope is a _pytest.scope.Scope enum — .value is the lowercase str.
    pytest <9: .scope may be str or None (None means function-scope).
    """

    __slots__ = ("_obj",)

    def __init__(self, obj: t.Any) -> None:
        self._obj = obj

    @property
    def scope(self) -> str:
        raw = self._obj.scope
        if hasattr(raw, "value"):  # pytest 9+: _pytest.scope.Scope enum
            return str(raw.value)
        return str(raw) if raw else "function"

    @property
    def autouse(self) -> bool:
        return bool(self._obj.autouse)

    @property
    def params(self) -> t.Sequence[t.Any] | None:
        return self._obj.params  # type: ignore[no-any-return]

    @property
    def name(self) -> str | None:
        return self._obj.name  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fixtures hidden from "Depends on" entirely (low-value noise for readers).
# Does NOT include fixtures that have entries in PYTEST_BUILTIN_LINKS —
# those are shown with external hyperlinks instead of being hidden.
PYTEST_HIDDEN: frozenset[str] = frozenset(
    {
        "pytestconfig",
        "capfd",
        "capsysbinary",
        "capfdbinary",
        "recwarn",
        "tmpdir",
        "pytester",
        "testdir",
        "record_property",
        "record_xml_attribute",
        "record_testsuite_property",
        "cache",
    },
)

# Backward-compatible alias; deprecated in favour of pytest_fixture_hidden_dependencies.
PYTEST_INTERNAL_FIXTURES: frozenset[str] = PYTEST_HIDDEN

# External links for pytest built-in fixtures shown in "Depends on" blocks.
PYTEST_BUILTIN_LINKS: dict[str, str] = {
    "tmp_path_factory": (
        "https://docs.pytest.org/en/stable/reference/fixtures.html#tmp_path_factory"
    ),
    "tmp_path": "https://docs.pytest.org/en/stable/reference/fixtures.html#tmp_path",
    "monkeypatch": (
        "https://docs.pytest.org/en/stable/reference/fixtures.html#monkeypatch"
    ),
    "request": "https://docs.pytest.org/en/stable/reference/fixtures.html#request",
    "capsys": "https://docs.pytest.org/en/stable/reference/fixtures.html#capsys",
    "caplog": "https://docs.pytest.org/en/stable/reference/fixtures.html#caplog",
}


# ---------------------------------------------------------------------------
# Env store — extension-owned domaindata namespace
# ---------------------------------------------------------------------------


def _get_spf_store(env: t.Any) -> dict[str, t.Any]:
    """Return the extension-owned env domaindata namespace.

    Creates the namespace with empty collections on first access.

    Structure
    ---------
    ``fixtures``
        ``dict[canonical_name, FixtureMeta]``
    ``public_to_canon``
        ``dict[public_name, canonical_name | None]`` — ``None`` when ambiguous
        (same public name exported by multiple modules).
    ``reverse_deps``
        ``dict[canonical_name, list[canonical_name]]`` — who uses this fixture.

    Parameters
    ----------
    env : Any
        The Sphinx build environment.

    Returns
    -------
    dict
        The mutable store dict.
    """
    store = env.domaindata.setdefault(
        "sphinx_pytest_fixtures",
        {
            "fixtures": {},
            "public_to_canon": {},
            "reverse_deps": {},
            "_store_version": _STORE_VERSION,
        },
    )
    if store.get("_store_version") != _STORE_VERSION:
        # Stale pickle — mutate in-place to preserve existing references.
        store.clear()
        store.update(
            {
                "fixtures": {},
                "public_to_canon": {},
                "reverse_deps": {},
                "_store_version": _STORE_VERSION,
            }
        )
    return store  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Store finalization — one-shot index rebuild after all docs are read
# ---------------------------------------------------------------------------


def _rebuild_public_to_canon(store: dict[str, t.Any]) -> None:
    """Rebuild ``public_to_canon`` from the ``fixtures`` registry.

    Marks public names that map to multiple canonical names as ``None``
    (ambiguous).
    """
    pub_map: dict[str, str | None] = {}
    for canon, meta in store["fixtures"].items():
        pub = meta.public_name
        if pub in pub_map and pub_map[pub] != canon:
            pub_map[pub] = None  # ambiguous
        else:
            pub_map[pub] = canon
    store["public_to_canon"] = pub_map


def _rebind_dep_targets(store: dict[str, t.Any]) -> None:
    """Rebind ALL ``FixtureDep.target`` values from the current ``public_to_canon``.

    Handles forward references (``None`` → resolved), stale references
    (old canonical → updated/``None``), and purged providers (resolved →
    ``None``).  Uses ``dataclasses.replace`` on the frozen dataclasses.
    """
    p2c = store["public_to_canon"]
    updated: dict[str, FixtureMeta] = {}
    for canon, meta in store["fixtures"].items():
        new_deps: list[FixtureDep] = []
        changed = False
        for dep in meta.deps:
            if dep.kind == "fixture":
                correct_target = p2c.get(dep.display_name)
                if correct_target != dep.target:
                    new_deps.append(dataclasses.replace(dep, target=correct_target))
                    changed = True
                    continue
            new_deps.append(dep)
        if changed:
            updated[canon] = dataclasses.replace(meta, deps=tuple(new_deps))
    store["fixtures"].update(updated)


def _rebuild_reverse_deps(store: dict[str, t.Any]) -> None:
    """Rebuild ``reverse_deps`` from the finalized ``fixtures`` registry.

    Skips self-edges (a fixture depending on itself).
    """
    rev: dict[str, list[str]] = {}
    for canon, meta in store["fixtures"].items():
        for dep in meta.deps:
            if dep.kind == "fixture" and dep.target and dep.target != canon:
                rev.setdefault(dep.target, [])
                if canon not in rev[dep.target]:
                    rev[dep.target].append(canon)
    store["reverse_deps"] = {k: sorted(v) for k, v in rev.items()}


def _finalize_store(store: dict[str, t.Any]) -> None:
    """One-shot finalization: rebuild all derived indices from ``fixtures``.

    Called via the ``env-updated`` event, which fires once after all
    parallel merges are complete and before ``doctree-resolved``.
    """
    _rebuild_public_to_canon(store)
    _rebind_dep_targets(store)
    _rebuild_reverse_deps(store)


def _on_env_updated(app: Sphinx, env: t.Any) -> None:
    """Finalize the fixture store after all documents are read and merged.

    Parameters
    ----------
    app : Sphinx
        The Sphinx application.
    env : Any
        The Sphinx build environment.
    """
    _finalize_store(_get_spf_store(env))


# ---------------------------------------------------------------------------
# Incremental / parallel build env hooks
# ---------------------------------------------------------------------------


def _on_env_purge_doc(app: Sphinx, env: t.Any, docname: str) -> None:
    """Remove fixture records for a doc being re-processed.

    Index rebuilds are deferred to :func:`_finalize_store` via ``env-updated``.

    Parameters
    ----------
    app : Sphinx
        The Sphinx application (unused; required by the hook signature).
    env : Any
        The Sphinx build environment.
    docname : str
        The document being purged.
    """
    store = _get_spf_store(env)
    to_remove = [k for k, v in store["fixtures"].items() if v.docname == docname]
    for k in to_remove:
        del store["fixtures"][k]


def _on_env_merge_info(
    app: Sphinx,
    env: t.Any,
    docnames: list[str],
    other: t.Any,
) -> None:
    """Merge fixture metadata from parallel-build sub-environments.

    Index rebuilds are deferred to :func:`_finalize_store` via ``env-updated``.

    Parameters
    ----------
    app : Sphinx
        The Sphinx application (unused; required by the hook signature).
    env : Any
        The primary (receiving) build environment.
    docnames : list[str]
        Docnames processed by the sub-environment (unused).
    other : Any
        The sub-environment whose store is merged into *env*.
    """
    store = _get_spf_store(env)
    other_store = _get_spf_store(other)
    store["fixtures"].update(other_store["fixtures"])


def _register_fixture_meta(
    env: t.Any,
    docname: str,
    obj: t.Any,
    public_name: str,
    source_name: str,
    modname: str,
    kind: str,
    app: t.Any,
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
    return_xref_target: str | None = None
    if return_display and return_display.isidentifier():
        return_xref_target = return_display

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
# Detection and metadata helpers
# ---------------------------------------------------------------------------


def _is_pytest_fixture(obj: t.Any) -> bool:
    """Return True if *obj* is a pytest fixture callable.

    Parameters
    ----------
    obj : Any
        The object to inspect.

    Returns
    -------
    bool
        True for pytest 9+ ``FixtureFunctionDefinition`` instances and older
        pytest fixtures marked with ``_fixture_function_marker``.
    """
    try:
        from _pytest.fixtures import FixtureFunctionDefinition

        if isinstance(obj, FixtureFunctionDefinition):
            return True
    except ImportError:
        pass
    return hasattr(obj, "_fixture_function_marker")


def _get_fixture_fn(obj: t.Any) -> t.Callable[..., t.Any]:
    """Return the raw underlying function from a fixture wrapper.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Returns
    -------
    Callable
        The unwrapped fixture function with original annotations and docstring.
    """
    if hasattr(obj, "_get_wrapped_function"):
        return obj._get_wrapped_function()  # type: ignore[no-any-return]
    if hasattr(obj, "_fixture_function"):
        return obj._fixture_function  # type: ignore[no-any-return]
    if hasattr(obj, "__wrapped__"):
        return obj.__wrapped__  # type: ignore[no-any-return]
    return t.cast("t.Callable[..., t.Any]", obj)


def _get_fixture_marker(obj: t.Any) -> _FixtureMarker:
    """Return normalised fixture metadata for *obj*.

    Handles pytest 9+ FixtureFunctionDefinition (scope is Scope enum) and
    older pytest fixtures (_fixture_function_marker attribute).

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Returns
    -------
    _FixtureMarker
        Normalised marker object exposing ``scope`` (always a str),
        ``autouse``, ``params``, and ``name``.
    """
    try:
        from _pytest.fixtures import FixtureFunctionDefinition

        if isinstance(obj, FixtureFunctionDefinition):
            # FixtureFunctionDefinition wraps a FixtureFunctionMarker;
            # access the marker to get scope/autouse/params/name.
            marker = obj._fixture_function_marker
            return _FixtureFunctionDefinitionAdapter(marker)
    except ImportError:
        pass
    old_marker = getattr(obj, "_fixture_function_marker", None)
    if old_marker is not None:
        return _FixtureFunctionDefinitionAdapter(old_marker)
    msg = f"pytest fixture marker metadata not found on {type(obj).__name__!r}"
    raise AttributeError(msg)


def _iter_injectable_params(
    obj: t.Any,
) -> t.Iterator[tuple[str, inspect.Parameter]]:
    """Yield (name, param) for injectable (non-variadic) fixture parameters.

    Pytest injects all POSITIONAL_OR_KEYWORD and KEYWORD_ONLY params by name.
    POSITIONAL_ONLY parameters (before ``/``) cannot be injected by name — skip.
    VAR_POSITIONAL (*args) and VAR_KEYWORD (**kwargs) are also skipped.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Yields
    ------
    tuple[str, inspect.Parameter]
        ``(name, param)`` pairs for injectable fixture parameters only.
    """
    sig = inspect.signature(_get_fixture_fn(obj))
    for name, param in sig.parameters.items():
        if param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        yield name, param


def _get_user_deps(
    obj: t.Any,
    hidden: frozenset[str] | None = None,
) -> list[tuple[str, t.Any]]:
    """Return ``(name, annotation)`` pairs for user-visible fixture dependencies.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.
    hidden : frozenset[str] | None
        Names to exclude from the dependency list.  When ``None``, falls back
        to the module-level :data:`PYTEST_INTERNAL_FIXTURES` constant.

    Returns
    -------
    list[tuple[str, Any]]
        Parameters of the wrapped function that are not pytest built-in fixtures.
        These are the fixtures users need to provide (or that are auto-provided
        by other project fixtures).
    """
    if hidden is None:
        hidden = PYTEST_HIDDEN
    return [
        (name, param.annotation)
        for name, param in _iter_injectable_params(obj)
        if name not in hidden
    ]


def _classify_deps(
    obj: t.Any,
    app: t.Any,
) -> tuple[list[str], dict[str, str], list[str]]:
    """Classify fixture dependencies into three buckets.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.
    app : Any
        The Sphinx application (may be ``None`` in unit-test contexts).

    Returns
    -------
    tuple[list[str], dict[str, str], list[str]]
        ``(project_deps, builtin_deps, hidden_deps)`` where:

        * *project_deps* — dep names to render as ``:fixture:`` cross-refs
        * *builtin_deps* — dict mapping dep name → external URL
        * *hidden_deps* — dep names suppressed entirely
    """
    if app is not None:
        hidden: frozenset[str] = getattr(
            app.config,
            "pytest_fixture_hidden_dependencies",
            PYTEST_HIDDEN,
        )
        # Backward-compat: merge deprecated pytest_internal_fixtures if set
        old_hidden = getattr(app.config, "pytest_internal_fixtures", None)
        if old_hidden is not None:
            logger.warning(
                "pytest_internal_fixtures is deprecated; "
                "use pytest_fixture_hidden_dependencies instead",
            )
            hidden = hidden | old_hidden
        builtin_links: dict[str, str] = getattr(
            app.config,
            "pytest_fixture_builtin_links",
            PYTEST_BUILTIN_LINKS,
        )
        external_links: dict[str, str] = getattr(
            app.config,
            "pytest_external_fixture_links",
            {},
        )
        all_links = {**builtin_links, **external_links}
    else:
        hidden = PYTEST_HIDDEN
        all_links = PYTEST_BUILTIN_LINKS

    project: list[str] = []
    builtin: dict[str, str] = {}
    hidden_list: list[str] = []

    for name, _param in _iter_injectable_params(obj):
        if name in hidden:
            hidden_list.append(name)
        elif name in all_links:
            builtin[name] = all_links[name]
        else:
            project.append(name)

    return project, builtin, hidden_list


def _get_return_annotation(obj: t.Any) -> t.Any:
    """Return the injected type of the fixture's underlying function.

    For ``yield`` fixtures annotated as ``Generator[T, None, None]`` or
    ``Iterator[T]``, returns the yield type ``T`` — the value the test function
    actually receives. This matches how pytest users think about the fixture's
    return contract.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Returns
    -------
    Any
        The resolved return/yield type annotation, or ``inspect.Parameter.empty``
        when the annotation cannot be resolved (e.g. forward references under
        ``TYPE_CHECKING`` guards not importable at doc-build time).
    """
    fn = _get_fixture_fn(obj)
    try:
        hints = t.get_type_hints(fn)
    except (NameError, AttributeError):
        # Forward references (TYPE_CHECKING guards) or other resolution failures.
        # Fall back to the raw annotation string from the signature.
        ann = inspect.signature(fn).return_annotation
        return inspect.Parameter.empty if ann is inspect.Parameter.empty else ann
    ret = hints.get("return", inspect.Parameter.empty)
    if ret is inspect.Parameter.empty:
        return ret
    # Unwrap Generator/Iterator and their async counterparts so that
    # yield-based fixtures show the injected type, not the generator type.
    origin = t.get_origin(ret)
    if origin in (
        collections.abc.Generator,
        collections.abc.Iterator,
        collections.abc.AsyncGenerator,
        collections.abc.AsyncIterator,
    ):
        args = t.get_args(ret)
        return args[0] if args else inspect.Parameter.empty
    return ret


def _format_type_short(annotation: t.Any) -> str:
    """Format *annotation* to a short display string for docs.

    Parameters
    ----------
    annotation : Any
        A type annotation, possibly ``inspect.Parameter.empty``.

    Returns
    -------
    str
        A human-readable type string, or ``"..."`` when annotation is absent.
    """
    if annotation is inspect.Parameter.empty:
        return "..."
    try:
        return stringify_annotation(annotation)
    except Exception:
        return str(annotation)


def _is_factory(obj: t.Any) -> bool:
    """Return True if *obj* is a factory fixture.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Returns
    -------
    bool
        True when the return annotation is ``type[X]`` or ``Callable[..., X]``.
        Falls back to the name convention heuristic (capital first letter, e.g.
        ``TestServer``) when no annotation is present.
    """
    ret = _get_return_annotation(obj)
    # t.Any means the annotation carries no type information — fall through
    # to the name convention heuristic, same as unannotated.
    if ret is inspect.Parameter.empty or ret is t.Any:
        fn = _get_fixture_fn(obj)
        return fn.__name__[:1].isupper()
    origin = t.get_origin(ret)
    if origin is type or origin is collections.abc.Callable:
        return True
    ret_str = str(ret)
    return ret_str.startswith("type[") or "Callable" in ret_str


def _is_overridable(obj: t.Any) -> bool:
    """Return True if *obj* is a configuration-hook fixture.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Returns
    -------
    bool
        True when all three conditions hold:

        1. Zero user-visible dependencies.
        2. Return type is a plain value type (``str``, ``dict``, ``bool``, etc.)
           or a generic thereof (``dict[str, Any]``).
        3. Docstring mentions ``override`` or ``conftest``.

        Examples: ``session_params``, ``home_user_name``.
    """
    user_deps = _get_user_deps(obj)
    if user_deps:
        return False
    ret = _get_return_annotation(obj)
    if ret is inspect.Parameter.empty:
        return False
    plain_types = {str, int, bool, float, dict, list, tuple}
    origin = t.get_origin(ret)
    # Allow plain primitive types (origin is None but ret IS in plain_types)
    # and generic forms of dict/list/tuple. Domain objects like Server or
    # pathlib.Path have origin=None but are not in plain_types → return False.
    if ret not in plain_types and origin not in {dict, list, tuple}:
        return False
    fn = _get_fixture_fn(obj)
    doc = inspect.getdoc(fn) or ""
    return "override" in doc.lower() or "conftest" in doc.lower()


def _infer_kind(obj: t.Any, explicit_kind: str | None = None) -> str:
    """Return the fixture kind, honouring an explicit override.

    Priority chain:

    1. *explicit_kind* — set via ``:kind:`` directive option by the author.
    2. Type annotation — ``type[X]`` / ``Callable`` → ``"factory"``.
    3. Heuristic overridable detection → ``"override_hook"``.
    4. Default → ``"resource"``.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.
    explicit_kind : str | None
        Value from the ``:kind:`` directive option, if provided.

    Returns
    -------
    str
        One of ``"resource"``, ``"factory"``, or ``"override_hook"`` (or any
        custom string passed via ``:kind:``).
    """
    if explicit_kind:
        return explicit_kind
    if _is_factory(obj):
        return "factory"
    if _is_overridable(obj):
        logger.debug(
            "autofixture: %r inferred as override_hook via heuristic; "
            "set :kind: explicitly to suppress",
            getattr(_get_fixture_fn(obj), "__qualname__", "unknown"),
        )
        return "override_hook"
    return "resource"


# ---------------------------------------------------------------------------
# Usage snippet and layout helpers
# ---------------------------------------------------------------------------


def _build_usage_snippet(
    fixture_name: str,
    ret_type: str | None,
    kind: str,
    scope: str,
    autouse: bool,
    is_async: bool = False,
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
    is_async : bool
        When True, generates ``async def test_example(...)`` without any
        pytest-asyncio-specific markers (caller decides what marker to use).

    Returns
    -------
    nodes.Node | None
        A ``literal_block`` or ``note`` node, or ``None`` for autouse fixtures.

    Notes
    -----
    * ``resource``      → ``def test_example(name: Type) -> None: ...``
    * ``resource async`` → ``async def test_example(name: Type) -> None: ...``
    * ``factory``       → ``def test_example(Name) -> None: obj = Name(); ...``
    * ``override_hook`` → ``conftest.py`` snippet with ``@pytest.fixture`` override
    * ``autouse``       → ``nodes.note`` (no test snippet needed)
    """
    if autouse:
        note = nodes.note()
        note += nodes.paragraph(
            "",
            "No request needed \u2014 this fixture runs automatically for every test.",
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


# ---------------------------------------------------------------------------
# PyFixtureDirective — py:fixture domain directive
# ---------------------------------------------------------------------------


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
        },
    )

    doc_field_types = [  # noqa: RUF012
        Field(
            "scope",
            label="Scope",
            has_arg=False,
            names=("scope",),
        ),
        GroupedField(
            "depends",
            label="Depends on",
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
        signode["spf_scope"] = self.options.get("scope", "function")
        signode["spf_kind"] = self.options.get("kind", "resource")
        signode["spf_autouse"] = "autouse" in self.options
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
        scope = self.options.get("scope", "function")
        depends_str = self.options.get("depends", "")
        ret_type = self.options.get("return-type", "")
        show_usage = self.options.get("usage", "auto") != "none"
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
                nodes.field_name("", "Autouse"),
                nodes.field_body(
                    "",
                    nodes.paragraph("", "yes \u2014 runs automatically for every test"),
                ),
            )

        # --- Kind field (only for custom/nonstandard kinds not covered by badges) ---
        if kind and kind not in _KNOWN_KINDS:
            field_list += nodes.field(
                "",
                nodes.field_name("", "Kind"),
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
                    "pytest_fixture_builtin_links",
                    PYTEST_BUILTIN_LINKS,
                )
                if app_obj is not None
                else PYTEST_BUILTIN_LINKS
            )
            external_links: dict[str, str] = (
                getattr(app_obj.config, "pytest_external_fixture_links", {})
                if app_obj is not None
                else {}
            )
            all_links = {**builtin_links, **external_links}

            for dep in (d.strip() for d in depends_str.split(",") if d.strip()):
                if dep in all_links:
                    url = all_links[dep]
                    link_node = nodes.reference(dep, dep, refuri=url)
                    body_para = nodes.paragraph("", "", link_node)
                else:
                    ref_nodes, _ = self.state.inline_text(
                        f":fixture:`{dep}`",
                        self.lineno,
                    )
                    body_para = nodes.paragraph("", "", *ref_nodes)
                field_list += nodes.field(
                    "",
                    nodes.field_name("", "Depends on"),
                    nodes.field_body("", body_para),
                )

        # --- Lifecycle callouts (session note + override hook tip) ---
        callout_nodes: list[nodes.Node] = []

        if scope == "session":
            note = nodes.note()
            note += nodes.paragraph(
                "",
                "Created once per test session and shared across all tests. "
                "Requesting this fixture does not create a new instance per test.",
            )
            callout_nodes.append(note)

        if kind == "override_hook":
            tip = nodes.tip()
            tip += nodes.paragraph(
                "",
                "This is an override hook. Override it in your project\u2019s "
                "conftest.py to customise behaviour for your test suite.",
            )
            callout_nodes.append(tip)

        if has_teardown:
            note = nodes.note()
            note += nodes.paragraph(
                "",
                "This is a yield fixture — it runs setup code before yielding "
                "the value to the test, then teardown code after the test completes.",
            )
            callout_nodes.append(note)

        if is_async:
            note = nodes.note()
            note += nodes.paragraph(
                "",
                "This is an async fixture. Use it in async test functions.",
            )
            callout_nodes.append(note)

        # --- Usage snippet (five-zone insertion after first paragraph) ---
        raw_arg = self.arguments[0] if self.arguments else ""
        fixture_name = raw_arg.split("(")[0].strip()

        snippet: nodes.Node | None = None
        if show_usage and fixture_name:
            snippet = _build_usage_snippet(
                fixture_name,
                ret_type or None,
                kind or "resource",
                scope,
                autouse,
                is_async=is_async,
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
                scope=self.options.get("scope", "function"),
                autouse="autouse" in self.options,
                kind=self.options.get("kind", "resource"),
                return_display=self.options.get("return-type", ""),
                return_xref_target=None,
                deps=tuple(deps),
                param_reprs=(),
                has_teardown="teardown" in self.options,
                is_async="async" in self.options,
            )


# ---------------------------------------------------------------------------
# FixtureDocumenter — autodoc documenter
# ---------------------------------------------------------------------------


class FixtureDocumenter(FunctionDocumenter):
    """Autodoc documenter for pytest fixtures.

    Registered via ``app.add_autodocumenter()``. Enables::

        .. autofixture:: libtmux.pytest_plugin.server
    """

    objtype = "fixture"
    directivetype = "fixture"
    priority = FunctionDocumenter.priority + 10

    # Resolved during import_object(); None until then.
    _fixture_public_name: str | None = None

    @classmethod
    def can_document_member(
        cls,
        member: t.Any,
        membername: str,
        isattr: bool,
        parent: t.Any,
    ) -> bool:
        """Return True if *member* is a pytest fixture."""
        return _is_pytest_fixture(member)

    def import_object(self, raiseerror: bool = False) -> bool:
        """Import the fixture object, with alias-aware fallback.

        When ``@pytest.fixture(name='alias')`` is used, the module attribute
        name differs from the public fixture name.  ``autofixture::`` directives
        may be written with either the attribute name or the public alias.  The
        standard ``super().import_object()`` path finds the attribute name; if
        that fails we scan the module members looking for a fixture whose public
        name matches the requested name.

        Parameters
        ----------
        raiseerror : bool
            When True, raise ``ImportError`` on failure instead of returning
            False.

        Returns
        -------
        bool
            True when the fixture object was resolved successfully.
        """
        import importlib

        # --- Standard path: resolve by module attribute name ---
        if super().import_object(raiseerror=False):
            try:
                marker = _get_fixture_marker(self.object)
                self._fixture_public_name = (
                    marker.name or _get_fixture_fn(self.object).__name__
                )
            except AttributeError:
                pass
            return True

        # --- Alias fallback: scan module members ---
        modname, _, wanted_public = self.fullname.rpartition(".")
        if not modname:
            if raiseerror:
                msg = f"fixture {self.fullname!r} not found"
                raise ImportError(msg)
            return False

        try:
            module = importlib.import_module(modname)
        except ImportError:
            if raiseerror:
                raise
            return False

        found: list[tuple[str, t.Any, str]] = []
        for attr_name, value in vars(module).items():
            if not _is_pytest_fixture(value):
                continue
            try:
                marker = _get_fixture_marker(value)
            except AttributeError:
                continue
            public = marker.name or _get_fixture_fn(value).__name__
            if public == wanted_public:
                found.append((attr_name, value, public))

        if len(found) > 1:
            logger.warning(
                "autofixture: multiple fixtures with public name %r in %s; "
                "using first match. Use the attribute name to disambiguate.",
                wanted_public,
                modname,
            )

        if found:
            attr_name, value, public_name = found[0]
            self.object = value
            self.modname = modname
            self.objpath = [attr_name]  # real attr path for source lookup
            self.fullname = f"{modname}.{public_name}"
            self._fixture_public_name = public_name
            self.parent = module
            return True

        if raiseerror:
            msg = f"fixture alias {self.fullname!r} not found"
            raise ImportError(msg)
        return False

    def format_name(self) -> str:
        """Return the effective fixture name, honouring ``@pytest.fixture(name=...)``.

        Returns
        -------
        str
            The fixture's name as pytest will inject it into test functions.
            When ``@pytest.fixture(name='alias')`` is used, returns ``'alias'``
            rather than the underlying function name.
        """
        if self._fixture_public_name:
            return self._fixture_public_name
        return (
            getattr(self.object, "name", None) or _get_fixture_fn(self.object).__name__
        )

    def format_signature(self, **kwargs: t.Any) -> str:
        """Return ``() -> ReturnType`` so Sphinx can parse the directive argument.

        The ``()`` is required for ``py_sig_re`` to match a ``->`` return
        annotation.  ``needs_arglist()`` returns ``False``, so the ``()`` is
        suppressed in the rendered output — the reader sees only
        ``fixture name -> ReturnType``.

        Returns
        -------
        str
            Signature string of the form ``() -> ReturnType``, or empty string
            when no return annotation is present.
        """
        ret = _get_return_annotation(self.object)
        if ret is inspect.Parameter.empty:
            return "()"
        return f"() -> {_format_type_short(ret)}"

    def format_args(self, **kwargs: t.Any) -> str:
        """Return empty string — no argument list is shown to users.

        Returns
        -------
        str
            Always ``""``.
        """
        return ""

    def get_doc(self) -> list[list[str]] | None:
        """Extract the docstring from the wrapped function, not the fixture wrapper.

        Returns
        -------
        list[list[str]] or None
            Docstring lines or empty list if no docstring.
        """
        fn = _get_fixture_fn(self.object)
        docstring = inspect.getdoc(fn)
        if docstring:
            return [docstring.splitlines()]
        return []

    def add_directive_header(self, sig: str) -> None:
        """Emit the directive header with fixture-specific options.

        Also registers ``FixtureMeta`` in the env store for reverse dep
        tracking and incremental-build correctness.

        Parameters
        ----------
        sig : str
            The formatted signature string.
        """
        super().add_directive_header(sig)
        sourcename = self.get_sourcename()
        marker = _get_fixture_marker(self.object)

        scope = marker.scope
        self.add_line(f"   :scope: {scope}", sourcename)

        if marker.autouse:
            self.add_line("   :autouse:", sourcename)

        # Use the config-driven hidden set so pytest_fixture_hidden_dependencies
        # in conf.py suppresses deps from the directive header too.
        hidden_cfg: frozenset[str] = getattr(
            self.env.app.config,
            "pytest_fixture_hidden_dependencies",
            PYTEST_HIDDEN,
        )
        user_deps = _get_user_deps(self.object, hidden=hidden_cfg)
        if user_deps:
            dep_names = ", ".join(name for name, _ in user_deps)
            self.add_line(f"   :depends: {dep_names}", sourcename)

        ret = _get_return_annotation(self.object)
        if ret is not inspect.Parameter.empty:
            self.add_line(f"   :return-type: {_format_type_short(ret)}", sourcename)

        kind = _infer_kind(self.object)
        self.add_line(f"   :kind: {kind}", sourcename)

        # Register fixture metadata in the env store for reverse-dep tracking.
        # Pass already-resolved kind to avoid a second _infer_kind call.
        public_name = self.format_name()
        source_name = self.objpath[-1] if self.objpath else public_name
        meta = _register_fixture_meta(
            env=self.env,
            docname=self.env.docname,
            obj=self.object,
            public_name=public_name,
            source_name=source_name,
            modname=self.modname,
            kind=kind,
            app=self.env.app,
        )

        # Emit teardown/async flags derived from the fixture function.
        if meta.has_teardown:
            self.add_line("   :teardown:", sourcename)
        if meta.is_async:
            self.add_line("   :async:", sourcename)


# ---------------------------------------------------------------------------
# missing-reference compatibility shim
# ---------------------------------------------------------------------------


def _on_missing_reference(
    app: t.Any,
    env: t.Any,
    node: t.Any,
    contnode: t.Any,
) -> t.Any | None:
    r"""Resolve ``:func:\`name\``` cross-references to ``py:fixture`` entries.

    Parameters
    ----------
    app : Any
        The Sphinx application.
    env : Any
        The Sphinx build environment.
    node : Any
        The pending cross-reference node.
    contnode : Any
        The content node to wrap.

    Returns
    -------
    Any or None
        A resolved reference node, or ``None`` to let Sphinx continue.

    Notes
    -----
    Handles MyST ``{func}\\`name\\``` references in ``usage.md`` that predate
    the ``py:fixture`` registration. The ``ObjType`` fallback roles cover most
    cases; this handler covers the ``any`` and implicit-domain paths.
    """
    if node.get("refdomain") != "py":
        return None

    reftype = node.get("reftype")
    target = node.get("reftarget", "")
    py_domain: PythonDomain = env.get_domain("py")

    # Short-name :fixture: lookup via public_to_canon.
    if reftype == "fixture":
        store = _get_spf_store(env)
        canon = store["public_to_canon"].get(target)
        if canon:  # None means ambiguous — let Sphinx emit standard warning
            return py_domain.resolve_xref(
                env,
                node.get("refdoc", ""),
                app.builder,
                "fixture",
                canon,
                node,
                contnode,
            )
        return None

    # Existing func/obj/any fallback for legacy :func: references.
    if reftype not in ("func", "obj", "any"):
        return None

    matches = py_domain.find_obj(
        env,
        node.get("py:module", ""),
        node.get("py:class", ""),
        target,
        "fixture",
        1,
    )
    if not matches:
        return None

    match_name, _obj_entry = matches[0]
    return py_domain.resolve_xref(
        env,
        node.get("refdoc", ""),
        app.builder,
        "fixture",
        match_name,
        node,
        contnode,
    )


# ---------------------------------------------------------------------------
# Badge group helpers + doctree-resolved badge injector
# ---------------------------------------------------------------------------


def _build_badge_group_node(
    scope: str,
    kind: str,
    autouse: bool,
) -> nodes.inline:
    """Return a badge group as portable ``nodes.inline`` nodes with CSS classes.

    Unlike :func:`_build_badge_html`, this function returns standard docutils
    nodes that work in all Sphinx builders (HTML, text, LaTeX, epub).

    Badge slots (left-to-right in visual order):

    * Slot 1 (scope):   shown when ``scope != "function"``
    * Slot 2 (kind):    shown for ``"factory"`` / ``"override_hook"``; or
                        state badge (``"autouse"``) when ``autouse=True``
    * Slot 3 (FIXTURE): always shown

    Parameters
    ----------
    scope : str
        Fixture scope string.
    kind : str
        Fixture kind string.
    autouse : bool
        When True, renders AUTO state badge instead of a kind badge.

    Returns
    -------
    nodes.inline
        Badge group container with inline badge children.
    """
    group = nodes.inline(classes=["spf-badge-group"])
    badges: list[nodes.inline] = []

    # Slot 1 — scope badge (leftmost, only non-function scope)
    if scope and scope != "function":
        badges.append(
            nodes.inline(
                scope,
                scope,
                classes=["spf-badge", "spf-badge--scope", f"spf-scope-{scope}"],
            )
        )

    # Slot 2 — kind or autouse badge
    if autouse:
        badges.append(
            nodes.inline(
                "AUTO",
                "AUTO",
                classes=["spf-badge", "spf-badge--state", "spf-autouse"],
            )
        )
    elif kind == "factory":
        badges.append(
            nodes.inline(
                "FACTORY",
                "FACTORY",
                classes=["spf-badge", "spf-badge--kind", "spf-factory"],
            )
        )
    elif kind == "override_hook":
        badges.append(
            nodes.inline(
                "OVERRIDE",
                "OVERRIDE",
                classes=["spf-badge", "spf-badge--kind", "spf-override"],
            )
        )

    # Slot 3 — FIXTURE (always, rightmost)
    badges.append(
        nodes.inline(
            "FIXTURE",
            "FIXTURE",
            classes=["spf-badge", "spf-badge--fixture"],
        )
    )

    # Interleave with text separators for non-HTML builders (CSS gap
    # handles spacing in HTML; text/LaTeX/man builders need explicit spaces).
    for i, badge in enumerate(badges):
        group += badge
        if i < len(badges) - 1:
            group += nodes.Text(" ")

    return group


def _on_doctree_resolved(
    app: Sphinx,
    doctree: nodes.document,
    docname: str,
) -> None:
    """Inject badges and metadata fields into ``py:fixture`` descriptions.

    **Badges** — portable ``nodes.inline`` badge nodes appended to each
    ``desc_signature`` (scope, kind, FIXTURE).

    **Metadata fields** — "Used by" and "Parametrized" field lists appended
    to ``desc_content`` using resolved cross-reference nodes.

    Uses :func:`make_refnode` for "Used by" links because ``pending_xref``
    nodes added during ``doctree-resolved`` are too late for normal reference
    resolution (the resolution pass has already run).

    Parameters
    ----------
    app : Sphinx
        The Sphinx application instance.
    doctree : nodes.document
        The resolved document tree.
    docname : str
        The name of the document being resolved.
    """
    store = _get_spf_store(app.env)
    py_domain: PythonDomain = app.env.get_domain("py")  # type: ignore[assignment]

    for desc_node in doctree.findall(addnodes.desc):
        if desc_node.get("objtype") != "fixture":
            continue

        # --- Badge injection (per signature) ---
        for sig_node in desc_node.findall(addnodes.desc_signature):
            if sig_node.get("spf_badges_injected"):
                continue
            sig_node["spf_badges_injected"] = True

            scope = sig_node.get("spf_scope", "function")
            kind = sig_node.get("spf_kind", "resource")
            autouse = sig_node.get("spf_autouse", False)

            badge_group = _build_badge_group_node(scope, kind, autouse)

            # Insert badges after the headerlink (¶) but before the [source]
            # viewcode link.  Desired order:
            #   name → return → ¶ → badges → [source]
            # The [source] link is a ``reference`` with a ``viewcode-link``
            # child span.  If found, move it to the end after the badge group.
            viewcode_ref = None
            for child in list(sig_node.children):
                if (
                    isinstance(child, nodes.reference)
                    and child.get("internal") is not True
                    and any(
                        "viewcode-link"
                        in getattr(gc, "get", lambda *_: "")("classes", [])
                        for gc in child.children
                        if isinstance(gc, nodes.inline)
                    )
                ):
                    viewcode_ref = child
                    sig_node.remove(child)
                    break

            sig_node += badge_group
            if viewcode_ref is not None:
                sig_node += viewcode_ref

        # --- Metadata injection (once per desc_node) ---
        if desc_node.get("spf_metadata_injected"):
            continue
        desc_node["spf_metadata_injected"] = True

        first_sig = next(desc_node.findall(addnodes.desc_signature), None)
        if first_sig is None:
            continue
        canon = first_sig.get("spf_canonical_name", "")
        if not canon:
            continue

        meta = store["fixtures"].get(canon)
        content_node = None
        for child in desc_node.children:
            if isinstance(child, addnodes.desc_content):
                content_node = child
                break
        if content_node is None:
            continue

        extra_fields = nodes.field_list()

        # "Used by" field — resolved links via make_refnode
        consumers = store.get("reverse_deps", {}).get(canon, [])
        if consumers:
            body_para = nodes.paragraph()
            for i, consumer_canon in enumerate(sorted(consumers)):
                short = consumer_canon.rsplit(".", 1)[-1]
                obj_entry = py_domain.objects.get(consumer_canon)
                if obj_entry is not None:
                    ref_node: nodes.Node = make_refnode(
                        app.builder,
                        docname,
                        obj_entry.docname,
                        obj_entry.node_id,
                        nodes.literal(short, short),
                    )
                else:
                    ref_node = nodes.literal(short, short)
                body_para += ref_node
                if i < len(consumers) - 1:
                    body_para += nodes.Text(", ")
            extra_fields += nodes.field(
                "",
                nodes.field_name("", "Used by"),
                nodes.field_body("", body_para),
            )

        # "Parametrized" field — render from FixtureMeta.param_reprs tuple
        if meta and meta.param_reprs:
            body_para = nodes.paragraph()
            for i, param_repr in enumerate(meta.param_reprs):
                body_para += nodes.literal(param_repr, param_repr)
                if i < len(meta.param_reprs) - 1:
                    body_para += nodes.Text(", ")
            extra_fields += nodes.field(
                "",
                nodes.field_name("", "Parametrized"),
                nodes.field_body("", body_para),
            )

        if extra_fields.children:
            # Merge into the existing field_list from transform_content()
            # so the CSS grid formats one unified <dl> block.
            existing_list = next(content_node.findall(nodes.field_list), None)
            if existing_list is not None:
                for child in list(extra_fields.children):
                    existing_list += child
            else:
                content_node += extra_fields


# ---------------------------------------------------------------------------
# AutofixturesDirective — bulk fixture discovery
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# setup()
# ---------------------------------------------------------------------------


def setup(app: Sphinx) -> SetupDict:
    """Register the ``sphinx_pytest_fixtures`` extension.

    Parameters
    ----------
    app : Sphinx
        The Sphinx application instance.

    Returns
    -------
    SetupDict
        Extension metadata dict.
    """
    app.setup_extension("sphinx.ext.autodoc")

    # --- New config values (v1.1) ---
    app.add_config_value(
        "pytest_fixture_hidden_dependencies",
        default=PYTEST_HIDDEN,
        rebuild="env",
        types=[frozenset],
    )
    app.add_config_value(
        "pytest_fixture_builtin_links",
        default=PYTEST_BUILTIN_LINKS,
        rebuild="env",
        types=[dict],
    )
    app.add_config_value(
        "pytest_external_fixture_links",
        default={},
        rebuild="env",
        types=[dict],
    )

    # Deprecated alias — kept for backward compat; emits a warning when set.
    # Set default=None so we can detect whether the user explicitly configured it.
    app.add_config_value(
        "pytest_internal_fixtures",
        default=None,
        rebuild="env",
    )

    # Guard against re-registration when setup() is called multiple times.
    if "fixture" not in PythonDomain.object_types:
        PythonDomain.object_types["fixture"] = ObjType(
            "fixture",
            "fixture",
            "func",
            "obj",
        )
    app.add_directive_to_domain("py", "fixture", PyFixtureDirective)
    app.add_role_to_domain("py", "fixture", PyXRefRole())

    app.add_autodocumenter(FixtureDocumenter)
    app.add_directive("autofixtures", AutofixturesDirective)

    app.connect("missing-reference", _on_missing_reference)
    app.connect("doctree-resolved", _on_doctree_resolved)
    app.connect("env-purge-doc", _on_env_purge_doc)
    app.connect("env-merge-info", _on_env_merge_info)
    app.connect("env-updated", _on_env_updated)

    return {
        "version": "1.0",
        "env_version": _STORE_VERSION,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
