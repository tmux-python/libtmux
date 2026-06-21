"""Tests for the registry-driven operation catalog."""

from __future__ import annotations

from libtmux.experimental.ops import catalog, registry


def test_catalog_covers_every_registered_operation() -> None:
    """The catalog has exactly one entry per registered kind."""
    entries = catalog()
    assert [entry.kind for entry in entries] == sorted(registry.kinds())


def test_catalog_entry_mirrors_spec() -> None:
    """A catalog entry reflects the operation's registry metadata."""
    entries = {entry.kind: entry for entry in catalog()}

    split = entries["split_window"]
    assert split.command == "split-window"
    assert split.scope == "window"
    assert split.result_type == "SplitWindowResult"
    assert split.effects["creates"] == "pane"
    assert split.flag_version_gates == {"environment": "3.0"}
    assert split.summary

    capture = entries["capture_pane"]
    assert capture.safety == "readonly"
    assert capture.effects["read_only"] is True
    assert capture.flag_version_gates["trim_trailing"] == "3.4"


def test_catalog_summary_is_first_docstring_line() -> None:
    """Each entry's summary is the operation's one-line description."""
    entries = {entry.kind: entry for entry in catalog()}
    assert entries["send_keys"].summary.startswith("Send keys")
