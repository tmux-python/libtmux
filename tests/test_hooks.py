"""Testsuite for libtmux hook management."""

from __future__ import annotations

import typing as t

import pytest

from libtmux._internal.constants import Hooks
from libtmux._internal.sparse_array import SparseArray
from libtmux.common import has_gte_version, has_lt_version

if t.TYPE_CHECKING:
    from libtmux.server import Server

if has_lt_version("3.0"):
    pytest.skip(
        reason="only support hooks in tmux 3.0 and above",
        allow_module_level=True,
    )


def test_hooks_raw_cmd(
    server: Server,
) -> None:
    """Raw hook set, show, unset via cmd."""
    session = server.new_session(session_name="test hooks")
    window = session.attached_window
    pane = window.attached_pane
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
    window = session.attached_window
    pane = window.attached_pane
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
    window = session.attached_window
    pane = window.attached_pane
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
        xfail_reason="pane-title-changed requires tmux 3.5+",
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
# Bulk Operations API Tests
# =============================================================================


class BulkOpTestCase(t.NamedTuple):
    """Test case for bulk hook operations."""

    test_id: str
    operation: str  # "get_indices", "get_values", "set_bulk", "clear", "append"
    hook: str  # Hook name to test
    setup_hooks: dict[int, str]  # Initial hooks to set (index -> value)
    operation_args: dict[str, t.Any]  # Args for operation
    expected_indices: list[int]  # Expected indices after operation
    expected_contains: list[str] | None = None  # Strings expected in values


# --- get_hook_indices tests ---
GET_INDICES_TESTS: list[BulkOpTestCase] = [
    BulkOpTestCase(
        "get_indices_empty",
        "get_indices",
        "session-renamed",
        {},
        {},
        [],
    ),
    BulkOpTestCase(
        "get_indices_sequential",
        "get_indices",
        "session-renamed",
        {
            0: "display-message 'hook 0'",
            1: "display-message 'hook 1'",
            2: "display-message 'hook 2'",
        },
        {},
        [0, 1, 2],
    ),
    BulkOpTestCase(
        "get_indices_sparse",
        "get_indices",
        "session-renamed",
        {
            0: "display-message 'hook 0'",
            5: "display-message 'hook 5'",
            10: "display-message 'hook 10'",
        },
        {},
        [0, 5, 10],
    ),
]

# --- get_hook_values tests ---
GET_VALUES_TESTS: list[BulkOpTestCase] = [
    BulkOpTestCase(
        "get_values_empty",
        "get_values",
        "session-renamed",
        {},
        {},
        [],
    ),
    BulkOpTestCase(
        "get_values_sparse",
        "get_values",
        "session-renamed",
        {0: "display-message 'hook 0'", 5: "display-message 'hook 5'"},
        {},
        [0, 5],
        ["display-message"],
    ),
]

