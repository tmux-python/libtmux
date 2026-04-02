from __future__ import annotations

import dataclasses
import typing as t

from sphinx_pytest_fixtures._constants import (
    _EXTENSION_KEY,
    _INTERSPHINX_FIXTURE_ROLE,
    _INTERSPHINX_PROJECT,
    _STORE_VERSION,
    PYTEST_BUILTIN_LINKS,
)
from sphinx_pytest_fixtures._models import FixtureDep, FixtureMeta

if t.TYPE_CHECKING:
    from sphinx.application import Sphinx


def _resolve_builtin_url(name: str, app: t.Any) -> str | None:
    """Resolve a pytest builtin fixture URL from intersphinx inventory.

    Falls back to the hardcoded ``PYTEST_BUILTIN_LINKS`` dict when
    the intersphinx inventory is unavailable (offline builds, missing
    extension, or inventory not yet loaded).

    Parameters
    ----------
    name : str
        The fixture name to look up (e.g. ``"tmp_path_factory"``).
    app : Any
        The Sphinx application instance (or None).

    Returns
    -------
    str or None
        The resolved URL, or None if the fixture is not a known builtin.
    """
    try:
        inv = getattr(getattr(app, "env", None), "intersphinx_named_inventory", {})
        fixture_inv = inv.get(_INTERSPHINX_PROJECT, {}).get(
            _INTERSPHINX_FIXTURE_ROLE, {}
        )
        if name in fixture_inv:
            _proj, _ver, uri, _dispname = fixture_inv[name]
            return str(uri)
    except Exception:
        pass
    return PYTEST_BUILTIN_LINKS.get(name)


class FixtureStoreDict(t.TypedDict):
    """Typed shape of the extension-owned env domaindata namespace."""

    fixtures: dict[str, FixtureMeta]
    public_to_canon: dict[str, str | None]
    reverse_deps: dict[str, list[str]]
    _store_version: int


def _make_empty_store() -> FixtureStoreDict:
    """Return a fresh, empty store dict."""
    return FixtureStoreDict(
        fixtures={},
        public_to_canon={},
        reverse_deps={},
        _store_version=_STORE_VERSION,
    )


def _get_spf_store(env: t.Any) -> FixtureStoreDict:
    """Return the extension-owned env domaindata namespace.

    Creates the namespace with empty collections on first access.

    Parameters
    ----------
    env : Any
        The Sphinx build environment.

    Returns
    -------
    FixtureStoreDict
        The mutable store dict.
    """
    store: FixtureStoreDict = env.domaindata.setdefault(
        _EXTENSION_KEY,
        _make_empty_store(),
    )
    if store.get("_store_version") != _STORE_VERSION:
        # Stale pickle — mutate in-place to preserve existing references.
        t.cast(dict[str, t.Any], store).clear()
        t.cast(dict[str, t.Any], store).update(_make_empty_store())
    return store


# ---------------------------------------------------------------------------
# Store finalization — one-shot index rebuild after all docs are read
# ---------------------------------------------------------------------------


def _rebuild_public_to_canon(store: FixtureStoreDict) -> None:
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


def _rebind_dep_targets(store: FixtureStoreDict) -> None:
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


def _rebuild_reverse_deps(store: FixtureStoreDict) -> None:
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


def _finalize_store(store: FixtureStoreDict) -> None:
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
