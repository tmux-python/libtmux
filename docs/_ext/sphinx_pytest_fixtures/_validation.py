"""Build-time fixture documentation validation with stable warning codes."""

from __future__ import annotations

import typing as t

from sphinx.util import logging as sphinx_logging

from sphinx_pytest_fixtures._store import FixtureStoreDict

if t.TYPE_CHECKING:
    pass

logger = sphinx_logging.getLogger(__name__)


def _validate_store(store: FixtureStoreDict, app: t.Any) -> None:
    """Emit structured warnings for fixture documentation issues.

    Each warning uses a stable ``spf_code`` in its ``extra`` dict so
    downstream tools can filter or suppress specific checks.

    Parameters
    ----------
    store : FixtureStoreDict
        The finalized fixture store.
    app : Any
        The Sphinx application instance, or ``None`` (skips validation).
    """
    if app is None:
        return

    lint_level = getattr(
        getattr(app, "config", None),
        "pytest_fixture_lint_level",
        "warning",
    )
    if lint_level == "none":
        return

    for canon, meta in store["fixtures"].items():
        # SPF001: Missing summary/docstring
        if not meta.summary:
            logger.warning(
                "fixture %r has no docstring",
                meta.public_name,
                extra={"fixture_canonical": canon, "spf_code": "SPF001"},
            )

        # SPF002: Missing return/yield annotation
        if meta.return_display in ("", "..."):
            logger.warning(
                "fixture %r has no return annotation",
                meta.public_name,
                extra={"fixture_canonical": canon, "spf_code": "SPF002"},
            )

        # SPF003: Yield fixture missing teardown documentation
        if meta.has_teardown and not meta.teardown_summary:
            logger.warning(
                "yield fixture %r has no teardown documentation",
                meta.public_name,
                extra={"fixture_canonical": canon, "spf_code": "SPF003"},
            )

        # SPF004: Unresolved documented dependency
        for dep in meta.deps:
            if dep.kind == "unresolved":
                logger.warning(
                    "fixture %r has unresolved dependency %r",
                    meta.public_name,
                    dep.display_name,
                    extra={"fixture_canonical": canon, "spf_code": "SPF004"},
                )

        # SPF005: Deprecated fixture missing replacement
        if meta.deprecated and not meta.replacement:
            logger.warning(
                "deprecated fixture %r has no replacement specified",
                meta.public_name,
                extra={"fixture_canonical": canon, "spf_code": "SPF005"},
            )

    # Ambiguous public names (two canonical names map to the same public name)
    for pub, canon in store["public_to_canon"].items():
        if canon is None:
            logger.warning(
                "fixture public name %r is ambiguous (maps to multiple canonicals)",
                pub,
                extra={"spf_code": "SPF006"},
            )
