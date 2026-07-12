"""Tests for libtmux.neo scope+version gated -F template builder.

These tests exercise :func:`libtmux.neo.get_output_format` and
:func:`libtmux.neo._token_scope` directly — pure-Python unit tests that
don't need a live tmux server. Scope and version classifications were
verified against tmux's ``format.c`` (see commit messages on
``parity-pt-2``).
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux.neo import (
    _CONTEXT_ONLY_TOKENS,
    FIELD_VERSION,
    SCOPES_BY_LIST_CMD,
    Obj,
    _is_target_not_found_error,
    _token_scope,
    get_output_format,
)


class TargetNotFoundFixture(t.NamedTuple):
    """One line of tmux stderr, and whether it means "that object is gone"."""

    test_id: str
    stderr_text: str
    expected: bool


TARGET_NOT_FOUND_FIXTURES: list[TargetNotFoundFixture] = [
    TargetNotFoundFixture(
        test_id="missing-pane",
        stderr_text="can't find pane: %99",
        expected=True,
    ),
    TargetNotFoundFixture(
        test_id="missing-window",
        stderr_text="can't find window: @99",
        expected=True,
    ),
    TargetNotFoundFixture(
        test_id="missing-session",
        stderr_text="can't find session: $99",
        expected=True,
    ),
    TargetNotFoundFixture(
        test_id="daemon-not-running",
        stderr_text="no server running on /tmp/tmux-1000/default",
        expected=False,
    ),
    TargetNotFoundFixture(
        test_id="socket-missing",
        stderr_text=(
            "error connecting to /tmp/tmux-1000/nope (No such file or directory)"
        ),
        expected=False,
    ),
    TargetNotFoundFixture(
        test_id="permission-denied",
        stderr_text="error connecting to /tmp/tmux-1000/other (Permission denied)",
        expected=False,
    ),
]


@pytest.mark.parametrize(
    list(TargetNotFoundFixture._fields),
    TARGET_NOT_FOUND_FIXTURES,
    ids=[test.test_id for test in TARGET_NOT_FOUND_FIXTURES],
)
def test_is_target_not_found_error(
    test_id: str,
    stderr_text: str,
    expected: bool,
) -> None:
    """Only an unknown ``-t`` target means the object is gone.

    Every other tmux failure -- a stopped daemon, a missing socket, a
    permission error -- leaves the object's existence unknown, and must keep
    surfacing as a :exc:`~libtmux.exc.LibTmuxException`.
    """
    assert _is_target_not_found_error(stderr_text) is expected


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


# Format tokens first registered in tmux 3.7 (verified against format.c /
# tmux.1 at the 3.7 tag).
TMUX_3_7_FORMAT_TOKENS = [
    "bracket_paste_flag",
    "pane_flags",
    "pane_floating_flag",
    "pane_pb_progress",
    "pane_pb_state",
    "pane_pipe_pid",
    "pane_x",
    "pane_y",
    "pane_z",
    "pane_zoomed_flag",
    "synchronized_output_flag",
]


@pytest.mark.parametrize("token", TMUX_3_7_FORMAT_TOKENS)
def test_format_token_gated_to_3_7(token: str) -> None:
    """Tmux 3.7 pane format tokens must not leak into older -F templates.

    Each token's format-table entry first appears at the 3.7 tag, so
    emitting it on 3.6 hydrates the field with the literal ``#{...}``
    text instead of an empty value.
    """
    assert FIELD_VERSION[token] == "3.7"
    fields_old, _ = get_output_format("list-panes", "3.6")
    assert token not in fields_old
    fields_new, _ = get_output_format("list-panes", "3.7")
    assert token in fields_new


@pytest.mark.parametrize("token", ["bracket_paste_flag", "synchronized_output_flag"])
def test_unprefixed_3_7_tokens_are_pane_scope(token: str) -> None:
    """The 3.7 pane tokens without a ``pane_`` prefix need scope overrides.

    Their ``format_cb_*`` dereference ``ft->wp`` (the pane), so they
    belong in ``list-panes`` output despite the missing prefix.
    """
    assert _token_scope(token) == "pane"
    fields, _ = get_output_format("list-panes", "3.7")
    assert token in fields


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


def test_token_scope_unknown_for_unclassified_field() -> None:
    """``_token_scope`` returns ``"unknown"`` for any unrecognized field.

    ``"unknown"`` must be absent from every :data:`SCOPES_BY_LIST_CMD`
    entry, so a future field added without classification is silently
    excluded from every ``-F`` template rather than emitted under a list
    command where it might crash older tmux.
    """
    assert _token_scope("libtmux_test_nonexistent_token") == "unknown"
    for allowed in SCOPES_BY_LIST_CMD.values():
        assert "unknown" not in allowed


def test_every_obj_field_classifies_to_known_scope() -> None:
    """Every declared ``Obj`` field must classify to a known scope.

    Adding a new field without a matching prefix / override /
    known-token table entry would silently exclude it from every
    ``list-*`` template (via the fail-closed default). This test
    surfaces that misclassification as a deterministic failure rather
    than a runtime hydration-as-None.
    """
    unclassified: list[str] = []
    for name in Obj.__dataclass_fields__:
        if name == "server":
            continue
        if _token_scope(name) == "unknown":
            unclassified.append(name)
    assert not unclassified, (
        "Obj fields with no scope classification "
        "(add them to _SCOPE_OVERRIDES, _SCOPE_PREFIXES, "
        f"_UNIVERSAL_TOKENS, or _CONTEXT_ONLY_TOKENS): {unclassified}"
    )
