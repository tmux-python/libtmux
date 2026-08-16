"""Structural contracts for the experimental operation reference."""

from __future__ import annotations

import ast
import doctest
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
        assert "SubprocessEngine" in text, path
        assert "run(" in text, path
        assert text.count("## Operation reference") == 1, path
        assert "## Failure and effects" in text, path
        assert "## Related operations" in text, path
        assert "{tmuxop:op}`" in text, path
        assert kind in text, path


def test_operation_pages_keep_live_proofs_visible() -> None:
    """Primary operation examples cannot hide setup or replace tmux with mocks."""
    for path in _operation_pages().values():
        text = path.read_text(encoding="utf-8")
        assert "MockEngine" not in text, path
        assert "AsyncMockEngine" not in text, path
        assert "doctest: +SKIP" not in text, path
        assert "testsetup" not in text, path
        assert "request.getfixturevalue" not in text, path


def test_acknowledgement_examples_show_the_typed_result() -> None:
    """Ack-only operations retain the result instead of discarding it."""
    pages = _operation_pages()

    for entry in catalog():
        if entry.result_type != "AckResult":
            continue
        path = pages[entry.kind]
        text = path.read_text(encoding="utf-8")
        block = text.split("```python", maxsplit=1)[1].split("```", maxsplit=1)[0]
        examples = doctest.DocTestParser().get_examples(block)
        operation_name = registry.get(entry.kind).operation_cls.__name__
        retained: set[str] = set()
        dependencies: dict[str, set[str]] = {}
        for example in examples:
            tree = ast.parse(example.source)
            for assignment in (
                node for node in ast.walk(tree) if isinstance(node, ast.Assign)
            ):
                targets = {
                    name.id
                    for target in assignment.targets
                    for name in ast.walk(target)
                    if isinstance(name, ast.Name) and name.id != "_"
                }
                loads = {
                    name.id
                    for name in ast.walk(assignment.value)
                    if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Load)
                }
                for target in targets:
                    dependencies.setdefault(target, set()).update(loads)

                calls = [
                    node
                    for node in ast.walk(assignment.value)
                    if isinstance(node, ast.Call)
                ]
                if not any(
                    isinstance(call.func, ast.Name)
                    and call.func.id == "run"
                    and any(
                        isinstance(nested.func, ast.Name)
                        and nested.func.id == operation_name
                        for nested in ast.walk(call)
                        if isinstance(nested, ast.Call)
                    )
                    for call in calls
                ):
                    continue
                retained.update(targets)

        assert retained, path
        displayed = set(retained)
        while derived := {
            target
            for target, loads in dependencies.items()
            if loads & displayed and target not in displayed
        }:
            displayed.update(derived)
        assert any(
            "AckResult" in example.want
            and any(
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in displayed
                for node in ast.walk(ast.parse(example.source))
            )
            for example in examples
        ), path


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
