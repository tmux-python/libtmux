"""Helpers for tmux hooks."""

import logging
import shlex
import typing as t
import warnings

from libtmux._internal.constants import (
    Hooks,
)
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

HookDict = t.Dict[str, t.Any]

logger = logging.getLogger(__name__)


class HookMixin(CmdMixin):
    """Mixin for manager scoped hooks in tmux.

    Require tmux 3.1+. For older versions, use raw commands.
    """

    default_hook_scope: t.Optional[OptionScope]
    hooks: Hooks

    def __init__(self, default_hook_scope: t.Optional[OptionScope]) -> None:
        """When not a user (custom) hook, scope can be implied."""
        self.default_hook_scope = default_hook_scope
        self.hooks = Hooks()

    def run_hook(
        self,
        hook: str,
        scope: t.Optional[
            t.Union[OptionScope, _DefaultOptionScope]
        ] = DEFAULT_OPTION_SCOPE,
    ) -> "Self":
        """Run a hook immediately. Useful for testing."""
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_hook_scope

        flags: t.List[str] = ["-R"]

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
        value: t.Union[int, str],
        _format: t.Optional[bool] = None,
        unset: t.Optional[bool] = None,
        run: t.Optional[bool] = None,
        prevent_overwrite: t.Optional[bool] = None,
        ignore_errors: t.Optional[bool] = None,
        append: t.Optional[bool] = None,
        g: t.Optional[bool] = None,
        _global: t.Optional[bool] = None,
        scope: t.Optional[
            t.Union[OptionScope, _DefaultOptionScope]
        ] = DEFAULT_OPTION_SCOPE,
    ) -> "Self":
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

        flags: t.List[str] = []

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

        if _global is not None and _global:
            assert isinstance(_global, bool)
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
        _global: t.Optional[bool] = None,
        ignore_errors: t.Optional[bool] = None,
        scope: t.Optional[
            t.Union[OptionScope, _DefaultOptionScope]
        ] = DEFAULT_OPTION_SCOPE,
    ) -> "Self":
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

        flags: t.List[str] = ["-u"]

        if ignore_errors is not None and ignore_errors:
            assert isinstance(ignore_errors, bool)
            flags.append("-q")

        if _global is not None and _global:
            assert isinstance(_global, bool)
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
        _global: t.Optional[bool] = False,
        scope: t.Optional[
            t.Union[OptionScope, _DefaultOptionScope]
        ] = DEFAULT_OPTION_SCOPE,
        ignore_errors: t.Optional[bool] = None,
    ) -> "HookDict":
        """Return a dict of hooks for the target."""
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_hook_scope

        flags: t.Tuple[str, ...] = ()

        if _global:
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
        hooks: "HookDict" = {}
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
        _global: bool = False,
        scope: t.Optional[
            t.Union[OptionScope, _DefaultOptionScope]
        ] = DEFAULT_OPTION_SCOPE,
        ignore_errors: t.Optional[bool] = None,
    ) -> t.Optional[t.List[str]]:
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

        flags: t.Tuple[t.Union[str, int], ...] = ()

        if _global:
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
        _global: bool = False,
        scope: t.Optional[
            t.Union[OptionScope, _DefaultOptionScope]
        ] = DEFAULT_OPTION_SCOPE,
        ignore_errors: t.Optional[bool] = None,
    ) -> t.Optional[t.Union[str, int]]:
        """Return value for the hook.

        Parameters
        ----------
        hook : str

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`
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
