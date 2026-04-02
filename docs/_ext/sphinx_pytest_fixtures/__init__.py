"""Sphinx extension for documenting pytest fixtures as first-class objects.

Registers ``py:fixture`` as a domain directive and ``autofixture::`` as an
autodoc documenter. Fixtures are rendered with their scope, user-visible
dependencies, and an auto-generated usage snippet rather than as plain
callable signatures.

.. note::

   This extension's visual output (badges, cards) depends on CSS rules
   currently located in the project's ``docs/_static/css/custom.css`` file.
   To use this extension in other projects, these styles must be included.
"""

from __future__ import annotations

import typing as t

from docutils import nodes
from sphinx.domains import ObjType
from sphinx.domains.python import PythonDomain, PyXRefRole

# ---------------------------------------------------------------------------
# Re-exports for backward compatibility (tests access these via the package)
# ---------------------------------------------------------------------------
from sphinx_pytest_fixtures._badges import (
    _BADGE_TOOLTIPS,
    _build_badge_group_node,
)
from sphinx_pytest_fixtures._constants import (
    _CONFIG_BUILTIN_LINKS,
    _CONFIG_EXTERNAL_LINKS,
    _CONFIG_HIDDEN_DEPS,
    _EXTENSION_KEY,
    _EXTENSION_VERSION,
    _STORE_VERSION,
    PYTEST_BUILTIN_LINKS,
    PYTEST_HIDDEN,
    SetupDict,
)
from sphinx_pytest_fixtures._css import _CSS
from sphinx_pytest_fixtures._detection import (
    _classify_deps,
    _get_fixture_fn,
    _get_fixture_marker,
    _get_return_annotation,
    _get_user_deps,
    _is_factory,
    _is_pytest_fixture,
    _iter_injectable_params,
)
from sphinx_pytest_fixtures._directives import (
    AutofixtureIndexDirective,
    AutofixturesDirective,
    PyFixtureDirective,
)
from sphinx_pytest_fixtures._documenter import FixtureDocumenter
from sphinx_pytest_fixtures._metadata import (
    _build_usage_snippet,
    _has_authored_example,
    _register_fixture_meta,
)
from sphinx_pytest_fixtures._models import (
    FixtureDep,
    FixtureMeta,
    autofixture_index_node,
)
from sphinx_pytest_fixtures._store import (
    _finalize_store,
    _get_spf_store,
    _on_env_merge_info,
    _on_env_purge_doc,
    _on_env_updated,
)
from sphinx_pytest_fixtures._transforms import (
    _depart_abbreviation_html,
    _on_doctree_resolved,
    _on_missing_reference,
    _visit_abbreviation_html,
)

if t.TYPE_CHECKING:
    from sphinx.application import Sphinx


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

    # Override the built-in abbreviation visitor to emit tabindex when set.
    # Sphinx's default visit_abbreviation only passes explanation → title,
    # silently dropping all other attributes.  This override is a strict
    # superset — non-badge abbreviation nodes produce identical output.
    app.add_node(
        nodes.abbreviation,
        override=True,
        html=(_visit_abbreviation_html, _depart_abbreviation_html),
    )

    # --- New config values (v1.1) ---
    app.add_config_value(
        _CONFIG_HIDDEN_DEPS,
        default=PYTEST_HIDDEN,
        rebuild="env",
        types=[frozenset],
    )
    app.add_config_value(
        _CONFIG_BUILTIN_LINKS,
        default=PYTEST_BUILTIN_LINKS,
        rebuild="env",
        types=[dict],
    )
    app.add_config_value(
        _CONFIG_EXTERNAL_LINKS,
        default={},
        rebuild="env",
        types=[dict],
    )

    # Register std:fixture so :external+pytest:std:fixture: intersphinx
    # references resolve.  Pytest registers this in their own conf.py;
    # we mirror it so the role is known locally.
    app.add_crossref_type("fixture", "fixture")

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
    app.add_node(autofixture_index_node)
    app.add_directive("autofixture-index", AutofixtureIndexDirective)

    app.connect("missing-reference", _on_missing_reference)
    app.connect("doctree-resolved", _on_doctree_resolved)
    app.connect("env-purge-doc", _on_env_purge_doc)
    app.connect("env-merge-info", _on_env_merge_info)
    app.connect("env-updated", _on_env_updated)

    return {
        "version": _EXTENSION_VERSION,
        "env_version": _STORE_VERSION,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
