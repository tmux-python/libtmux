"""Tests for libtmux.neo scope+version gated -F template builder.

These tests exercise :func:`libtmux.neo.get_output_format` and
:func:`libtmux.neo._token_scope` directly — pure-Python unit tests that
don't need a live tmux server. Scope and version classifications were
verified against tmux's ``format.c`` (see commit messages on
``parity-pt-2``).
"""

from __future__ import annotations

from libtmux.neo import (
    FIELD_VERSION,
    SCOPES_BY_LIST_CMD,
    get_output_format,
)


def test_pane_dead_signal_gated_to_3_3() -> None:
    """``pane_dead_signal`` first registered in tmux 3.3.

    The format-table entry sits in ``format.c`` from commit a3d92093
    ("Add remain-on-exit-format"), first tagged in tmux 3.3. Emitting
    it on tmux 3.2a hydrates the field with the literal ``#{...}``
    text rather than an empty value, which downstream code interprets
    as a live signal — a real footgun.
    """
    assert FIELD_VERSION["pane_dead_signal"] == "3.3"
    fields_old, _ = get_output_format("list-panes", "3.2a")
    assert "pane_dead_signal" not in fields_old
    fields_new, _ = get_output_format("list-panes", "3.3")
    assert "pane_dead_signal" in fields_new


def test_pane_dead_time_gated_to_3_3() -> None:
    """``pane_dead_time`` first registered in tmux 3.3.

    Same provenance as ``pane_dead_signal`` — both tokens shipped in
    the same upstream commit, so they share a version floor.
    """
    assert FIELD_VERSION["pane_dead_time"] == "3.3"
    fields_old, _ = get_output_format("list-panes", "3.2a")
    assert "pane_dead_time" not in fields_old
    fields_new, _ = get_output_format("list-panes", "3.3")
    assert "pane_dead_time" in fields_new


def test_field_version_keys_are_obj_fields() -> None:
    """Every gated field name must exist on :class:`libtmux.neo.Obj`.

    A typo in ``FIELD_VERSION`` would silently no-op; this catches
    drift between the dataclass and the version-gate table.
    """
    from libtmux.neo import Obj

    obj_fields = set(Obj.__dataclass_fields__)
    for token in FIELD_VERSION:
        assert token in obj_fields, (
            f"{token!r} in FIELD_VERSION but not declared on Obj"
        )


def test_scopes_by_list_cmd_downward_cascade() -> None:
    """Every ``list-*`` admits universal+session+window+pane scopes.

    ``list-clients`` additionally admits ``client`` scope. This pins
    the cascade asymmetry documented at ``neo.py`` SCOPES_BY_LIST_CMD.
    """
    for cmd, scopes in SCOPES_BY_LIST_CMD.items():
        assert {"universal", "session", "window", "pane"} <= scopes, (
            f"{cmd} should admit the downward-cascade core scopes"
        )
    assert "client" in SCOPES_BY_LIST_CMD["list-clients"]
    assert "client" not in SCOPES_BY_LIST_CMD["list-sessions"]
    assert "client" not in SCOPES_BY_LIST_CMD["list-windows"]
    assert "client" not in SCOPES_BY_LIST_CMD["list-panes"]
