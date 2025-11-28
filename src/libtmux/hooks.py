"""Helpers for tmux hooks.

tmux Hook Version Compatibility
-------------------------------
Hook array support requires tmux 3.0+.

**tmux 3.0+**:
- Hooks are array options (e.g., ``session-renamed[0]``, ``session-renamed[1]``)
- Sparse indices supported (can have gaps: ``[0]``, ``[5]``, ``[10]``)
- Session-level hooks available

**tmux 3.2+**:
- Window-level hooks via ``-w`` flag
- Pane-level hooks via ``-p`` flag
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
import shlex
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
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
    ) -> Self:
        """Run a hook immediately. Useful for testing."""
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_hook_scope

        flags: list[str] = ["-R"]

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
        _format: bool | None = None,
        unset: bool | None = None,
        run: bool | None = None,
        prevent_overwrite: bool | None = None,
        ignore_errors: bool | None = None,
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
        value : str
            hook command.

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`
        """
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_hook_scope

        flags: list[str] = []

        if unset is not None and unset:
            assert isinstance(unset, bool)
            flags.append("-u")

        if run is not None and run:
            assert isinstance(run, bool)
            flags.append("-R")

        if _format is not None and _format:
            assert isinstance(_format, bool)
            flags.append("-F")

        if prevent_overwrite is not None and prevent_overwrite:
            assert isinstance(prevent_overwrite, bool)
            flags.append("-o")

        if ignore_errors is not None and ignore_errors:
            assert isinstance(ignore_errors, bool)
            flags.append("-q")

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
        ignore_errors: bool | None = None,
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

        if ignore_errors is not None and ignore_errors:
            assert isinstance(ignore_errors, bool)
            flags.append("-q")

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
        ignore_errors: bool | None = None,
    ) -> HookDict:
        """Return a dict of hooks for the target."""
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

        if ignore_errors is not None and ignore_errors:
            assert isinstance(ignore_errors, bool)
            flags += ("-q",)

        cmd = self.cmd("show-hooks", *flags)
        output = cmd.stdout
        hooks: HookDict = {}
        for item in output:
            try:
                key, val = shlex.split(item)
            except ValueError:
                logger.warning(f"Error extracting hook: {item}")
                key, val = item, None
            assert isinstance(key, str)
            assert isinstance(val, str) or val is None

            if isinstance(val, str) and val.isdigit():
                hooks[key] = int(val)

        return hooks

    def _show_hook(
        self,
        hook: str,
        global_: bool = False,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
        ignore_errors: bool | None = None,
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

        if ignore_errors is not None and ignore_errors:
            flags += ("-q",)

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
        ignore_errors: bool | None = None,
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
            scope=scope,
            ignore_errors=ignore_errors,
        )
        if hooks_output is None:
            return None
        hooks = Hooks.from_stdout(hooks_output)
        return getattr(hooks, hook.replace("-", "_"), None)

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

        >>> session.set_hooks('session-renamed', {  # doctest: +SKIP
        ...     0: 'display-message "hook 0"',
        ...     1: 'display-message "hook 1"',
        ... })
        Session($...)

        >>> hooks = session.show_hook('session-renamed')  # doctest: +SKIP
        >>> sorted(hooks.keys())  # doctest: +SKIP
        [0, 1]

        >>> session.unset_hook('session-renamed')  # doctest: +SKIP
        Session($...)

        Set hooks from a list (sequential indices):

        >>> session.set_hooks('after-new-window', [  # doctest: +SKIP
        ...     'select-pane -t 0',
        ...     'send-keys "clear" Enter',
        ... ])
        Session($...)

        >>> hooks = session.show_hook('after-new-window')  # doctest: +SKIP
        >>> sorted(hooks.keys())  # doctest: +SKIP
        [0, 1]

        Replace all existing hooks with ``clear_existing=True``:

        >>> session.set_hooks(  # doctest: +SKIP
        ...     'session-renamed',
        ...     {0: 'display-message "new"'},
        ...     clear_existing=True,
        ... )
        Session($...)

        >>> hooks = session.show_hook('session-renamed')  # doctest: +SKIP
        >>> sorted(hooks.keys())  # doctest: +SKIP
        [0]

        >>> session.unset_hook('session-renamed')  # doctest: +SKIP
        Session($...)

        >>> session.unset_hook('after-new-window')  # doctest: +SKIP
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
