"""Contracts for the registry-backed tmux operation domain."""

from __future__ import annotations

import dataclasses
import pathlib
import sys
import typing as t

import pytest
from sphinx.errors import SphinxError

from libtmux.experimental.ops import catalog


@dataclasses.dataclass
class _Environment:
    domaindata: dict[str, dict[str, t.Any]] = dataclasses.field(default_factory=dict)


@pytest.fixture
def tmuxop_module(monkeypatch: pytest.MonkeyPatch):
    """Import the in-tree Sphinx extension as Sphinx does."""
    extension_path = pathlib.Path(__file__).parents[2] / "docs" / "_ext"
    monkeypatch.syspath_prepend(str(extension_path))
    sys.modules.pop("tmuxop", None)
    return __import__("tmuxop")


def test_domain_exposes_semantic_operation_surface(tmuxop_module) -> None:
    """The extension exposes one object type, role, and two directives."""
    domain = tmuxop_module.TmuxOperationDomain

    assert set(domain.object_types) == {"operation"}
    assert set(domain.roles) == {"op"}
    assert set(domain.directives) == {"operation", "catalog"}


def test_domain_rejects_duplicate_operation_targets(tmuxop_module) -> None:
    """A kind cannot silently point to two documentation pages."""
    domain = tmuxop_module.TmuxOperationDomain(_Environment())

    domain.note_operation("send_keys", "operations/pane/send_keys", "send-keys")

    with pytest.raises(SphinxError, match=r"send_keys.*already documented"):
        domain.note_operation(
            "send_keys",
            "operations/pane/other_send_keys",
            "other-send-keys",
        )


def test_domain_clears_only_objects_from_changed_document(tmuxop_module) -> None:
    """Incremental builds retain targets owned by unchanged documents."""
    domain = tmuxop_module.TmuxOperationDomain(_Environment())
    domain.note_operation("send_keys", "pane/send_keys", "send-keys")
    domain.note_operation("split_window", "window/split_window", "split-window")

    domain.clear_doc("pane/send_keys")

    assert domain.operations == {
        "split_window": ("window/split_window", "split-window")
    }


def test_domain_merges_only_worker_documents(tmuxop_module) -> None:
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


def test_domain_inventory_is_stable_and_specific(tmuxop_module) -> None:
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
    tmuxop_module,
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
    tmuxop_module,
    options: dict[str, str],
    message: str,
) -> None:
    """A misspelled catalog filter is a build error, not an empty catalog."""
    with pytest.raises(SphinxError, match=message):
        tmuxop_module.filter_catalog(catalog(), options)
