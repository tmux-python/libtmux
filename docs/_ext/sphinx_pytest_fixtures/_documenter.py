"""Autodoc documenter for pytest fixtures."""

from __future__ import annotations

import inspect
import typing as t

from docutils.parsers.rst import directives
from sphinx.ext.autodoc import FunctionDocumenter
from sphinx.util import logging as sphinx_logging

from sphinx_pytest_fixtures._constants import (
    _CONFIG_HIDDEN_DEPS,
    PYTEST_HIDDEN,
)
from sphinx_pytest_fixtures._detection import (
    _format_type_short,
    _get_fixture_fn,
    _get_fixture_marker,
    _get_return_annotation,
    _get_user_deps,
    _infer_kind,
    _is_pytest_fixture,
)
from sphinx_pytest_fixtures._metadata import _register_fixture_meta

if t.TYPE_CHECKING:
    pass

logger = sphinx_logging.getLogger(__name__)


class FixtureDocumenter(FunctionDocumenter):
    """Autodoc documenter for pytest fixtures.

    Registered via ``app.add_autodocumenter()``. Enables::

        .. autofixture:: libtmux.pytest_plugin.server
           :kind: override_hook
    """

    objtype = "fixture"
    directivetype = "fixture"
    priority = FunctionDocumenter.priority + 10

    option_spec: t.ClassVar[dict[str, t.Any]] = {
        **FunctionDocumenter.option_spec,
        "kind": directives.unchanged,
    }

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
            _CONFIG_HIDDEN_DEPS,
            PYTEST_HIDDEN,
        )
        user_deps = _get_user_deps(self.object, hidden=hidden_cfg)
        if user_deps:
            dep_names = ", ".join(name for name, _ in user_deps)
            self.add_line(f"   :depends: {dep_names}", sourcename)

        ret = _get_return_annotation(self.object)
        if ret is not inspect.Parameter.empty:
            self.add_line(f"   :return-type: {_format_type_short(ret)}", sourcename)

        explicit_kind = self.options.get("kind")
        kind = _infer_kind(self.object, explicit_kind=explicit_kind)
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