# --- set_hooks_bulk tests ---
SET_BULK_TESTS: list[BulkOpTestCase] = [
    BulkOpTestCase(
        "set_bulk_with_dict",
        "set_bulk",
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
    BulkOpTestCase(
        "set_bulk_with_list",
        "set_bulk",
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
    BulkOpTestCase(
        "set_bulk_clear_existing",
        "set_bulk",
        "session-renamed",
        {0: "display-message 'old 0'", 1: "display-message 'old 1'"},
        {"values": {0: "display-message 'new 0'"}, "clear_existing": True},
        [0],
        ["new 0"],
    ),
]

# --- clear_hook tests ---
CLEAR_TESTS: list[BulkOpTestCase] = [
    BulkOpTestCase(
        "clear_hook",
        "clear",
        "session-renamed",
        {0: "display-message 'hook 0'", 5: "display-message 'hook 5'"},
        {},
        [],
    ),
]

# --- append_hook tests ---
APPEND_TESTS: list[BulkOpTestCase] = [
    BulkOpTestCase(
        "append_to_empty",
        "append",
        "session-renamed",
        {},
        {"value": "display-message 'appended'"},
        [0],
        ["appended"],
    ),
    BulkOpTestCase(
        "append_sequential",
        "append",
        "session-renamed",
        {0: "display-message 'initial'"},
        {"value": "display-message 'appended'"},
        [0, 1],
    ),
    BulkOpTestCase(
        "append_after_sparse",
        "append",
        "session-renamed",
        {0: "display-message 'at 0'", 10: "display-message 'at 10'"},
        {"value": "display-message 'appended'"},
        [0, 10, 11],
        ["appended"],
    ),
]

# Combine all bulk operation test cases
ALL_BULK_OP_TESTS: list[BulkOpTestCase] = (
    GET_INDICES_TESTS + GET_VALUES_TESTS + SET_BULK_TESTS + CLEAR_TESTS + APPEND_TESTS
)


def _build_bulk_op_params() -> list[t.Any]:
    """Build pytest params for bulk operation tests."""
    return [pytest.param(tc, id=tc.test_id) for tc in ALL_BULK_OP_TESTS]


@pytest.mark.parametrize("test_case", _build_bulk_op_params())
def test_bulk_hook_operation(server: Server, test_case: BulkOpTestCase) -> None:
    """Test bulk hook operations.

    This parametrized test ensures all bulk operations work correctly:
    - get_hook_indices: returns sorted list of existing indices
    - get_hook_values: returns SparseArray with values
    - set_hooks_bulk: sets multiple hooks at once
    - clear_hook: removes all indexed values
    - append_hook: appends at next available index
    """
    session = server.new_session(session_name="test_bulk_ops")

    # Setup initial hooks
    for idx, val in test_case.setup_hooks.items():
        session.set_hook(f"{test_case.hook}[{idx}]", val)

    # Perform operation based on type
    if test_case.operation == "get_indices":
        result = session.get_hook_indices(test_case.hook)
        assert result == test_case.expected_indices

    elif test_case.operation == "get_values":
        values = session.get_hook_values(test_case.hook)
        assert isinstance(values, SparseArray)
        assert sorted(values.keys()) == test_case.expected_indices
        if test_case.expected_contains:
            for expected_str in test_case.expected_contains:
                assert any(expected_str in v for v in values.values())

    elif test_case.operation == "set_bulk":
        session.set_hooks_bulk(test_case.hook, **test_case.operation_args)
        indices = session.get_hook_indices(test_case.hook)
        assert indices == test_case.expected_indices
        if test_case.expected_contains:
            values = session.get_hook_values(test_case.hook)
            for expected_str in test_case.expected_contains:
                assert any(expected_str in v for v in values.values())

    elif test_case.operation == "clear":
        session.clear_hook(test_case.hook)
        indices = session.get_hook_indices(test_case.hook)
        assert indices == test_case.expected_indices

    elif test_case.operation == "append":
        session.append_hook(test_case.hook, test_case.operation_args["value"])
        indices = session.get_hook_indices(test_case.hook)
        assert indices == test_case.expected_indices
        if test_case.expected_contains:
            values = session.get_hook_values(test_case.hook)
            for expected_str in test_case.expected_contains:
                assert any(expected_str in v for v in values.values())

    # Cleanup
    session.clear_hook(test_case.hook)


def test_bulk_hook_values_iteration(server: Server) -> None:
    """Test iterating over hook values in sorted order."""
    session = server.new_session(session_name="test_bulk_ops")

    # Set hooks at sparse indices (out of order)
    session.set_hook("session-renamed[5]", "display-message 'fifth'")
    session.set_hook("session-renamed[0]", "display-message 'zeroth'")
    session.set_hook("session-renamed[2]", "display-message 'second'")

    values = session.get_hook_values("session-renamed")
    value_list = list(values.iter_values())

    # Values should be in sorted index order
    assert len(value_list) == 3
    assert "zeroth" in value_list[0]
    assert "second" in value_list[1]
    assert "fifth" in value_list[2]

    # Cleanup
    session.clear_hook("session-renamed")


def test_bulk_hook_set_with_sparse_array(server: Server) -> None:
    """Test set_hooks_bulk with SparseArray input."""
    session = server.new_session(session_name="test_bulk_ops")

    sparse: SparseArray[str] = SparseArray()
    sparse.add(0, "display-message 'from sparse 0'")
    sparse.add(10, "display-message 'from sparse 10'")

    session.set_hooks_bulk("session-renamed", sparse)

    indices = session.get_hook_indices("session-renamed")
    assert indices == [0, 10]

    # Cleanup
    session.clear_hook("session-renamed")


def test_bulk_hook_method_chaining(server: Server) -> None:
    """Test that bulk operations support method chaining."""
    session = server.new_session(session_name="test_bulk_ops")

    # Chain operations
    result = (
        session.set_hooks_bulk(
            "session-renamed",
            ["display-message 'hook 0'"],
        )
        .append_hook("session-renamed", "display-message 'hook 1'")
        .append_hook("session-renamed", "display-message 'hook 2'")
    )

    # Should return the session
    assert result is session

    # Verify all hooks set
    indices = session.get_hook_indices("session-renamed")
    assert indices == [0, 1, 2]

    # Cleanup
    session.clear_hook("session-renamed")
