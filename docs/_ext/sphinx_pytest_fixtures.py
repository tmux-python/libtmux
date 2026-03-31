"""Sphinx extension for documenting pytest fixtures as first-class objects.

Registers ``py:fixture`` as a domain directive and ``autofixture::`` as an
autodoc documenter. Fixtures are rendered with their scope, user-visible
dependencies, and an auto-generated usage snippet rather than as plain
callable signatures.
"""

from __future__ import annotations

import collections.abc
import inspect
import logging
import typing as t

from docutils.parsers.rst import directives
from sphinx import addnodes
from sphinx.domains import ObjType
from sphinx.domains.python import PyFunction, PythonDomain, PyXRefRole
from sphinx.ext.autodoc import FunctionDocumenter
from sphinx.util.docfields import Field, GroupedField
from sphinx.util.typing import stringify_annotation

if t.TYPE_CHECKING:
    from sphinx.application import Sphinx

logger = logging.getLogger(__name__)


class SetupDict(t.TypedDict):
    """Return type for Sphinx extension setup()."""

    version: str
    parallel_read_safe: bool
    parallel_write_safe: bool


# ---------------------------------------------------------------------------
# Protocol for fixture marker (structural type for mypy safety)
# ---------------------------------------------------------------------------


class _FixtureMarker(t.Protocol):
    """Structural type for the pytest ``FixtureFunctionMarker`` object."""

    scope: str | None
    autouse: bool
    params: t.Sequence[t.Any] | None
    name: str | None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PYTEST_INTERNAL_FIXTURES: frozenset[str] = frozenset(
    {
        "request",
        "pytestconfig",
        "capsys",
        "capfd",
        "capsysbinary",
        "capfdbinary",
        "caplog",
        "monkeypatch",
        "recwarn",
        "tmpdir",
        "tmp_path",
        "tmp_path_factory",
        "pytester",
        "testdir",
        "record_property",
        "record_xml_attribute",
        "record_testsuite_property",
        "cache",
    },
)

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
    """Return the ``FixtureFunctionMarker`` attached to *obj*.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Returns
    -------
    _FixtureMarker
        The marker object exposing ``scope``, ``autouse``, ``params``, etc.
    """
    return obj._fixture_function_marker  # type: ignore[no-any-return]


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
        hidden = PYTEST_INTERNAL_FIXTURES
    fn = _get_fixture_fn(obj)
    sig = inspect.signature(fn)
    return [
        (name, param.annotation)
        for name, param in sig.parameters.items()
        if name not in hidden
    ]


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
    # Unwrap Generator[YieldType, SendType, ReturnType] and Iterator[YieldType]
    # so that yield-based fixtures show the injected type, not the generator type.
    origin = t.get_origin(ret)
    if origin in (
        collections.abc.Generator,
        collections.abc.Iterator,
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
        """
        super(PyFunction, self).add_target_and_index(name_cls, sig, signode)


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

    def format_name(self) -> str:
        """Return the effective fixture name, honouring ``@pytest.fixture(name=...)``.

        Returns
        -------
        str
            The fixture's name as pytest will inject it into test functions.
            When ``@pytest.fixture(name='alias')`` is used, returns ``'alias'``
            rather than the underlying function name.
        """
        return (
            getattr(self.object, "name", None) or _get_fixture_fn(self.object).__name__
        )

    def format_signature(self, **kwargs: t.Any) -> str:
        """Return only ``-> ReturnType``, suppressing the parameter list.

        Returns
        -------
        str
            Arrow notation return type, or empty string when no annotation.
        """
        ret = _get_return_annotation(self.object)
        if ret is inspect.Parameter.empty:
            return ""
        return f" -> {_format_type_short(ret)}"

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

        Parameters
        ----------
        sig : str
            The formatted signature string.
        """
        super().add_directive_header(sig)
        sourcename = self.get_sourcename()
        marker = _get_fixture_marker(self.object)

        scope = marker.scope or "function"
        self.add_line(f"   :scope: {scope}", sourcename)

        if marker.autouse:
            self.add_line("   :autouse:", sourcename)

        user_deps = _get_user_deps(self.object)
        if user_deps:
            dep_names = ", ".join(name for name, _ in user_deps)
            self.add_line(f"   :depends: {dep_names}", sourcename)

        if _is_factory(self.object):
            self.add_line("   :factory:", sourcename)
        elif _is_overridable(self.object):
            self.add_line("   :overridable:", sourcename)


# ---------------------------------------------------------------------------
# autodoc-process-docstring handler
# ---------------------------------------------------------------------------


def _on_process_fixture_docstring(
    app: t.Any,
    what: str,
    name: str,
    obj: t.Any,
    options: dict[str, t.Any],
    lines: list[str],
) -> None:
    """Inject a canonical Usage snippet and Depends-on block before the docstring.

    Parameters
    ----------
    app : Any
        The Sphinx application.
    what : str
        The autodoc object type string.
    name : str
        Fully-qualified name of the object being documented.
    obj : Any
        The object being documented.
    options : dict
        Autodoc options dict.
    lines : list[str]
        Mutable docstring lines — injected content is prepended in-place.

    Notes
    -----
    Checks ``_is_pytest_fixture(obj)`` rather than ``what == 'fixture'`` for
    robustness: handles fixtures documented via ``automodule`` using the default
    ``FunctionDocumenter`` before this extension is fully active.
    """
    if not _is_pytest_fixture(obj):
        return

    fn = _get_fixture_fn(obj)
    fixture_name = getattr(obj, "name", None) or fn.__name__
    ret = _get_return_annotation(obj)
    ret_str = _format_type_short(ret)
    hidden: frozenset[str] = (
        getattr(app.config, "pytest_internal_fixtures", PYTEST_INTERNAL_FIXTURES)
        if app is not None
        else PYTEST_INTERNAL_FIXTURES
    )
    user_deps = _get_user_deps(obj, hidden=hidden)

    injected: list[str] = []

    # Auto-generated canonical usage snippet:
    # Shows injection syntax BEFORE docstring — teaches pytest DI model first.
    injected.append(".. rubric:: Usage")
    injected.append("")
    injected.append(".. code-block:: python")
    injected.append("")
    injected.append(f"   def test_example({fixture_name}: {ret_str}) -> None:")
    injected.append("       ...")
    injected.append("")

    # Depends-on block: pytest built-ins link externally; project fixtures
    # link via the :fixture: role.
    if user_deps:
        injected.append(".. rubric:: Depends on")
        injected.append("")
        for dep_name, dep_ann in user_deps:
            dep_type = _format_type_short(dep_ann)
            if dep_name in PYTEST_BUILTIN_LINKS:
                url = PYTEST_BUILTIN_LINKS[dep_name]
                injected.append(f"- `{dep_name} <{url}>`_ ({dep_type})")
            else:
                injected.append(f"- :fixture:`{dep_name}` ({dep_type})")
        injected.append("")

    lines[:0] = injected


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
    if node.get("reftype") not in ("func", "obj", "any"):
        return None

    target = node.get("reftarget", "")
    py_domain: PythonDomain = env.get_domain("py")

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

    # Configurable internal-fixture exclusion list.
    # Projects using pytest-mock can add 'mocker' here in conf.py:
    #   pytest_internal_fixtures = {
    #       *sphinx_pytest_fixtures.PYTEST_INTERNAL_FIXTURES, 'mocker'
    #   }
    app.add_config_value(
        "pytest_internal_fixtures",
        default=PYTEST_INTERNAL_FIXTURES,
        rebuild="env",
        types=[frozenset],
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

    app.connect("autodoc-process-docstring", _on_process_fixture_docstring)
    app.connect("missing-reference", _on_missing_reference)

    return {
        "version": "1.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
