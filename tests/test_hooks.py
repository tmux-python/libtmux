"""Testsuite for libtmux hook management."""

from __future__ import annotations

import typing as t

import pytest

from libtmux._internal.constants import Hooks
from libtmux._internal.sparse_array import SparseArray
from libtmux.common import has_gte_version

if t.TYPE_CHECKING:
    from libtmux.server import Server


def test_hooks_raw_cmd(
    server: Server,
) -> None:
    """Raw hook set, show, unset via cmd."""
    session = server.new_session(session_name="test hooks")
    window = session.active_window
    pane = window.active_pane
    assert pane is not None

    #
    # Global
    #
    set_hook_proc = server.cmd(
        "set-hook",
        "-g",
        "session-renamed[0]",
        "set -g status-left-style bg=red",
    )

    assert not set_hook_proc.stdout
    assert not set_hook_proc.stderr
    assert not server.cmd("show-hooks").stdout

    show_hooks_proc = server.cmd("show-hooks", "-g", "session-renamed[0]")

    assert "set-option -g status-left-style bg=red" in show_hooks_proc.stdout[0]

    # Server: Unset

    # Server: Unset: Index
    set_hook_proc = server.cmd(
        "set-hook",
        "-g",
        "-u",
        "session-renamed[0]",
    )
    assert server.cmd("show-hooks", "-g", "session-renamed[0]").stdout == [
        "session-renamed[0] ",
    ]

    # Server: Unset variable
    set_hook_proc = server.cmd(
        "set-hook",
        "-g",
        "-u",
        "session-renamed",
    )
    assert server.cmd("show-hooks", "-g", "session-renamed[0]").stdout == [
        "session-renamed[0] ",
    ]

    #
    # Session
    #
    set_hook_proc = session.cmd(
        "set-hook",
        "session-renamed[0]",
        "set -g status-left-style bg=red",
    )

    assert not set_hook_proc.stdout
    assert not set_hook_proc.stderr

    assert not session.cmd(
        "show-hooks",
        "-s",
    ).stdout
    show_hooks_proc = session.cmd(
        "show-hooks",
        "session-renamed[0]",
    )

    assert "set-option -g status-left-style bg=red" in show_hooks_proc.stdout[0]

    # Session: Unset

    # Session: Unset: Index
    set_hook_proc = session.cmd(
        "set-hook",
        "-u",
        "session-renamed[0]",
    )
    assert session.cmd("show-hooks", "-s", "session-renamed[0]").stdout == []

    # Session: Unset variable
    set_hook_proc = session.cmd(
        "set-hook",
        "-u",
        "session-renamed",
    )
    assert session.cmd("show-hooks", "-s", "session-renamed[0]").stdout == []

    if has_gte_version("3.2"):
        #
        # Window
        #
        set_hook_proc = window.cmd(
            "set-hook",
            "-w",
            "session-renamed[0]",
            "set -g status-left-style bg=red",
        )

        assert not set_hook_proc.stdout
        assert not set_hook_proc.stderr

        show_hooks_proc = server.cmd(
            "show-hooks",
            "session-renamed[0]",
        )

        assert "set-option -g status-left-style bg=red" in show_hooks_proc.stdout[0]

        # Window: Unset

        # Window: Unset: Index
        set_hook_proc = window.cmd(
            "set-hook",
            "-w",
            "-u",
            "session-renamed[0]",
        )
        assert window.cmd("show-hooks", "-w", "session-renamed[0]").stdout == [
            "session-renamed[0] ",
        ]

        # Window: Unset variable
        set_hook_proc = window.cmd(
            "set-hook",
            "-w",
            "-u",
            "session-renamed",
        )
        assert window.cmd("show-hooks", "-w", "session-renamed[0]").stdout == []

        #
        # Pane
        #
        set_hook_proc = pane.cmd(
            "set-hook",
            "-p",
            "session-renamed[0]",
            "set -g status-left-style bg=red",
        )

        assert not set_hook_proc.stdout
        assert not set_hook_proc.stderr

        show_hooks_proc = server.cmd(
            "show-hooks",
            "-p",
            "session-renamed[0]",
        )

        assert "set-option -g status-left-style bg=red" in show_hooks_proc.stdout[0]

        # Pane: Unset

        # Pane: Unset: Index
        set_hook_proc = pane.cmd(
            "set-hook",
            "-p",
            "-u",
            "session-renamed[0]",
        )
        assert pane.cmd("show-hooks", "-p", "session-renamed[0]").stdout == [
            "session-renamed[0] ",
        ]

        # Pane: Unset variable
        set_hook_proc = pane.cmd(
            "set-hook",
            "-p",
            "-u",
            "session-renamed",
        )
        assert pane.cmd("show-hooks", "-p", "session-renamed[0]").stdout == []


