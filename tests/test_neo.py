"""Tests for libtmux.neo scope+version gated -F template builder.

These tests exercise :func:`libtmux.neo.get_output_format` and
:func:`libtmux.neo._token_scope` directly — pure-Python unit tests that
don't need a live tmux server. Scope and version classifications were
verified against tmux's ``format.c`` (see commit messages on
``parity-pt-2``).
"""

from __future__ import annotations

import pytest

from libtmux.neo import (
    _CONTEXT_ONLY_TOKENS,
    FIELD_VERSION,
    SCOPES_BY_LIST_CMD,
    _token_scope,
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


@pytest.mark.parametrize("token", sorted(_CONTEXT_ONLY_TOKENS))
def test_context_only_token_scope(token: str) -> None:
    """Tokens registered outside ``format.c`` route to the ``context`` scope.

    ``command_list_*`` is only registered by ``cmd-list-commands.c``;
    ``search_match`` by ``window-copy.c``; ``current_file`` by ``cfg.c``.
    None resolve via ``format_defaults`` for any ``list-*``, so they
    should not land in the universal bucket where they'd be emitted
    in every ``-F`` template.
    """
    assert _token_scope(token) == "context"


@pytest.mark.parametrize("list_cmd", sorted(SCOPES_BY_LIST_CMD))
def test_context_scope_excluded_from_every_list_cmd(list_cmd: str) -> None:
    """``"context"`` is excluded from every ``SCOPES_BY_LIST_CMD`` entry.

    The exclusion is the structural guarantee that context-only tokens
    don't drift into any ``-F`` template. If a future change accidentally
    admits ``"context"`` for a list subcommand, this test catches it.
    """
    assert "context" not in SCOPES_BY_LIST_CMD[list_cmd]


@pytest.mark.parametrize("token", sorted(_CONTEXT_ONLY_TOKENS))
def test_context_tokens_absent_from_every_list_cmd_template(token: str) -> None:
    """Context-only tokens never appear in any ``list-*`` ``-F`` template."""
    for list_cmd in SCOPES_BY_LIST_CMD:
        fields, _ = get_output_format(list_cmd, "3.6a")
        assert token not in fields, (
            f"{token!r} (context-only) leaked into {list_cmd} template"
        )
