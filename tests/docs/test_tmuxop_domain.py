"""Contracts for the registry-backed tmux operation domain."""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import pathlib
import sys
import types
import typing as t

import pytest
from docutils import nodes
from sphinx.errors import SphinxError

from libtmux.experimental.ops import catalog, registry
from libtmux.experimental.ops.registry import OpSpec


@dataclasses.dataclass
class _Environment:
    domaindata: dict[str, dict[str, t.Any]] = dataclasses.field(default_factory=dict)


@pytest.fixture
def tmuxop_module(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Import the in-tree Sphinx extension as Sphinx does."""
    extension_path = pathlib.Path(__file__).parents[2] / "docs" / "_ext"
    monkeypatch.syspath_prepend(str(extension_path))
    sys.modules.pop("tmuxop", None)
    return __import__("tmuxop")


def test_domain_exposes_semantic_operation_surface(
    tmuxop_module: types.ModuleType,
) -> None:
    """The extension exposes one object type, role, and two directives."""
    domain = tmuxop_module.TmuxOperationDomain

    assert set(domain.object_types) == {"operation"}
    assert set(domain.roles) == {"op"}
    assert set(domain.directives) == {"operation", "catalog"}


def test_domain_rejects_duplicate_operation_targets(
    tmuxop_module: types.ModuleType,
) -> None:
    """A kind cannot silently point to two documentation pages."""
    domain = tmuxop_module.TmuxOperationDomain(_Environment())

    domain.note_operation("send_keys", "operations/pane/send_keys", "send-keys")

    with pytest.raises(SphinxError, match=r"send_keys.*already documented"):
        domain.note_operation(
            "send_keys",
            "operations/pane/other_send_keys",
            "other-send-keys",
        )


def test_domain_clears_only_objects_from_changed_document(
    tmuxop_module: types.ModuleType,
) -> None:
    """Incremental builds retain targets owned by unchanged documents."""
    domain = tmuxop_module.TmuxOperationDomain(_Environment())
    domain.note_operation("send_keys", "pane/send_keys", "send-keys")
    domain.note_operation("split_window", "window/split_window", "split-window")

    domain.clear_doc("pane/send_keys")

    assert domain.operations == {
        "split_window": ("window/split_window", "split-window")
    }


def test_domain_merges_only_worker_documents(
    tmuxop_module: types.ModuleType,
) -> None:
    """Parallel readers cannot import stale targets from unrelated documents."""
    domain = tmuxop_module.TmuxOperationDomain(_Environment())
    domain.note_operation("send_keys", "pane/send_keys", "send-keys")

    domain.merge_domaindata(
        {"window/split_window"},
        {
            "operations": {
                "split_window": ("window/split_window", "split-window"),
                "kill_server": ("server/kill_server", "kill-server"),
            }
        },
    )

    assert domain.operations == {
        "send_keys": ("pane/send_keys", "send-keys"),
        "split_window": ("window/split_window", "split-window"),
    }


def test_domain_inventory_is_stable_and_specific(
    tmuxop_module: types.ModuleType,
) -> None:
    """Sphinx inventory entries identify operation targets and their priority."""
    domain = tmuxop_module.TmuxOperationDomain(_Environment())
    domain.note_operation("send_keys", "pane/send_keys", "send-keys")

    assert list(domain.get_objects()) == [
        (
            "send_keys",
            "send_keys",
            "operation",
            "pane/send_keys",
            "send-keys",
            1,
        )
    ]


def test_operation_badges_share_api_metrics_and_spacing(
    tmuxop_module: types.ModuleType,
) -> None:
    """Operation metadata renders as one evenly spaced API badge group."""
    entry = next(item for item in catalog() if item.kind == "send_keys")

    render = importlib.import_module("tmuxop.render")
    group = render.build_operation_badges(entry)

    assert len(group.children) == 3
    assert all(not isinstance(child, nodes.Text) for child in group.children)
    assert {
        "tmuxop-badge--safety-mutating",
        "tmuxop-badge--scope-pane",
        "tmuxop-badge--shape-primitive",
    } <= {class_name for child in group.children for class_name in child["classes"]}
    for child in group.children:
        assert "gp-sphinx-badge--dense" in child["classes"]
        assert "gp-sphinx-badge--underline-none" in child["classes"]


@pytest.mark.parametrize(
    "spec",
    registry,
    ids=lambda spec: spec.kind,
)
def test_operation_constructor_parameters_are_documented(
    tmuxop_module: types.ModuleType,
    spec: OpSpec,
) -> None:
    """Every rendered constructor parameter has canonical API prose."""
    render = importlib.import_module("tmuxop.render")
    parameter_names = tuple(
        name
        for name in inspect.signature(spec.operation_cls.__init__).parameters
        if name != "self"
    )

    fields = render._constructor_parameter_fields(spec.operation_cls)

    assert tuple(fields) == parameter_names


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (
            {"scope": "client"},
            {
                "detach_client",
                "refresh_client",
                "suspend_client",
                "switch_client",
            },
        ),
        (
            {"safety": "readonly"},
            {
                "capture_pane",
                "display_message",
                "has_session",
                "list_clients",
                "list_panes",
                "list_sessions",
                "list_windows",
                "show_buffer",
                "show_options",
            },
        ),
        (
            {"primitive-only": None},
            {entry.kind for entry in catalog() if entry.primitive},
        ),
    ],
)
def test_catalog_filter_uses_registry_metadata(
    tmuxop_module: types.ModuleType,
    options: dict[str, str | None],
    expected: set[str],
) -> None:
    """Catalog options filter canonical registry entries."""
    assert {
        entry.kind for entry in tmuxop_module.filter_catalog(catalog(), options)
    } == expected


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"scope": "workspace"}, "unknown scope"),
        ({"safety": "dangerous"}, "unknown safety"),
    ],
)
def test_catalog_filter_rejects_unknown_values(
    tmuxop_module: types.ModuleType,
    options: dict[str, str],
    message: str,
) -> None:
    """A misspelled catalog filter is a build error, not an empty catalog."""
    with pytest.raises(SphinxError, match=message):
        tmuxop_module.filter_catalog(catalog(), options)