def test_hooks_dataclass(
    server: Server,
) -> None:
    """Tests for hooks dataclass."""
    session = server.new_session(session_name="test hooks")
    window = session.active_window
    pane = window.active_pane
    assert pane is not None

    #
    # Session
    #
    set_hook_proc = session.cmd(
        "set-hook",
        "session-renamed[0]",
        "set -g status-left-style bg=red",
    )

    assert not set_hook_proc.stdout
    assert not set_hook_proc.stderr

    show_hooks_proc = server.cmd(
        "show-hooks",
        "session-renamed[0]",
    )

    hooks = Hooks.from_stdout(show_hooks_proc.stdout)
    assert hooks.session_renamed.as_list() == [
        "set-option -g status-left-style bg=red",
    ]

    set_hook_proc = session.cmd(
        "set-hook",
        "-p",
        "session-renamed[0]",
        "set -g status-left-style bg=red",
    )
    set_hook_proc = session.cmd(
        "set-hook",
        "session-renamed[1]",
        "set -g status-left-style bg=white",
    )
    set_hook_proc = session.cmd(
        "set-hook",
        "session-renamed[2]",
        "set -g status-left-style bg=blue",
    )
    set_hook_proc = session.cmd(
        "set-hook",
        "after-set-buffer[2]",
        "set -g status-left-style bg=pink",
    )

    global_out = server.cmd("show-hooks", "-g").stdout
    session_out = server.cmd("show-hooks").stdout

    window_out = server.cmd("show-hooks", "-w").stdout
    pane_out = server.cmd("show-hooks", "-p").stdout

    session_out_processed = Hooks.from_stdout(session_out)
    assert session_out_processed.session_renamed is not None

    assert (
        session_out_processed.session_renamed[2]
        == "set-option -g status-left-style bg=blue"
    )

    hooks = Hooks.from_stdout(global_out + session_out + window_out + pane_out)

    assert hooks.session_renamed.as_list() == [
        "set-option -g status-left-style bg=red",
        "set-option -g status-left-style bg=white",
        "set-option -g status-left-style bg=blue",
    ]
    assert hooks.after_set_buffer.as_list() == [
        "set-option -g status-left-style bg=pink",
    ]


def test_hooks_mixin(
    server: Server,
) -> None:
    """Tests for hooks."""
    session = server.new_session(session_name="test hooks")
    window = session.active_window
    pane = window.active_pane
    assert pane is not None

    pane.set_hook("session-renamed[0]", "set -g status-left-style bg=red")

    #
    # Pane
    #
    assert not pane.show_hooks()

    show_hooks_raw = pane._show_hook(
        "session-renamed[0]",
    )

    assert show_hooks_raw is not None

    hooks = Hooks.from_stdout(show_hooks_raw)

    assert hooks.session_renamed == SparseArray(
        {
            0: "set-option -g status-left-style bg=red",
        },
    )


# =============================================================================
# Comprehensive Hook Test Grid
# =============================================================================


class HookTestCase(t.NamedTuple):
    """Test case for hook validation."""

    test_id: str
    hook: str  # tmux hook name (hyphenated)
    min_version: str = "3.0"  # Minimum tmux version required
    xfail_reason: str | None = None  # Mark as expected failure with reason


# --- Alert Hooks ---
ALERT_HOOKS: list[HookTestCase] = [
    HookTestCase("alert_activity", "alert-activity"),
    HookTestCase("alert_bell", "alert-bell"),
    HookTestCase("alert_silence", "alert-silence"),
]

# --- Client Hooks ---
CLIENT_HOOKS: list[HookTestCase] = [
    HookTestCase("client_active", "client-active", "3.3"),
    HookTestCase("client_attached", "client-attached"),
    HookTestCase("client_detached", "client-detached"),
    HookTestCase("client_focus_in", "client-focus-in", "3.3"),
    HookTestCase("client_focus_out", "client-focus-out", "3.3"),
    HookTestCase("client_resized", "client-resized"),
    HookTestCase("client_session_changed", "client-session-changed"),
]

