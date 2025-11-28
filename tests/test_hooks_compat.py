"""Tests for hook version compatibility.

This module tests hook behavior differences between tmux < 3.0 and tmux 3.0+.

tmux Hook Architecture Changes (3.0)
------------------------------------
Prior to tmux 3.0, hooks were stored in a red-black tree by exact name.
Setting "session-renamed[0]" created a hook with that literal name (including
brackets). The ``set-hook -u session-renamed`` command only removed a hook
named exactly "session-renamed", NOT "session-renamed[0]".

In tmux 3.0 (commit dfb7bb68, April 2019), hooks were merged into the options
tree as array options. Now "session-renamed[0]" is index 0 of the
"session-renamed" array, and ``set-hook -u session-renamed`` clears all
indices of that array.

This difference means that:
- On tmux < 3.0: ``set_hooks()`` creates hooks with literal bracket names
- On tmux < 3.0: ``unset_hook('session-renamed')`` does NOT clear indexed hooks
- On tmux 3.0+: ``set_hooks()`` properly creates array entries
- On tmux 3.0+: ``unset_hook('session-renamed')`` clears all array indices

References
----------
- tmux commit: dfb7bb68 (April 26, 2019)
- tmux CHANGES 3.0: "Hooks are now stored in the options tree as array options"
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux._internal.sparse_array import SparseArray
from libtmux.common import has_gte_version, has_lt_version

if t.TYPE_CHECKING:
    from libtmux.server import Server


class TestSetHooksVersionWarning:
    """Test set_hooks warning on tmux < 3.0."""

    @pytest.mark.skipif(
        has_gte_version("3.0"),
        reason="Warning only emitted on tmux < 3.0",
    )
    def test_set_hooks_warns_on_old_tmux(self, server: Server) -> None:
        """Verify set_hooks emits warning on tmux < 3.0.

        On tmux < 3.0, hook arrays don't exist. The bracket syntax creates
        hooks with literal names like "session-renamed[0]" instead of array
        indices. This test verifies the warning is raised to alert users.
        """
        session = server.new_session(session_name="test_warn")

        with pytest.warns(
            UserWarning,
            match=r"Hook arrays require tmux 3\.0\+",
        ):
            session.set_hooks("session-renamed", {0: "display-message 'test'"})

    @pytest.mark.skipif(
        has_lt_version("3.0"),
        reason="Test requires tmux 3.0+ for proper array hook support",
    )
    def test_set_hooks_no_warning_on_new_tmux(
        self,
        server: Server,
        recwarn: pytest.WarningsRecorder,
    ) -> None:
        """Verify set_hooks does NOT warn on tmux 3.0+.

        On tmux 3.0+, hooks are proper array options. No warning should be
        emitted when using set_hooks.
        """
        session = server.new_session(session_name="test_no_warn")

        # Call set_hooks - should not emit any warnings on 3.0+
        session.set_hooks("session-renamed", {0: "display-message 'test'"})

        # Filter for our specific warning (ignore other warnings)
        hook_warnings = [
            w for w in recwarn if "Hook arrays require tmux" in str(w.message)
        ]
        assert len(hook_warnings) == 0, "Should not warn on tmux 3.0+"

        # Cleanup
        session.unset_hook("session-renamed")


class TestSetHooksArrayBehavior:
    """Test set_hooks array behavior on tmux 3.0+."""

    @pytest.mark.skipif(
        has_lt_version("3.0"),
        reason="Hook arrays require tmux 3.0+",
    )
    def test_set_hooks_creates_array_indices(self, server: Server) -> None:
        """Verify set_hooks creates proper array indices on tmux 3.0+.

        On tmux 3.0+, set_hooks should create hooks as array indices that can
        be queried with show_hook and cleared with unset_hook.
        """
        session = server.new_session(session_name="test_array")

        # Suppress warning in case test runs on < 3.0 (though it's skipped)
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            session.set_hooks(
                "session-renamed",
                {
                    0: 'display-message "hook 0"',
                    1: 'display-message "hook 1"',
                },
            )

        # Verify hooks were created as array
        hooks = session.show_hook("session-renamed")
        assert hooks is not None
        assert isinstance(hooks, SparseArray)
        assert sorted(hooks.keys()) == [0, 1]

        # Cleanup
        session.unset_hook("session-renamed")

    @pytest.mark.skipif(
        has_lt_version("3.0"),
        reason="Hook arrays require tmux 3.0+",
    )
    def test_set_hooks_clear_existing(self, server: Server) -> None:
        """Verify clear_existing=True clears all indices on tmux 3.0+.

        On tmux 3.0+, unset_hook('hook-name') clears all array indices.
        The clear_existing parameter uses this to replace all existing hooks.
        """
        session = server.new_session(session_name="test_clear")

        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # Set initial hooks
            session.set_hooks(
                "session-renamed",
                {0: 'display-message "old 0"', 1: 'display-message "old 1"'},
            )

            # Verify initial hooks
            hooks = session.show_hook("session-renamed")
            assert hooks is not None
            assert isinstance(hooks, SparseArray)
            assert sorted(hooks.keys()) == [0, 1]

            # Replace with new hooks using clear_existing
            session.set_hooks(
                "session-renamed",
                {0: 'display-message "new"'},
                clear_existing=True,
            )

        # Verify only new hook exists
        hooks_after = session.show_hook("session-renamed")
        assert hooks_after is not None
        assert isinstance(hooks_after, SparseArray)
        assert sorted(hooks_after.keys()) == [0]

        # Cleanup
        session.unset_hook("session-renamed")

    @pytest.mark.skipif(
        has_lt_version("3.0"),
        reason="Hook arrays require tmux 3.0+",
    )
    def test_set_hooks_from_list(self, server: Server) -> None:
        """Verify set_hooks accepts list input on tmux 3.0+.

        Lists are converted to dicts with sequential indices starting at 0.
        """
        session = server.new_session(session_name="test_list")

        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            session.set_hooks(
                "after-new-window",
                [
                    "select-pane -t 0",
                    'send-keys "clear" Enter',
                ],
            )

        hooks = session.show_hook("after-new-window")
        assert hooks is not None
        assert isinstance(hooks, SparseArray)
        assert sorted(hooks.keys()) == [0, 1]

        # Cleanup
        session.unset_hook("after-new-window")
