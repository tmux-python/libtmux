"""Helpers for tmux hooks.

tmux Hook Features
------------------
Hooks are array options (e.g., ``session-renamed[0]``, ``session-renamed[1]``)
with sparse index support (can have gaps: ``[0]``, ``[5]``, ``[10]``).

All features available in libtmux's minimum supported version (tmux 3.2+):

- Session, window, and pane-level hooks
- Window hooks via ``-w`` flag, pane hooks via ``-p`` flag
- Hook scope separation (session vs window vs pane)

**tmux 3.3+**:
- ``client-active`` hook
- ``window-resized`` hook

**tmux 3.5+**:
- ``pane-title-changed`` hook
- ``client-light-theme`` / ``client-dark-theme`` hooks
- ``command-error`` hook

Bulk Operations API
-------------------
This module provides bulk operations for managing multiple indexed hooks:

- :meth:`~HooksMixin.set_hooks` - Set multiple hooks at once
"""

from __future__ import annotations

import logging
import re
import typing as t
import warnings

from libtmux._internal.constants import (
    Hooks,
)
from libtmux._internal.sparse_array import SparseArray
from libtmux.common import CmdMixin, has_lt_version
from libtmux.constants import (
    DEFAULT_OPTION_SCOPE,
    HOOK_SCOPE_FLAG_MAP,
    OptionScope,
    _DefaultOptionScope,
)
from libtmux.options import handle_option_error

if t.TYPE_CHECKING:
    from typing_extensions import Self

HookDict = dict[str, t.Any]
HookValues = dict[int, str] | SparseArray[str] | list[str]

logger = logging.getLogger(__name__)