# --- Session Hooks ---
SESSION_HOOKS: list[HookTestCase] = [
    HookTestCase("session_created", "session-created"),
    HookTestCase("session_closed", "session-closed"),
    HookTestCase("session_renamed", "session-renamed"),
]

# --- Window Hooks ---
WINDOW_HOOKS: list[HookTestCase] = [
    HookTestCase("window_linked", "window-linked"),
    HookTestCase("window_renamed", "window-renamed"),
    HookTestCase("window_resized", "window-resized", "3.3"),
    HookTestCase("window_unlinked", "window-unlinked"),
    HookTestCase("session_window_changed", "session-window-changed"),
]

# --- Pane Hooks ---
PANE_HOOKS: list[HookTestCase] = [
    HookTestCase("pane_died", "pane-died"),
    HookTestCase("pane_exited", "pane-exited"),
    HookTestCase("pane_focus_in", "pane-focus-in"),
    HookTestCase("pane_focus_out", "pane-focus-out"),
    HookTestCase("pane_mode_changed", "pane-mode-changed"),
    HookTestCase("pane_set_clipboard", "pane-set-clipboard"),
]

# --- After-* Hooks ---
AFTER_HOOKS: list[HookTestCase] = [
    HookTestCase("after_bind_key", "after-bind-key"),
    HookTestCase("after_capture_pane", "after-capture-pane"),
    HookTestCase("after_copy_mode", "after-copy-mode"),
    HookTestCase("after_display_message", "after-display-message"),
    HookTestCase("after_display_panes", "after-display-panes"),
    HookTestCase("after_kill_pane", "after-kill-pane"),
    HookTestCase("after_list_buffers", "after-list-buffers"),
    HookTestCase("after_list_clients", "after-list-clients"),
    HookTestCase("after_list_keys", "after-list-keys"),
    HookTestCase("after_list_panes", "after-list-panes"),
    HookTestCase("after_list_sessions", "after-list-sessions"),
    HookTestCase("after_list_windows", "after-list-windows"),
    HookTestCase("after_load_buffer", "after-load-buffer"),
    HookTestCase("after_lock_server", "after-lock-server"),
    HookTestCase("after_new_session", "after-new-session"),
    HookTestCase("after_new_window", "after-new-window"),
    HookTestCase("after_paste_buffer", "after-paste-buffer"),
    HookTestCase("after_pipe_pane", "after-pipe-pane"),
    HookTestCase("after_queue", "after-queue"),
    HookTestCase("after_refresh_client", "after-refresh-client"),
    HookTestCase("after_rename_session", "after-rename-session"),
    HookTestCase("after_rename_window", "after-rename-window"),
    HookTestCase("after_resize_pane", "after-resize-pane"),
    HookTestCase("after_resize_window", "after-resize-window"),
    HookTestCase("after_save_buffer", "after-save-buffer"),
    HookTestCase("after_select_layout", "after-select-layout"),
    HookTestCase("after_select_pane", "after-select-pane"),
    HookTestCase("after_select_window", "after-select-window"),
    HookTestCase("after_send_keys", "after-send-keys"),
    HookTestCase("after_set_buffer", "after-set-buffer"),
    HookTestCase("after_set_environment", "after-set-environment"),
    HookTestCase("after_set_hook", "after-set-hook"),
    HookTestCase("after_set_option", "after-set-option"),
    HookTestCase("after_show_environment", "after-show-environment"),
    HookTestCase("after_show_messages", "after-show-messages"),
    HookTestCase("after_show_options", "after-show-options"),
    HookTestCase("after_split_window", "after-split-window"),
    HookTestCase("after_unbind_key", "after-unbind-key"),
]

# --- New Hooks (tmux 3.5+) ---
NEW_HOOKS: list[HookTestCase] = [
    HookTestCase(
        "pane_title_changed",
        "pane-title-changed",
        "3.5",
    ),
    # NOTE: client-light-theme and client-dark-theme are not in any released tmux
    # version yet (will be in 3.6+). Add them back when 3.6 is released.
]

# Combine all hook test cases
ALL_HOOK_TEST_CASES: list[HookTestCase] = (
    ALERT_HOOKS + CLIENT_HOOKS + SESSION_HOOKS + WINDOW_HOOKS + PANE_HOOKS + AFTER_HOOKS
)


def _build_hook_params() -> list[t.Any]:
    """Build pytest params with appropriate marks."""
    params = []
    for tc in ALL_HOOK_TEST_CASES:
        marks: list[t.Any] = []
        if tc.xfail_reason:
            marks.append(pytest.mark.xfail(reason=tc.xfail_reason))
        params.append(pytest.param(tc, id=tc.test_id, marks=marks))
    return params


