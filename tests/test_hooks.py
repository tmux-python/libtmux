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
