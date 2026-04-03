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

    When ``pytest_fixture_lint_level`` is ``"error"``, diagnostics are
    emitted at ERROR level and ``app.statuscode`` is set to ``1`` so the
    Sphinx build reports failure.

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

    _emit = logger.error if lint_level == "error" else logger.warning
    emitted = False

    for canon, meta in store["fixtures"].items():
        # SPF001: Missing summary/docstring
        if not meta.summary:
            _emit(
                "fixture %r has no docstring",
                meta.public_name,
                extra={"fixture_canonical": canon, "spf_code": "SPF001"},
            )
            emitted = True

        # SPF002: Missing return/yield annotation
        if meta.return_display in ("", "..."):
            _emit(
                "fixture %r has no return annotation",
                meta.public_name,
                extra={"fixture_canonical": canon, "spf_code": "SPF002"},
            )
            emitted = True

        # SPF003: Yield fixture missing teardown documentation
        if meta.has_teardown and not meta.teardown_summary:
            _emit(
                "yield fixture %r has no teardown documentation",
                meta.public_name,
                extra={"fixture_canonical": canon, "spf_code": "SPF003"},
            )
            emitted = True

        # SPF005: Deprecated fixture missing replacement
        if meta.deprecated and not meta.replacement:
            _emit(
                "deprecated fixture %r has no replacement specified",
                meta.public_name,
                extra={"fixture_canonical": canon, "spf_code": "SPF005"},
            )
            emitted = True

    # Ambiguous public names (two canonical names map to the same public name)
    for pub, canon in store["public_to_canon"].items():
        if canon is None:
            _emit(
                "fixture public name %r is ambiguous (maps to multiple canonicals)",
                pub,
                extra={"spf_code": "SPF006"},
            )
            emitted = True

    if lint_level == "error" and emitted:
        app.statuscode = 1