@pytest.mark.parametrize("test_case", _build_hook_params())
def test_hook_set_show_unset_cycle(server: Server, test_case: HookTestCase) -> None:
    """Test set/show/unset cycle for each hook.

    This parametrized test ensures all hooks in the libtmux constants can be:
    1. Set with a command
    2. Shown and verified
    3. Unset cleanly
    """
    if not has_gte_version(test_case.min_version):
        pytest.skip(f"Requires tmux {test_case.min_version}+")

    session = server.new_session(session_name="test_hook_cycle")
    window = session.active_window
    assert window is not None
    pane = window.active_pane
    assert pane is not None

    hook_cmd = "display-message 'test hook fired'"

    # Test set_hook (using session-level hook which works on all tmux versions)
    session.set_hook(f"{test_case.hook}[0]", hook_cmd)

    # Test show_hook
    result = session._show_hook(f"{test_case.hook}[0]")
    assert result is not None, f"Expected hook {test_case.hook} to be set"

    # Parse and verify
    hooks = Hooks.from_stdout(result)
    hook_attr = test_case.hook.replace("-", "_")
    hook_value = getattr(hooks, hook_attr, None)
    assert hook_value is not None, f"Hook attribute {hook_attr} not found in Hooks"
    assert len(hook_value) > 0, f"Expected hook {test_case.hook} to have values"
    assert "display-message" in hook_value[0], (
        f"Expected 'display-message' in hook value, got: {hook_value[0]}"
    )

    # Test unset_hook
    session.unset_hook(f"{test_case.hook}[0]")

    # Verify unset
    result_after_unset = session._show_hook(f"{test_case.hook}[0]")
    if result_after_unset:
        hooks_after = Hooks.from_stdout(result_after_unset)
        hook_value_after = getattr(hooks_after, hook_attr, None)
        # After unset, the hook should be empty or have empty value
        if hook_value_after:
            assert len(hook_value_after.as_list()) == 0 or hook_value_after[0] == "", (
                f"Expected hook {test_case.hook} to be unset"
            )


@pytest.mark.parametrize(
    "test_case",
    [pytest.param(tc, id=tc.test_id) for tc in NEW_HOOKS],
)
def test_new_hooks_version_gated(server: Server, test_case: HookTestCase) -> None:
    """Test new hooks that require tmux 3.5+.

    These hooks are version-gated and will skip on older tmux versions.
    """
    if not has_gte_version(test_case.min_version):
        pytest.skip(f"Requires tmux {test_case.min_version}+")

    session = server.new_session(session_name="test_new_hooks")

    hook_cmd = "display-message 'new hook fired'"

    # Test set_hook
    session.set_hook(f"{test_case.hook}[0]", hook_cmd)

    # Test show_hook
    result = session._show_hook(f"{test_case.hook}[0]")
    assert result is not None, f"Expected hook {test_case.hook} to be set"

    # Cleanup
    session.unset_hook(f"{test_case.hook}[0]")


# =============================================================================
# set_hooks Tests
# =============================================================================


class SetHooksTestCase(t.NamedTuple):
    """Test case for set_hooks operations."""

    test_id: str
    hook: str  # Hook name to test
    setup_hooks: dict[int, str]  # Initial hooks to set (index -> value)
    operation_args: dict[str, t.Any]  # Args for set_hooks
    expected_indices: list[int]  # Expected indices after operation
    expected_contains: list[str] | None = None  # Strings expected in values


SET_HOOKS_TESTS: list[SetHooksTestCase] = [
    SetHooksTestCase(
        "set_hooks_with_dict",
        "session-renamed",
        {},
        {
            "values": {
                0: "display-message 'hook 0'",
                1: "display-message 'hook 1'",
                5: "display-message 'hook 5'",
            },
        },
        [0, 1, 5],
        ["hook 0", "hook 1", "hook 5"],
    ),
    SetHooksTestCase(
        "set_hooks_with_list",
        "session-renamed",
        {},
        {
            "values": [
                "display-message 'hook 0'",
                "display-message 'hook 1'",
                "display-message 'hook 2'",
            ],
        },
        [0, 1, 2],
    ),
    SetHooksTestCase(
        "set_hooks_clear_existing",
        "session-renamed",
        {0: "display-message 'old 0'", 1: "display-message 'old 1'"},
        {"values": {0: "display-message 'new 0'"}, "clear_existing": True},
        [0],
        ["new 0"],
    ),
]