class HooksMixin(CmdMixin):
    """Mixin for manager scoped hooks in tmux.

    Requires tmux 3.1+. For older versions, use raw commands.
    """

    default_hook_scope: OptionScope | None
    hooks: Hooks

    def __init__(self, default_hook_scope: OptionScope | None) -> None:
        """When not a user (custom) hook, scope can be implied."""
        self.default_hook_scope = default_hook_scope
        self.hooks = Hooks()

    def run_hook(
        self,
        hook: str,
        global_: bool | None = None,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
    ) -> Self:
        """Run a hook immediately. Useful for testing."""
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_hook_scope

        flags: list[str] = ["-R"]

        if global_ is not None and global_:
            flags.append("-g")

        if scope is not None and not isinstance(scope, _DefaultOptionScope):
            assert scope in HOOK_SCOPE_FLAG_MAP

            flag = HOOK_SCOPE_FLAG_MAP[scope]
            if flag in {"-p", "-w"} and has_lt_version("3.2"):
                warnings.warn(
                    "Scope flag '-w' and '-p' requires tmux 3.2+. Ignoring.",
                    stacklevel=2,
                )
            else:
                flags += (flag,)

        cmd = self.cmd(
            "set-hook",
            *flags,
            hook,
        )

        if isinstance(cmd.stderr, list) and len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        return self

    def set_hook(
        self,
        hook: str,
        value: int | str,
        unset: bool | None = None,
        run: bool | None = None,
        append: bool | None = None,
        g: bool | None = None,
        global_: bool | None = None,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
    ) -> Self:
        """Set hook for tmux target.

        Wraps ``$ tmux set-hook <hook> <value>``.

        Parameters
        ----------
        hook : str
            hook to set, e.g. 'aggressive-resize'
        value : int | str
            hook command.

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`
        """
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_hook_scope

        if g:
            warnings.warn(
                "g argument is deprecated in favor of global_",
                category=DeprecationWarning,
                stacklevel=2,
            )
            global_ = g

        flags: list[str] = []

        if unset is not None and unset:
            assert isinstance(unset, bool)
            flags.append("-u")

        if run is not None and run:
            assert isinstance(run, bool)
            flags.append("-R")

        if append is not None and append:
            assert isinstance(append, bool)
            flags.append("-a")

        if global_ is not None and global_:
            assert isinstance(global_, bool)
            flags.append("-g")

        if scope is not None and not isinstance(scope, _DefaultOptionScope):
            assert scope in HOOK_SCOPE_FLAG_MAP

            flag = HOOK_SCOPE_FLAG_MAP[scope]
            if flag in {"-p", "-w"} and has_lt_version("3.2"):
                warnings.warn(
                    "Scope flag '-w' and '-p' requires tmux 3.2+. Ignoring.",
                    stacklevel=2,
                )
            else:
                flags += (flag,)

        cmd = self.cmd(
            "set-hook",
            *flags,
            hook,
            value,
        )

        if isinstance(cmd.stderr, list) and len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        return self

    def unset_hook(
        self,
        hook: str,
        global_: bool | None = None,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
    ) -> Self:
        """Unset hook for tmux target.

        Wraps ``$ tmux set-hook -u <hook>`` / ``$ tmux set-hook -U <hook>``

        Parameters
        ----------
        hook : str
            hook to unset, e.g. 'after-show-environment'

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`
        """
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_hook_scope

        flags: list[str] = ["-u"]

        if global_ is not None and global_:
            assert isinstance(global_, bool)
            flags.append("-g")

        if scope is not None and not isinstance(scope, _DefaultOptionScope):
            assert scope in HOOK_SCOPE_FLAG_MAP

            flag = HOOK_SCOPE_FLAG_MAP[scope]
            if flag in {"-p", "-w"} and has_lt_version("3.2"):
                warnings.warn(
                    "Scope flag '-w' and '-p' requires tmux 3.2+. Ignoring.",
                    stacklevel=2,
                )
            else:
                flags += (flag,)

        cmd = self.cmd(
            "set-hook",
            *flags,
            hook,
        )

        if isinstance(cmd.stderr, list) and len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        return self

    def show_hooks(
        self,
        global_: bool | None = False,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
    ) -> HookDict:
        """Return a dict of hooks for the target.

        Parameters
        ----------
        global_ : bool, optional
            Pass ``-g`` flag for global hooks, default False.
        scope : OptionScope | _DefaultOptionScope | None, optional
            Hook scope (Server/Session/Window/Pane), defaults to object's scope.

        Returns
        -------
        HookDict
            Dictionary mapping hook names to their values.

        Examples
        --------
        >>> session.set_hook('session-renamed[0]', 'display-message "test"')
        Session($...)

        >>> hooks = session.show_hooks()
        >>> isinstance(hooks, dict)
        True

        >>> 'session-renamed[0]' in hooks
        True

        >>> session.unset_hook('session-renamed')
        Session($...)
        """
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_hook_scope

        flags: tuple[str, ...] = ()

        if global_:
            flags += ("-g",)

        if scope is not None and not isinstance(scope, _DefaultOptionScope):
            assert scope in HOOK_SCOPE_FLAG_MAP

            flag = HOOK_SCOPE_FLAG_MAP[scope]
            if flag in {"-p", "-w"} and has_lt_version("3.2"):
                warnings.warn(
                    "Scope flag '-w' and '-p' requires tmux 3.2+. Ignoring.",
                    stacklevel=2,
                )
            else:
                flags += (flag,)

        cmd = self.cmd("show-hooks", *flags)
        output = cmd.stdout
        hooks: HookDict = {}
        for item in output:
            # Split on first whitespace only to handle multi-word hook values
            parts = item.split(None, 1)
            if len(parts) == 2:
                key, val = parts
            elif len(parts) == 1:
                key, val = parts[0], None
            else:
                logger.warning(f"Error extracting hook: {item}")
                continue

            if isinstance(val, str) and val.isdigit():
                hooks[key] = int(val)
            elif isinstance(val, str):
                hooks[key] = val

        return hooks

    def _show_hook(
        self,
        hook: str,
        global_: bool = False,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
    ) -> list[str] | None:
        """Return value for the hook.

        Parameters
        ----------
        hook : str

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`
        """
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_hook_scope

        flags: tuple[str | int, ...] = ()

        if global_:
            flags += ("-g",)

        if scope is not None and not isinstance(scope, _DefaultOptionScope):
            assert scope in HOOK_SCOPE_FLAG_MAP

            flag = HOOK_SCOPE_FLAG_MAP[scope]
            if flag in {"-p", "-w"} and has_lt_version("3.2"):
                warnings.warn(
                    "Scope flag '-w' and '-p' requires tmux 3.2+. Ignoring.",
                    stacklevel=2,
                )
            else:
                flags += (flag,)

        flags += (hook,)

        cmd = self.cmd("show-hooks", *flags)

        if len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        return cmd.stdout

    def show_hook(
        self,
        hook: str,
        global_: bool = False,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
    ) -> str | int | SparseArray[str] | None:
        """Return value for a hook.

        For array hooks (e.g., ``session-renamed``), returns a
        :class:`~libtmux._internal.sparse_array.SparseArray` with hook values
        at their original indices. Use ``.keys()`` for indices and ``.values()``
        for values.

        Parameters
        ----------
        hook : str
            Hook name to query

        Returns
        -------
        str | int | SparseArray[str] | None
            Hook value. For array hooks, returns SparseArray.

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`

        Examples
        --------
        >>> session.set_hook('session-renamed[0]', 'display-message "test"')
        Session($...)

        >>> hooks = session.show_hook('session-renamed')
        >>> isinstance(hooks, SparseArray)
        True

        >>> sorted(hooks.keys())
        [0]

        >>> session.unset_hook('session-renamed')
        Session($...)
        """
        hooks_output = self._show_hook(
            hook=hook,
            global_=global_,
            scope=scope,
        )
        if hooks_output is None:
            return None
        hooks = Hooks.from_stdout(hooks_output)

        # Check if this is an indexed query (e.g., "session-renamed[0]")
        # For indexed queries, return the specific value like _show_option does
        hook_attr = hook.lstrip("%").replace("-", "_")
        index_match = re.search(r"\[(\d+)\]$", hook_attr)
        if index_match:
            # Strip the index for attribute lookup
            base_hook_attr = re.sub(r"\[\d+\]$", "", hook_attr)
            hook_val = getattr(hooks, base_hook_attr, None)
            if isinstance(hook_val, SparseArray):
                return hook_val.get(int(index_match.group(1)))
            return hook_val

        return getattr(hooks, hook_attr, None)

    def set_hooks(
        self,
        hook: str,
        values: HookValues,
        *,
        clear_existing: bool = False,
        global_: bool | None = None,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
    ) -> Self:
        """Set multiple indexed hooks at once.

        Parameters
        ----------
        hook : str
            Hook name, e.g. 'session-renamed'
        values : HookValues
            Values to set. Can be:
            - dict[int, str]: {0: 'cmd1', 1: 'cmd2'} - explicit indices
            - SparseArray[str]: preserves indices from another hook
            - list[str]: ['cmd1', 'cmd2'] - sequential indices starting at 0
        clear_existing : bool
            If True, unset all existing hook values first
        global_ : bool | None
            Use global hooks
        scope : OptionScope | None
            Scope for the hook

        Returns
        -------
        Self
            Returns self for method chaining.

        Examples
        --------
        Set hooks with explicit indices:

        >>> session.set_hooks('session-renamed', {
        ...     0: 'display-message "hook 0"',
        ...     1: 'display-message "hook 1"',
        ... })
        Session($...)

        >>> hooks = session.show_hook('session-renamed')
        >>> sorted(hooks.keys())
        [0, 1]

        >>> session.unset_hook('session-renamed')
        Session($...)

        Set hooks from a list (sequential indices):

        >>> session.set_hooks('after-new-window', [
        ...     'select-pane -t 0',
        ...     'send-keys "clear" Enter',
        ... ])
        Session($...)

        >>> hooks = session.show_hook('after-new-window')
        >>> sorted(hooks.keys())
        [0, 1]

        Replace all existing hooks with ``clear_existing=True``:

        >>> session.set_hooks(
        ...     'session-renamed',
        ...     {0: 'display-message "new"'},
        ...     clear_existing=True,
        ... )
        Session($...)

        >>> hooks = session.show_hook('session-renamed')
        >>> sorted(hooks.keys())
        [0]

        >>> session.unset_hook('session-renamed')
        Session($...)

        >>> session.unset_hook('after-new-window')
        Session($...)
        """
        if clear_existing:
            self.unset_hook(hook, global_=global_, scope=scope)

        # Convert list to dict with sequential indices
        if isinstance(values, list):
            values = dict(enumerate(values))

        for index, value in values.items():
            self.set_hook(
                f"{hook}[{index}]",
                value,
                global_=global_,
                scope=scope,
            )

        return self
