"""Structural contracts for the experimental operation reference."""

from __future__ import annotations

import pathlib
import re

from libtmux.experimental.ops import catalog, registry

_ROOT = pathlib.Path(__file__).parents[2]
_OPERATIONS = _ROOT / "docs" / "experimental" / "operations"


def _operation_pages() -> dict[str, pathlib.Path]:
    """Return checked-in operation pages keyed by directive argument."""
    pages: dict[str, pathlib.Path] = {}
    for path in _OPERATIONS.glob("*/*.md"):
        if path.name == "index.md":
            continue
        text = path.read_text(encoding="utf-8")
        matches = re.findall(r"^```\{tmuxop:operation\}\s+(\w+)$", text, re.MULTILINE)
        assert len(matches) == 1, f"{path}: expected one operation directive"
        pages[matches[0]] = path
    return pages


def test_operation_pages_match_registry_exactly() -> None:
    """Every registered operation owns exactly one checked-in page."""
    pages = _operation_pages()

    assert set(pages) == set(registry.kinds())
    assert len(pages) == len(registry)


def test_operation_pages_follow_registry_scope() -> None:
    """The source hierarchy groups operations by their canonical scope."""
    pages = _operation_pages()

    for spec in registry:
        assert pages[spec.kind].parent.name == spec.scope
        assert pages[spec.kind].stem == spec.kind


def test_operation_pages_have_executable_user_contracts() -> None:
    """Each page has one outcome, example, failure section, and related links."""
    pages = _operation_pages()

    assert pages
    for kind, path in pages.items():
        text = path.read_text(encoding="utf-8")
        assert len(re.findall(r"^# ", text, re.MULTILINE)) == 1, path
        assert text.count("```python") == 1, path
        assert "MockEngine" in text, path
        assert "run(" in text, path
        assert "## Failure and effects" in text, path
        assert "## Related operations" in text, path
        assert "{tmuxop:op}`" in text, path
        assert kind in text, path


def test_scope_indexes_use_filtered_catalogs_and_toctrees() -> None:
    """Scope indexes derive visible catalogs and navigation from the registry."""
    for scope in ("server", "session", "window", "pane", "client"):
        text = (_OPERATIONS / scope / "index.md").read_text(encoding="utf-8")
        assert f":scope: {scope}" in text
        assert ":toctree:" in text


def test_operations_landing_links_every_scope() -> None:
    """The Operations landing exposes the complete object-oriented hierarchy."""
    text = (_OPERATIONS / "index.md").read_text(encoding="utf-8")

    for scope in ("server", "session", "window", "pane", "client"):
        assert f"]({scope}/index.md)" in text
    assert "CommandResult" in text
    assert "raise_for_status" in text


def test_catalog_inventory_remains_58_operations() -> None:
    """The reference inventory changes deliberately with the registry."""
    assert len(catalog()) == 58