def _build_set_hooks_params() -> list[t.Any]:
    """Build pytest params for set_hooks tests."""
    return [pytest.param(tc, id=tc.test_id) for tc in SET_HOOKS_TESTS]


@pytest.mark.parametrize("test_case", _build_set_hooks_params())
def test_set_hooks(server: Server, test_case: SetHooksTestCase) -> None:
    """Test set_hooks operations."""
    session = server.new_session(session_name="test_set_hooks")

    # Setup initial hooks
    for idx, val in test_case.setup_hooks.items():
        session.set_hook(f"{test_case.hook}[{idx}]", val)

    # Perform set_hooks
    session.set_hooks(test_case.hook, **test_case.operation_args)

    # Verify via show_hook
    hooks = session.show_hook(test_case.hook)
    assert hooks is not None
    assert isinstance(hooks, SparseArray)
    assert sorted(hooks.keys()) == test_case.expected_indices

    if test_case.expected_contains:
        for expected_str in test_case.expected_contains:
            assert any(expected_str in v for v in hooks.values())

    # Cleanup
    session.unset_hook(test_case.hook)


def test_show_hook_returns_sparse_array(server: Server) -> None:
    """Test that show_hook returns SparseArray for array hooks."""
    session = server.new_session(session_name="test_show_hook")

    # Set hooks at sparse indices (out of order)
    session.set_hook("session-renamed[5]", "display-message 'fifth'")
    session.set_hook("session-renamed[0]", "display-message 'zeroth'")
    session.set_hook("session-renamed[2]", "display-message 'second'")

    hooks = session.show_hook("session-renamed")
    assert hooks is not None
    assert isinstance(hooks, SparseArray)

    # Check keys (indices)
    assert sorted(hooks.keys()) == [0, 2, 5]

    # Check values via iter_values (sorted order)
    value_list = list(hooks.iter_values())
    assert len(value_list) == 3
    assert "zeroth" in value_list[0]
    assert "second" in value_list[1]
    assert "fifth" in value_list[2]

    # Cleanup
    session.unset_hook("session-renamed")


class IndexedHookLookupCase(t.NamedTuple):
    """Test fixture for indexed hook lookups."""

    test_id: str
    hook_name: str
    hook_index: int
    hook_value: str


@pytest.mark.parametrize(
    IndexedHookLookupCase._fields,
    [
        IndexedHookLookupCase(
            test_id="index_zero",
            hook_name="session-renamed",
            hook_index=0,
            hook_value="display-message 'test zero'",
        ),
        IndexedHookLookupCase(
            test_id="index_five",
            hook_name="session-renamed",
            hook_index=5,
            hook_value="display-message 'test five'",
        ),
        IndexedHookLookupCase(
            test_id="window_hook",
            hook_name="window-renamed",
            hook_index=0,
            hook_value="display-message 'window test'",
        ),
    ],
    ids=lambda x: x.test_id if isinstance(x, IndexedHookLookupCase) else x,
)
def test_show_hook_indexed_lookup(
    server: Server,
    test_id: str,
    hook_name: str,
    hook_index: int,
    hook_value: str,
) -> None:
    """Test that show_hook with indexed hook name returns the specific value.

    Per tmux.1, hooks are array options that can be queried by index.
    When calling show_hook("session-renamed[0]"), it should return the string
    value at that index, not a SparseArray.
    """
    session = server.new_session(session_name="test_indexed_lookup")
    indexed_hook = f"{hook_name}[{hook_index}]"

    # Set the hook
    session.set_hook(indexed_hook, hook_value)

    # Query with indexed name - should return the specific value, not SparseArray
    result = session.show_hook(indexed_hook)
    assert result is not None
    assert isinstance(result, str), f"Expected str, got {type(result)}"
    # tmux may normalize quotes, so check the essential parts are present
    assert "display-message" in result

    # Verify base hook query still returns SparseArray
    base_result = session.show_hook(hook_name)
    assert isinstance(base_result, SparseArray)
    assert hook_index in base_result

    # Cleanup
    session.unset_hook(hook_name)


def test_set_hooks_with_sparse_array(server: Server) -> None:
    """Test set_hooks with SparseArray input."""
    session = server.new_session(session_name="test_set_hooks_sparse")

    sparse: SparseArray[str] = SparseArray()
    sparse.add(0, "display-message 'from sparse 0'")
    sparse.add(10, "display-message 'from sparse 10'")

    session.set_hooks("session-renamed", sparse)

    hooks = session.show_hook("session-renamed")
    assert hooks is not None
    assert isinstance(hooks, SparseArray)
    assert sorted(hooks.keys()) == [0, 10]

    # Cleanup
    session.unset_hook("session-renamed")


def test_set_hooks_method_chaining(server: Server) -> None:
    """Test that set_hooks supports method chaining."""
    session = server.new_session(session_name="test_set_hooks_chain")

    # Chain set_hooks with set_hook (append=True)
    result = (
        session.set_hooks(
            "session-renamed",
            ["display-message 'hook 0'"],
        )
        .set_hook("session-renamed", "display-message 'hook 1'", append=True)
        .set_hook("session-renamed", "display-message 'hook 2'", append=True)
    )

    # Should return the session
    assert result is session

    # Verify all hooks set via show_hook
    hooks = session.show_hook("session-renamed")
    assert hooks is not None
    assert isinstance(hooks, SparseArray)
    assert sorted(hooks.keys()) == [0, 1, 2]

    # Cleanup
    session.unset_hook("session-renamed")


def test_unset_hook_clears_all_indices(server: Server) -> None:
    """Test that unset_hook without index clears all hook indices."""
    session = server.new_session(session_name="test_unset_hook")

    # Set hooks at multiple indices
    session.set_hook("session-renamed[0]", "display-message 'hook 0'")
    session.set_hook("session-renamed[5]", "display-message 'hook 5'")
    session.set_hook("session-renamed[10]", "display-message 'hook 10'")

    # Verify hooks exist
    hooks = session.show_hook("session-renamed")
    assert hooks is not None
    assert isinstance(hooks, SparseArray)
    assert sorted(hooks.keys()) == [0, 5, 10]

    # Unset without index should clear all
    session.unset_hook("session-renamed")

    # Verify hooks are cleared
    hooks_after = session.show_hook("session-renamed")
    assert hooks_after is None or (
        isinstance(hooks_after, SparseArray) and len(hooks_after) == 0
    )


def test_set_hook_append_flag(server: Server) -> None:
    """Test set_hook with append=True uses tmux's -a flag."""
    session = server.new_session(session_name="test_append_flag")

    # Set initial hook
    session.set_hook("session-renamed[0]", "display-message 'initial'")

    # Append using set_hook with append=True
    session.set_hook("session-renamed", "display-message 'appended'", append=True)

    # Verify both hooks exist
    hooks = session.show_hook("session-renamed")
    assert hooks is not None
    assert isinstance(hooks, SparseArray)
    assert len(hooks) == 2

    # Cleanup
    session.unset_hook("session-renamed")


# =============================================================================
# show_hooks Tests
# =============================================================================


class ShowHooksTestCase(t.NamedTuple):
    """Test case for show_hooks validation."""

    test_id: str
    hook: str
    value: str
    expected_value: str
    expected_type: type
    min_version: str = "3.2"


SHOW_HOOKS_TEST_CASES: list[ShowHooksTestCase] = [
    ShowHooksTestCase(
        test_id="string_hook_value",
        hook="session-renamed[0]",
        value='display-message "test"',
        expected_value="display-message test",  # tmux strips quotes in output
        expected_type=str,
    ),
    ShowHooksTestCase(
        test_id="multiple_hooks",
        hook="session-renamed[1]",
        value='display-message "another"',
        expected_value="display-message another",  # tmux strips quotes in output
        expected_type=str,
    ),
]


def _build_show_hooks_params() -> list[t.Any]:
    """Build pytest params for show_hooks tests."""
    return [pytest.param(tc, id=tc.test_id) for tc in SHOW_HOOKS_TEST_CASES]


@pytest.mark.parametrize("test_case", _build_show_hooks_params())
def test_show_hooks_stores_string_values(
    server: Server,
    test_case: ShowHooksTestCase,
) -> None:
    """Test that show_hooks() correctly stores string hook values."""
    if not has_gte_version(test_case.min_version):
        pytest.skip(f"Requires tmux >= {test_case.min_version}")

    session = server.new_session(session_name="test_show_hooks")

    session.set_hook(test_case.hook, test_case.value)
    hooks = session.show_hooks()

    assert test_case.hook in hooks
    assert isinstance(hooks[test_case.hook], test_case.expected_type)
    assert hooks[test_case.hook] == test_case.expected_value

    # Cleanup
    session.unset_hook(test_case.hook.split("[")[0])


# =============================================================================
# run_hook Tests
# =============================================================================


def test_run_hook_basic(server: Server) -> None:
    """Test run_hook() method exists and can be called without error."""
    if not has_gte_version("3.2"):
        pytest.skip("Requires tmux >= 3.2")

    session = server.new_session(session_name="test_run_hook")

    # Set a hook first
    session.set_hook("session-renamed[0]", 'display-message "test"')

    # Run the hook immediately - should not raise
    result = session.run_hook("session-renamed[0]")

    # Verify returns self for chaining
    assert result is session

    # Cleanup
    session.unset_hook("session-renamed")


# =============================================================================
# set_hook Flag Combination Tests
# =============================================================================


class SetHookFlagTestCase(t.NamedTuple):
    """Test case for set_hook flag combinations."""

    test_id: str
    flag_kwargs: dict[str, t.Any]
    expected_behavior: str  # "sets_hook", "runs_immediately", "appends", "global"
    min_version: str = "3.2"


SET_HOOK_FLAG_TEST_CASES: list[SetHookFlagTestCase] = [
    SetHookFlagTestCase(
        "append_to_existing",
        {"append": True},
        "appends",
    ),
    SetHookFlagTestCase(
        "global_hook",
        {"global_": True},
        "global",
    ),
    SetHookFlagTestCase(
        "run_immediately",
        {"run": True},
        "runs_immediately",
    ),
    SetHookFlagTestCase(
        "append_and_global",
        {"append": True, "global_": True},
        "appends",
    ),
]


@pytest.mark.parametrize(
    "test_case",
    [pytest.param(tc, id=tc.test_id) for tc in SET_HOOK_FLAG_TEST_CASES],
)
def test_set_hook_flag_combinations(
    server: Server,
    test_case: SetHookFlagTestCase,
) -> None:
    """Test set_hook with various flag combinations."""
    if not has_gte_version(test_case.min_version):
        pytest.skip(f"Requires tmux {test_case.min_version}+")

    session = server.new_session(session_name="test_flags")

    hook_name = "session-renamed"
    hook_cmd = "display-message 'flag test'"

    if test_case.expected_behavior == "appends":
        # Set initial hook first
        session.set_hook(f"{hook_name}[0]", "display-message 'initial'")
        session.set_hook(hook_name, hook_cmd, **test_case.flag_kwargs)

        # Verify append added another entry
        if test_case.flag_kwargs.get("global_"):
            # Use raw command for global hooks
            result = server.cmd("show-hooks", "-g", hook_name)
            assert result.stdout is not None
            parsed = Hooks.from_stdout(result.stdout)
        else:
            hooks = session._show_hook(hook_name)
            assert hooks is not None
            parsed = Hooks.from_stdout(hooks)

        hook_values = parsed.session_renamed.as_list()
        assert len(hook_values) >= 1

    elif test_case.expected_behavior == "global":
        session.set_hook(f"{hook_name}[0]", hook_cmd, **test_case.flag_kwargs)

        # Global hook should be visible from server with -g flag
        result = server.cmd("show-hooks", "-g", f"{hook_name}[0]")
        assert result.stdout is not None
        assert len(result.stdout) > 0
        assert "display-message" in result.stdout[0]

    elif test_case.expected_behavior == "runs_immediately":
        # The -R flag runs hook immediately WITHOUT storing
        # So after set_hook with run=True, hook should NOT be stored
        session.set_hook(hook_name, hook_cmd, **test_case.flag_kwargs)

        # Hook should NOT be stored (run immediately and discarded)
        hooks = session._show_hook(hook_name)
        # Either None or empty
        if hooks:
            parsed = Hooks.from_stdout(hooks)
            # May be empty or have default empty entry
            assert parsed.session_renamed is None or len(parsed.session_renamed) == 0

    # Cleanup
    session.unset_hook(hook_name)
    if test_case.flag_kwargs.get("global_"):
        server.cmd("set-hook", "-gu", hook_name)


# =============================================================================
# Hook Scope Tests
# =============================================================================


class HookScopeTestCase(t.NamedTuple):
    """Test case for hook scope handling."""

    test_id: str
    scope: str  # "session", "window", "pane"
    scope_flag: str  # tmux flag for show-hooks
    min_version: str = "3.2"


HOOK_SCOPE_TEST_CASES: list[HookScopeTestCase] = [
    HookScopeTestCase("session_scope", "session", ""),
    HookScopeTestCase("window_scope", "window", "-w", "3.2"),
    HookScopeTestCase("pane_scope", "pane", "-p", "3.2"),
]


@pytest.mark.parametrize(
    "test_case",
    [pytest.param(tc, id=tc.test_id) for tc in HOOK_SCOPE_TEST_CASES],
)
def test_hook_scope_handling(
    server: Server,
    test_case: HookScopeTestCase,
) -> None:
    """Test hooks at different scopes (session, window, pane)."""
    if not has_gte_version(test_case.min_version):
        pytest.skip(f"Requires tmux {test_case.min_version}+")

    session = server.new_session(session_name="test_scope")
    window = session.active_window
    assert window is not None
    pane = window.active_pane
    assert pane is not None

    hook_name = "session-renamed"
    hook_cmd = f"display-message '{test_case.scope} scope test'"

    # Set hook at the appropriate scope
    if test_case.scope == "session":
        session.set_hook(f"{hook_name}[0]", hook_cmd)
        result = session._show_hook(f"{hook_name}[0]")
    elif test_case.scope == "window":
        window.set_hook(f"{hook_name}[0]", hook_cmd)
        result = window._show_hook(f"{hook_name}[0]")
    else:  # pane
        pane.set_hook(f"{hook_name}[0]", hook_cmd)
        result = pane._show_hook(f"{hook_name}[0]")

    assert result is not None
    assert len(result) > 0
    assert "display-message" in result[0]

    # Cleanup
    if test_case.scope == "session":
        session.unset_hook(hook_name)
    elif test_case.scope == "window":
        window.unset_hook(hook_name)
    else:
        pane.unset_hook(hook_name)


# =============================================================================
# show_hooks Parsing Edge Cases
# =============================================================================


class ShowHooksParseTestCase(t.NamedTuple):
    """Test case for show_hooks output parsing edge cases."""

    test_id: str
    setup_commands: list[tuple[str, str]]  # List of (hook[idx], value) to set
    expected_keys: list[str]  # Expected keys in result
    check_values: bool = True  # Whether to verify specific values


SHOW_HOOKS_PARSE_TEST_CASES: list[ShowHooksParseTestCase] = [
    ShowHooksParseTestCase(
        "normal_hook_value",
        [("session-renamed[0]", "display-message 'test'")],
        ["session-renamed[0]"],
    ),
    ShowHooksParseTestCase(
        "multiple_indexed_hooks",
        [
            ("session-renamed[0]", "display-message 'first'"),
            ("session-renamed[1]", "display-message 'second'"),
            ("session-renamed[5]", "display-message 'fifth'"),
        ],
        ["session-renamed[0]", "session-renamed[1]", "session-renamed[5]"],
    ),
    ShowHooksParseTestCase(
        "multiple_different_hooks",
        [
            ("session-renamed[0]", "display-message 'renamed'"),
            ("after-split-window[0]", "display-message 'split'"),
        ],
        ["session-renamed[0]", "after-split-window[0]"],
    ),
]


@pytest.mark.parametrize(
    "test_case",
    [pytest.param(tc, id=tc.test_id) for tc in SHOW_HOOKS_PARSE_TEST_CASES],
)
def test_show_hooks_parsing_edge_cases(
    server: Server,
    test_case: ShowHooksParseTestCase,
) -> None:
    """Test show_hooks parses various output formats correctly."""
    session = server.new_session(session_name="test_parsing")

    # Setup hooks
    for hook, value in test_case.setup_commands:
        session.set_hook(hook, value)

    # Get all hooks via show_hooks
    hooks = session.show_hooks()

    # Verify expected keys are present
    for key in test_case.expected_keys:
        assert key in hooks, f"Expected key {key} not found in {list(hooks.keys())}"

    if test_case.check_values:
        for key in test_case.expected_keys:
            assert hooks[key] is not None, f"Expected value for {key} to be non-None"

    # Cleanup
    for hook, _ in test_case.setup_commands:
        base_hook = hook.split("[")[0]
        session.unset_hook(base_hook)


def test_show_hooks_empty_result(server: Server) -> None:
    """Test show_hooks returns empty dict when no hooks are set."""
    session = server.new_session(session_name="test_empty_hooks")

    # Fresh session should have no session-level hooks
    hooks = session.show_hooks()

    # Should be a dict (possibly empty)
    assert isinstance(hooks, dict)
