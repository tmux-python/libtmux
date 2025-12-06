# ruff: NOQA: E501
"""Helpers for tmux options.

Option parsing function trade testability and clarity for performance.

Tmux options
------------

Options in tmux consist of empty values, strings, integers, arrays, and complex shapes.

Marshalling types from text:

Integers: ``buffer-limit 50`` to ``{'buffer-limit': 50}``
Booleans: ``exit-unattached on`` to ``{'exit-unattached': True}``

Exploding arrays:

``command-alias[1] split-pane=split-window`` to
``{'command-alias[1]': {'split-pane=split-window'}}``

However, there is no equivalent to the above type of object in Python (a sparse array),
so a SparseArray is used.

Exploding complex shapes:

``"choose-session=choose-tree -s"`` to ``{'choose-session': 'choose-tree -s'}``

Finally, we need to convert hyphenated keys to underscored attribute names and assign
values, as python does not allow hyphens in attribute names.

``command-alias`` is ``command_alias`` in python.

Options object
--------------
Dataclasses are used to provide typed access to tmux' option shape.

Extra data gleaned from the options, such as user options (custom data) and an option
being inherited,

User options
------------
There are also custom user options, preceded with @, which exist are stored to
`Options.context.user_options` as a dictionary.

> tmux set-option -w my-custom-variable my-value
invalid option: my-custom-option

> tmux set-option -w @my-custom-option my-value
> tmux show-option -w
@my-custom-optione my-value

Inherited options
-----------------

``tmux show-options`` -A can include inherited options. The raw output of an inherited
option is detected by the key having a ``*``::

    visual-activity* on
    visual-bell* off

A list of options that are inherited is kept at ``Options.context._inherited_options`` and
``Options.context.inherited_options``.

They are mixed with the normal options,
to differentiate them, run ``show_options()`` without ``include_inherited=True``.
"""

from __future__ import annotations

import io
import logging
import re
import shlex
import typing as t
import warnings

from libtmux._internal.sparse_array import SparseArray
from libtmux.common import CmdMixin
from libtmux.constants import (
    DEFAULT_OPTION_SCOPE,
    OPTION_SCOPE_FLAG_MAP,
    OptionScope,
    _DefaultOptionScope,
)

from . import exc

if t.TYPE_CHECKING:
    from typing import TypeAlias

    from typing_extensions import Self

    from libtmux._internal.constants import TerminalFeatures
    from libtmux.common import tmux_cmd


TerminalOverride = dict[str, str | None]
TerminalOverrides = dict[str, TerminalOverride]
CommandAliases = dict[str, str]

OptionDict: TypeAlias = dict[str, t.Any]
UntypedOptionsDict: TypeAlias = dict[str, str | None]
ExplodedUntypedOptionsDict: TypeAlias = dict[
    str,
    str | int | list[str] | dict[str, list[str]],
]
ExplodedComplexUntypedOptionsDict: TypeAlias = dict[
    str,
    str
    | int
    | list[str | int]
    | dict[str, list[str | int]]
    | SparseArray[str | int]
    | None,
]

logger = logging.getLogger(__name__)


def handle_option_error(error: str) -> type[exc.OptionError]:
    """Raise exception if error in option command found.

    In tmux 3.0, show-option and show-window-option return invalid option instead of
    unknown option. See https://github.com/tmux/tmux/blob/3.0/cmd-show-options.c.

    In tmux >2.4, there are 3 different types of option errors:

    - unknown option
    - invalid option
    - ambiguous option

    In tmux <2.4, unknown option was the only option.

    All errors raised will have the base error of :exc:`exc.OptionError`. So to
    catch any option error, use ``except exc.OptionError``.

    Parameters
    ----------
    error : str
        Error response from subprocess call.

    Raises
    ------
    :exc:`exc.OptionError`, :exc:`exc.UnknownOption`, :exc:`exc.InvalidOption`,
    :exc:`exc.AmbiguousOption`

    Examples
    --------
    >>> result = server.cmd(
    ...     'set-option',
    ...     'unknown-option-name',
    ... )

    >>> bool(isinstance(result.stderr, list) and len(result.stderr))
    True

    >>> import pytest
    >>> from libtmux import exc

    >>> with pytest.raises(exc.OptionError):
    ...     handle_option_error(result.stderr[0])
    """
    if "unknown option" in error:
        raise exc.UnknownOption(error)
    if "invalid option" in error:
        raise exc.InvalidOption(error)
    if "ambiguous option" in error:
        raise exc.AmbiguousOption(error)
    raise exc.OptionError(error)  # Raise generic option error


_V = t.TypeVar("_V")
ConvertedValue: TypeAlias = str | int | bool | None
ConvertedValues: TypeAlias = (
    ConvertedValue
    | list[ConvertedValue]
    | dict[str, ConvertedValue]
    | SparseArray[ConvertedValue]
)


def convert_value(
    value: _V | None,
) -> ConvertedValue | _V | None:
    """Convert raw option strings to python types.

    Examples
    --------
    >>> convert_value("on")
    True
    >>> convert_value("off")
    False

    >>> convert_value("1")
    1
    >>> convert_value("50")
    50

    >>> convert_value("%50")
    '%50'
    """
    if not isinstance(value, str):
        return value

    if value.isdigit():
        return int(value)

    if value == "on":
        return True

    if value == "off":
        return False

    return value


def convert_values(
    value: _V | None,
) -> ConvertedValues | _V | None:
    """Recursively convert values to python types via :func:`convert_value`.

    >>> convert_values(None)

    >>> convert_values("on")
    True
    >>> convert_values("off")
    False

    >>> convert_values(["on"])
    [True]
    >>> convert_values(["off"])
    [False]

    >>> convert_values({"window_index": "1"})
    {'window_index': 1}

    >>> convert_values({"visual-bell": "on"})
    {'visual-bell': True}
    """
    if value is None:
        return None
    if isinstance(value, dict):
        # Note: SparseArray inherits from dict, so this branch handles both
        for k, v in value.items():
            value[k] = convert_value(v)
        return value
    if isinstance(value, list):
        for idx, v in enumerate(value):
            value[idx] = convert_value(v)
        return value
    return convert_value(value)


def parse_options_to_dict(
    stdout: t.IO[str],
) -> UntypedOptionsDict:
    r"""Process subprocess.stdout options or hook output to flat, naive, untyped dict.

    Does not explode arrays or deep values.

    Examples
    --------
    >>> import io

    >>> raw_options = io.StringIO("status-keys vi")
    >>> parse_options_to_dict(raw_options) == {"status-keys": "vi"}
    True

    >>> int_options = io.StringIO("message-limit 50")
    >>> parse_options_to_dict(int_options) == {"message-limit": "50"}
    True

    >>> empty_option = io.StringIO("user-keys")
    >>> parse_options_to_dict(empty_option) == {"user-keys": None}
    True

    >>> array_option = io.StringIO("command-alias[0] split-pane=split-window")
    >>> parse_options_to_dict(array_option) == {
    ... "command-alias[0]": "split-pane=split-window"}
    True

    >>> array_option = io.StringIO("command-alias[40] split-pane=split-window")
    >>> parse_options_to_dict(array_option) == {
    ... "command-alias[40]": "split-pane=split-window"}
    True

    >>> many_options = io.StringIO(r'''status-keys
    ... command-alias[0] split-pane=split-window
    ... ''')
    >>> parse_options_to_dict(many_options) == {
    ... "command-alias[0]": "split-pane=split-window",
    ... "status-keys": None,}
    True

    >>> many_more_options = io.StringIO(r'''
    ... terminal-features[0] xterm*:clipboard:ccolour:cstyle:focus
    ... terminal-features[1] screen*:title
    ... ''')
    >>> parse_options_to_dict(many_more_options) == {
    ... "terminal-features[0]": "xterm*:clipboard:ccolour:cstyle:focus",
    ... "terminal-features[1]": "screen*:title",}
    True

    >>> quoted_option = io.StringIO(r'''
    ... command-alias[0] "choose-session=choose-tree -s"
    ... ''')
    >>> parse_options_to_dict(quoted_option) == {
    ... "command-alias[0]": "choose-session=choose-tree -s",
    ... }
    True
    """
    output: UntypedOptionsDict = {}

    val: ConvertedValue | None = None

    for item in stdout.readlines():
        if " " in item:
            try:
                key, val = shlex.split(item)
            except ValueError:
                key, val = item.split(" ", maxsplit=1)
        else:
            key, val = item, None
        key = key.strip()

        if key:
            if isinstance(val, str) and val.endswith("\n"):
                val = val.rstrip("\n")

            output[key] = val
    return output


def explode_arrays(
    _dict: UntypedOptionsDict,
    force_array: bool = False,
) -> ExplodedUntypedOptionsDict:
    """Explode flat, naive options dict's option arrays.

    Examples
    --------
    >>> import io

    >>> many_more_options = io.StringIO(r'''
    ... terminal-features[0] xterm*:clipboard:ccolour:cstyle:focus
    ... terminal-features[1] screen*:title
    ... ''')
    >>> many_more_flat_dict = parse_options_to_dict(many_more_options)
    >>> many_more_flat_dict == {
    ... "terminal-features[0]": "xterm*:clipboard:ccolour:cstyle:focus",
    ... "terminal-features[1]": "screen*:title",}
    True
    >>> explode_arrays(many_more_flat_dict) == {
    ... "terminal-features": {0: "xterm*:clipboard:ccolour:cstyle:focus",
    ... 1: "screen*:title"}}
    True

    tmux arrays allow non-sequential indexes, so we need to support that:

    >>> explode_arrays(parse_options_to_dict(io.StringIO(r'''
    ... terminal-features[0] xterm*:clipboard:ccolour:cstyle:focus
    ... terminal-features[5] screen*:title
    ... '''))) == {
    ... "terminal-features": {0: "xterm*:clipboard:ccolour:cstyle:focus",
    ... 5: "screen*:title"}}
    True

    Use ``force_array=True`` for hooks, which always use array format:

    >>> from libtmux._internal.sparse_array import SparseArray

    >>> hooks_output = io.StringIO(r'''
    ... session-renamed[0] display-message 'renamed'
    ... session-renamed[5] refresh-client
    ... pane-focus-in[0] run-shell 'echo focus'
    ... ''')
    >>> hooks_exploded = explode_arrays(
    ...     parse_options_to_dict(hooks_output),
    ...     force_array=True,
    ... )

    Each hook becomes a SparseArray preserving indices:

    >>> isinstance(hooks_exploded["session-renamed"], SparseArray)
    True
    >>> hooks_exploded["session-renamed"][0]
    "display-message 'renamed'"
    >>> hooks_exploded["session-renamed"][5]
    'refresh-client'
    >>> sorted(hooks_exploded["session-renamed"].keys())
    [0, 5]
    """
    options: dict[str, t.Any] = {}
    for key, val in _dict.items():
        Default: type[dict[t.Any, t.Any] | SparseArray[str | int | bool | None]] = (
            dict if isinstance(key, str) and key == "terminal-features" else SparseArray
        )
        if "[" not in key:
            if force_array:
                options[key] = Default()
                if val is not None:
                    options[key][0] = val
            else:
                options[key] = val
            continue

        try:
            matchgroup = re.match(
                r"(?P<option>[\w-]+)(\[(?P<index>\d+)\])?(?P<inherited>\*)?",
                key,
            )
            if matchgroup is not None:
                match = matchgroup.groupdict()
                if match.get("option") and match.get("index"):
                    # Preserve inherited marker (*) if present
                    base_key = match["option"]
                    if match.get("inherited"):
                        base_key += "*"
                    key = base_key
                    index = int(match["index"])

                    if options.get(key) is None:
                        options[key] = Default()
                    options[key][index] = val
        except Exception:
            if force_array and val:
                options[key] = Default()
                if isinstance(options[key], SparseArray):
                    options[key][0] = val
            else:
                options[key] = val
            logger.exception("Error parsing options")
    return options


def explode_complex(
    _dict: ExplodedUntypedOptionsDict,
) -> ExplodedComplexUntypedOptionsDict:
    r"""Explode arrayed option's complex values.

    Examples
    --------
    >>> import io

    >>> explode_complex(explode_arrays(parse_options_to_dict(io.StringIO(r'''
    ... terminal-features[0] xterm*:clipboard:ccolour:cstyle:focus
    ... terminal-features[5] screen*:title
    ... '''))))
    {'terminal-features': {'xterm*': ['clipboard', 'ccolour', 'cstyle', 'focus'], 'screen*': ['title']}}

    >>> explode_complex(explode_arrays(parse_options_to_dict(io.StringIO(r'''
    ... terminal-features[0] xterm*:clipboard:ccolour:cstyle:focus
    ... terminal-features[5] screen*:title
    ... ''')))) == {
    ... "terminal-features": {"xterm*": ["clipboard", "ccolour", "cstyle", "focus"],
    ... "screen*": ["title"]}}
    True

    >>> explode_complex(explode_arrays(parse_options_to_dict(io.StringIO(r'''
    ... command-alias[0] split-pane=split-window
    ... command-alias[1] splitp=split-window
    ... command-alias[2] "server-info=show-messages -JT"
    ... ''')))) == {
    ... "command-alias": {"split-pane": "split-window",
    ... "splitp": "split-window",
    ... "server-info": "show-messages -JT"}}
    True

    >>> explode_complex(explode_arrays({"terminal-features": {0: "xterm*:clipboard:ccolour:cstyle:focus",
    ... 1: "screen*:title"}}))
    {'terminal-features': {0: 'xterm*:clipboard:ccolour:cstyle:focus', 1: 'screen*:title'}}

    >>> explode_complex(explode_arrays({"terminal-features": {0: "xterm*:clipboard:ccolour:cstyle:focus",
    ... 8: "screen*:title"}})) == SparseArray({'terminal-features': {0:
    ... 'xterm*:clipboard:ccolour:cstyle:focus', 8: 'screen*:title'}})
    True

    >>> explode_complex(explode_arrays(parse_options_to_dict(io.StringIO(r'''
    ... terminal-overrides[0] xterm-256color:Tc
    ... terminal-overrides[1] *:U8=0
    ... ''')))) == {
    ... "terminal-overrides": {"xterm-256color": {"Tc": None},
    ... "*": {"U8": 0}}}
    True

    >>> explode_complex(explode_arrays(parse_options_to_dict(io.StringIO(r'''
    ... user-keys[100] "\e[test"
    ... user-keys[6] "\e\n"
    ... user-keys[0] "\e[5;30012~"
    ... ''')))) == {
    ... "user-keys": {0: "\\e[5;30012~",
    ... 6: "\\e\\n",
    ... 100: "\\e[test"}}
    True

    >>> explode_complex(explode_arrays(parse_options_to_dict(io.StringIO(r'''
    ... status-format[0] "#[align=left range=left #{E:status-left-style}]#[push-default]#{T;=/#{status-left-length}:status-left}#[pop-default]#[norange default]#[list=on align=#{status-justify}]#[list=left-marker]<#[list=right-marker]>#[list=on]#{W:#[range=window|#{window_index} #{E:window-status-style}#{?#{&&:#{window_last_flag},#{!=:#{E:window-status-last-style},default}}, #{E:window-status-last-style},}#{?#{&&:#{window_bell_flag},#{!=:#{E:window-status-bell-style},default}}, #{E:window-status-bell-style},#{?#{&&:#{||:#{window_activity_flag},#{window_silence_flag}},#{!=:#{E:window-status-activity-style},default}}, #{E:window-status-activity-style},}}]#[push-default]#{T:window-status-format}#[pop-default]#[norange default]#{?window_end_flag,,#{window-status-separator}},#[range=window|#{window_index} list=focus #{?#{!=:#{E:window-status-current-style},default},#{E:window-status-current-style},#{E:window-status-style}}#{?#{&&:#{window_last_flag},#{!=:#{E:window-status-last-style},default}}, #{E:window-status-last-style},}#{?#{&&:#{window_bell_flag},#{!=:#{E:window-status-bell-style},default}}, #{E:window-status-bell-style},#{?#{&&:#{||:#{window_activity_flag},#{window_silence_flag}},#{!=:#{E:window-status-activity-style},default}}, #{E:window-status-activity-style},}}]#[push-default]#{T:window-status-current-format}#[pop-default]#[norange list=on default]#{?window_end_flag,,#{window-status-separator}}}#[nolist align=right range=right #{E:status-right-style}]#[push-default]#{T;=/#{status-right-length}:status-right}#[pop-default]#[norange default]"
    ... status-format[1] "#[align=centre]#{P:#{?pane_active,#[reverse],}#{pane_index}[#{pane_width}x#{pane_height}]#[default] }"
    ... ''')))) == {
    ... "status-format": {0: "#[align=left range=left #{E:status-left-style}]#[push-default]#{T;=/#{status-left-length}:status-left}#[pop-default]#[norange default]#[list=on align=#{status-justify}]#[list=left-marker]<#[list=right-marker]>#[list=on]#{W:#[range=window|#{window_index} #{E:window-status-style}#{?#{&&:#{window_last_flag},#{!=:#{E:window-status-last-style},default}}, #{E:window-status-last-style},}#{?#{&&:#{window_bell_flag},#{!=:#{E:window-status-bell-style},default}}, #{E:window-status-bell-style},#{?#{&&:#{||:#{window_activity_flag},#{window_silence_flag}},#{!=:#{E:window-status-activity-style},default}}, #{E:window-status-activity-style},}}]#[push-default]#{T:window-status-format}#[pop-default]#[norange default]#{?window_end_flag,,#{window-status-separator}},#[range=window|#{window_index} list=focus #{?#{!=:#{E:window-status-current-style},default},#{E:window-status-current-style},#{E:window-status-style}}#{?#{&&:#{window_last_flag},#{!=:#{E:window-status-last-style},default}}, #{E:window-status-last-style},}#{?#{&&:#{window_bell_flag},#{!=:#{E:window-status-bell-style},default}}, #{E:window-status-bell-style},#{?#{&&:#{||:#{window_activity_flag},#{window_silence_flag}},#{!=:#{E:window-status-activity-style},default}}, #{E:window-status-activity-style},}}]#[push-default]#{T:window-status-current-format}#[pop-default]#[norange list=on default]#{?window_end_flag,,#{window-status-separator}}}#[nolist align=right range=right #{E:status-right-style}]#[push-default]#{T;=/#{status-right-length}:status-right}#[pop-default]#[norange default]",
    ... 1: "#[align=centre]#{P:#{?pane_active,#[reverse],}#{pane_index}[#{pane_width}x#{pane_height}]#[default] }",
    ... }}
    True
    """
    options: dict[str, t.Any] = {}
    for key, val in _dict.items():
        try:
            if isinstance(val, SparseArray) and key == "terminal-features":
                new_val: TerminalFeatures = {}

                for item in val.iter_values():
                    try:
                        term, features = item.split(":", maxsplit=1)
                        new_val[term] = features.split(":")
                    except Exception:  # NOQA: PERF203
                        logger.exception("Error parsing options")
                options[key] = new_val
                continue
            if isinstance(val, SparseArray) and key == "terminal-overrides":
                new_overrides: TerminalOverrides = {}

                for item in val.iter_values():
                    try:
                        # Split on all colons: first part is terminal pattern,
                        # remaining parts are individual features/capabilities
                        parts = item.split(":")
                        term = parts[0]
                        features = parts[1:]

                        if term not in new_overrides:
                            new_overrides[term] = {}

                        for feature in features:
                            if feature and "=" in feature:
                                k, v = feature.split("=", 1)
                                new_overrides[term][k] = int(v) if v.isdigit() else v
                            elif feature:
                                new_overrides[term][feature] = None
                    except Exception:  # NOQA: PERF203
                        logger.exception("Error parsing options")
                options[key] = new_overrides
                continue
            if isinstance(val, SparseArray) and key == "command-alias":
                new_aliases: CommandAliases = {}

                for item in val.iter_values():
                    try:
                        alias, command = item.split("=", maxsplit=1)
                        if options.get(key) is None or not isinstance(
                            options.get(key),
                            dict,
                        ):
                            options[key] = {}
                        new_aliases[alias] = command
                    except Exception:  # NOQA: PERF203
                        logger.exception("Error parsing options")
                options[key] = new_aliases
                continue
            options[key] = val
            continue

        except Exception:
            options[key] = val
            logger.exception("Error parsing options")
    return options


class OptionsMixin(CmdMixin):
    """Mixin for managing tmux options based on scope."""

    default_option_scope: OptionScope | None

    def __init__(self, default_option_scope: OptionScope | None = None) -> None:
        """When not a user (custom) option, scope can be implied."""
        if default_option_scope is not None:
            self.default_option_scope = default_option_scope

    def set_option(
        self,
        option: str,
        value: int | str,
        _format: bool | None = None,
        prevent_overwrite: bool | None = None,
        ignore_errors: bool | None = None,
        suppress_warnings: bool | None = None,
        append: bool | None = None,
        g: bool | None = None,
        global_: bool | None = None,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
    ) -> Self:
        """Set option for tmux target.

        Wraps ``$ tmux set-option <option> <value>``.

        Parameters
        ----------
        option : str
            option to set, e.g. 'aggressive-resize'
        value : str
            option value. True/False will turn in 'on' and 'off',
            also accepts string of 'on' or 'off' directly.

        .. deprecated:: 0.28

           Deprecated by ``g`` for global, use ``global_`` instead.

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`

        Examples
        --------
        >>> import typing as t
        >>> from libtmux.common import tmux_cmd
        >>> from libtmux.constants import OptionScope
        >>> from libtmux._internal.sparse_array import SparseArray

        >>> class MyServer(OptionsMixin):
        ...     socket_name = server.socket_name
        ...     def cmd(self, cmd: str, *args: object):
        ...         cmd_args: t.List[t.Union[str, int]] = [cmd]
        ...         if self.socket_name:
        ...             cmd_args.insert(0, f"-L{self.socket_name}")
        ...         cmd_args.insert(0, "-f/dev/null")
        ...         return tmux_cmd(*cmd_args, *args)
        ...
        ...     default_option_scope = OptionScope.Server

        >>> MyServer().set_option('escape-time', 1250)
        <libtmux.options.MyServer object at ...>

        >>> MyServer()._show_option('escape-time')
        1250

        >>> MyServer().set_option('escape-time', 495)
        <libtmux.options.MyServer object at ...>

        >>> MyServer()._show_option('escape-time')
        495
        """
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_option_scope

        flags: list[str] = []
        if isinstance(value, bool) and value:
            value = "on"
        elif isinstance(value, bool) and not value:
            value = "off"

        if _format is not None and _format:
            assert isinstance(_format, bool)
            flags.append("-F")

        if prevent_overwrite is not None and prevent_overwrite:
            assert isinstance(prevent_overwrite, bool)
            flags.append("-o")

        if ignore_errors is not None and ignore_errors:
            assert isinstance(ignore_errors, bool)
            flags.append("-q")

        if suppress_warnings is not None and suppress_warnings:
            assert isinstance(suppress_warnings, bool)
            flags.append("-q")

        if append is not None and append:
            assert isinstance(append, bool)
            flags.append("-a")

        if g is not None:
            warnings.warn(
                "g argument is deprecated in favor of global_",
                category=DeprecationWarning,
                stacklevel=2,
            )
            global_ = g

        if global_ is not None and global_:
            assert isinstance(global_, bool)
            flags.append("-g")

        if scope is not None and not isinstance(scope, _DefaultOptionScope):
            assert scope in OPTION_SCOPE_FLAG_MAP
            scope_flag = OPTION_SCOPE_FLAG_MAP[scope]
            if scope_flag:  # Session scope has empty string, skip it
                flags.append(scope_flag)

        cmd = self.cmd(
            "set-option",
            *flags,
            option,
            value,
        )

        if isinstance(cmd.stderr, list) and len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        return self

    def unset_option(
        self,
        option: str,
        unset_panes: bool | None = None,
        global_: bool | None = None,
        ignore_errors: bool | None = None,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
    ) -> Self:
        """Unset option for tmux target.

        Wraps ``$ tmux set-option -u <option>`` / ``$ tmux set-option -U <option>``

        Parameters
        ----------
        option : str
            option to unset, e.g. 'aggressive-resize'

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`

        Examples
        --------
        >>> import typing as t
        >>> from libtmux.common import tmux_cmd
        >>> from libtmux.constants import OptionScope

        >>> class MyServer(OptionsMixin):
        ...     socket_name = server.socket_name
        ...     def cmd(self, cmd: str, *args: object):
        ...         cmd_args: t.List[t.Union[str, int]] = [cmd]
        ...         if self.socket_name:
        ...             cmd_args.insert(0, f"-L{self.socket_name}")
        ...         cmd_args.insert(0, "-f/dev/null")
        ...         return tmux_cmd(*cmd_args, *args)
        ...
        ...     default_option_scope = OptionScope.Server

        >>> MyServer().set_option('escape-time', 1250)
        <libtmux.options.MyServer object at ...>

        >>> MyServer()._show_option('escape-time')
        1250

        >>> MyServer().unset_option('escape-time')
        <libtmux.options.MyServer object at ...>

        >>> isinstance(MyServer()._show_option('escape-time'), int)
        True
        """
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_option_scope

        flags: list[str] = []

        if unset_panes is not None and unset_panes:
            assert isinstance(unset_panes, bool)
            flags.append("-U")
        else:
            flags.append("-u")

        if ignore_errors is not None and ignore_errors:
            assert isinstance(ignore_errors, bool)
            flags.append("-q")

        if global_ is not None and global_:
            assert isinstance(global_, bool)
            flags.append("-g")

        if scope is not None and not isinstance(scope, _DefaultOptionScope):
            assert scope in OPTION_SCOPE_FLAG_MAP
            scope_flag = OPTION_SCOPE_FLAG_MAP[scope]
            if scope_flag:  # Session scope has empty string, skip it
                flags.append(scope_flag)

        cmd = self.cmd(
            "set-option",
            *flags,
            option,
        )

        if isinstance(cmd.stderr, list) and len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        return self

    def _show_options_raw(
        self,
        g: bool | None = False,
        global_: bool | None = False,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
        include_hooks: bool | None = None,
        include_inherited: bool | None = None,
    ) -> tmux_cmd:
        """Return a dict of options for the target.

        Parameters
        ----------
        g : bool, optional
            .. deprecated:: 0.50.0
               Use ``global_`` instead.

        Examples
        --------
        >>> import typing as t
        >>> from libtmux.common import tmux_cmd
        >>> from libtmux.constants import OptionScope

        >>> class MyServer(OptionsMixin):
        ...     socket_name = server.socket_name
        ...     def cmd(self, cmd: str, *args: object):
        ...         cmd_args: t.List[t.Union[str, int]] = [cmd]
        ...         if self.socket_name:
        ...             cmd_args.insert(0, f"-L{self.socket_name}")
        ...         cmd_args.insert(0, "-f/dev/null")
        ...         return tmux_cmd(*cmd_args, *args)
        ...
        ...     default_option_scope = OptionScope.Server

        >>> MyServer()._show_options_raw()
        <libtmux.common.tmux_cmd object at ...>

        >>> MyServer()._show_options_raw().stdout
        [...]
        """
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_option_scope

        flags: tuple[str, ...] = ()

        if g:
            warnings.warn(
                "g argument is deprecated in favor of global_",
                category=DeprecationWarning,
                stacklevel=2,
            )
            global_ = g

        if global_:
            flags += ("-g",)

        if scope is not None and not isinstance(scope, _DefaultOptionScope):
            assert scope in OPTION_SCOPE_FLAG_MAP
            scope_flag = OPTION_SCOPE_FLAG_MAP[scope]
            if scope_flag:  # Session scope has empty string, skip it
                flags += (scope_flag,)

        if include_inherited is not None and include_inherited:
            flags += ("-A",)

        if include_hooks is not None and include_hooks:
            flags += ("-H",)

        return self.cmd("show-options", *flags)

    def _show_options_dict(
        self,
        g: bool | None = False,
        global_: bool | None = False,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
        include_hooks: bool | None = None,
        include_inherited: bool | None = None,
    ) -> UntypedOptionsDict:
        """Return dict of options for the target.

        Parameters
        ----------
        g : bool, optional
            .. deprecated:: 0.50.0
               Use ``global_`` instead.

        Examples
        --------
        >>> import typing as t
        >>> from libtmux.common import tmux_cmd
        >>> from libtmux.constants import OptionScope

        >>> class MyServer(OptionsMixin):
        ...     socket_name = server.socket_name
        ...     def cmd(self, cmd: str, *args: object):
        ...         cmd_args: t.List[t.Union[str, int]] = [cmd]
        ...         if self.socket_name:
        ...             cmd_args.insert(0, f"-L{self.socket_name}")
        ...         cmd_args.insert(0, "-f/dev/null")
        ...         return tmux_cmd(*cmd_args, *args)
        ...
        ...     default_option_scope = OptionScope.Server

        >>> MyServer()._show_options_dict()
        {...}

        >>> isinstance(MyServer()._show_options_dict(), dict)
        True
        """
        cmd = self._show_options_raw(
            global_=global_,
            scope=scope,
            include_hooks=include_hooks,
            include_inherited=include_inherited,
        )

        return parse_options_to_dict(
            io.StringIO("\n".join(cmd.stdout)),
        )

    def _show_options(
        self,
        g: bool | None = False,
        global_: bool | None = False,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
        include_hooks: bool | None = None,
        include_inherited: bool | None = None,
    ) -> ExplodedComplexUntypedOptionsDict:
        """Return a dict of options for the target.

        Parameters
        ----------
        g : bool, optional
            .. deprecated:: 0.50.0
               Use ``global_`` instead.

        Examples
        --------
        >>> import typing as t
        >>> from libtmux.common import tmux_cmd
        >>> from libtmux.constants import OptionScope

        >>> class MyServer(OptionsMixin):
        ...     socket_name = server.socket_name
        ...     def cmd(self, cmd: str, *args: object):
        ...         cmd_args: t.List[t.Union[str, int]] = [cmd]
        ...         if self.socket_name:
        ...             cmd_args.insert(0, f"-L{self.socket_name}")
        ...         cmd_args.insert(0, "-f/dev/null")
        ...         return tmux_cmd(*cmd_args, *args)
        ...
        ...     default_option_scope = OptionScope.Server

        >>> MyServer()._show_options()
        {...}
        """
        dict_output = self._show_options_dict(
            global_=global_,
            scope=scope,
            include_hooks=include_hooks,
            include_inherited=include_inherited,
        )

        output_exploded = convert_values(
            explode_complex(
                explode_arrays(dict_output),
            ),
        )

        return t.cast("ExplodedComplexUntypedOptionsDict", output_exploded)

    def show_options(
        self,
        global_: bool = False,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
        include_hooks: bool | None = None,
        include_inherited: bool | None = None,
    ) -> ExplodedComplexUntypedOptionsDict:
        """Return all options for the target.

        Parameters
        ----------
        global_ : bool, optional
            Pass ``-g`` flag for global options, default False.
        scope : OptionScope | _DefaultOptionScope | None, optional
            Option scope (Server/Session/Window/Pane), defaults to object's scope.
        include_hooks : bool, optional
            Include hook options (``-H`` flag).
        include_inherited : bool, optional
            Include inherited options (``-A`` flag).

        Returns
        -------
        ExplodedComplexUntypedOptionsDict
            Dictionary with all options, arrays exploded and values converted.

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`

        Examples
        --------
        >>> options = server.show_options()
        >>> isinstance(options, dict)
        True

        >>> 'buffer-limit' in options
        True
        """
        return self._show_options(
            global_=global_,
            scope=scope,
            include_hooks=include_hooks,
            include_inherited=include_inherited,
        )

    def _show_option_raw(
        self,
        option: str,
        global_: bool = False,
        g: bool = False,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
        ignore_errors: bool | None = None,
        include_hooks: bool | None = None,
        include_inherited: bool | None = None,
    ) -> tmux_cmd:
        """Return raw option output for target.

        Parameters
        ----------
        option : str
        g : bool, optional
            .. deprecated:: 0.50.0
               Use ``global_`` instead.

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`

        Examples
        --------
        >>> import typing as t
        >>> from libtmux.common import tmux_cmd
        >>> from libtmux.constants import OptionScope

        >>> class MyServer(OptionsMixin):
        ...     socket_name = server.socket_name
        ...     def cmd(self, cmd: str, *args: object):
        ...         cmd_args: t.List[t.Union[str, int]] = [cmd]
        ...         if self.socket_name:
        ...             cmd_args.insert(0, f"-L{self.socket_name}")
        ...         cmd_args.insert(0, "-f/dev/null")
        ...         return tmux_cmd(*cmd_args, *args)
        ...
        ...     default_option_scope = OptionScope.Server

        >>> MyServer().cmd('new-session', '-d')
        <libtmux.common.tmux_cmd object at ...>

        >>> MyServer()._show_option_raw('exit-unattached', global_=True)
        <libtmux.common.tmux_cmd object at ...>

        >>> MyServer()._show_option_raw('exit-unattached', global_=True).stdout
        ['exit-unattached off']

        >>> isinstance(MyServer()._show_option_raw('exit-unattached', global_=True).stdout, list)
        True

        >>> isinstance(MyServer()._show_option_raw('exit-unattached', global_=True).stdout[0], str)
        True
        """
        if scope is DEFAULT_OPTION_SCOPE:
            scope = self.default_option_scope

        flags: tuple[str | int, ...] = ()

        if g:
            warnings.warn(
                "g argument is deprecated in favor of global_",
                category=DeprecationWarning,
                stacklevel=2,
            )
            global_ = g

        if global_:
            flags += ("-g",)

        if scope is not None and not isinstance(scope, _DefaultOptionScope):
            assert scope in OPTION_SCOPE_FLAG_MAP
            scope_flag = OPTION_SCOPE_FLAG_MAP[scope]
            if scope_flag:  # Session scope has empty string, skip it
                flags += (scope_flag,)

        if ignore_errors is not None and ignore_errors:
            flags += ("-q",)

        if include_inherited is not None and include_inherited:
            flags += ("-A",)

        if include_hooks is not None and include_hooks:
            flags += ("-H",)

        flags += (option,)

        return self.cmd("show-options", *flags)

    def _show_option(
        self,
        option: str,
        global_: bool = False,
        g: bool = False,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
        ignore_errors: bool | None = None,
        include_hooks: bool | None = None,
        include_inherited: bool | None = None,
    ) -> ConvertedValue | None:
        """Return option value for the target.

        todo: test and return True/False for on/off string

        Parameters
        ----------
        option : str
        g : bool, optional
            .. deprecated:: 0.50.0
               Use ``global_`` instead.

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`

        Examples
        --------
        >>> import typing as t
        >>> from libtmux.common import tmux_cmd
        >>> from libtmux.constants import OptionScope

        >>> class MyServer(OptionsMixin):
        ...     socket_name = server.socket_name
        ...     def cmd(self, cmd: str, *args: object):
        ...         cmd_args: t.List[t.Union[str, int]] = [cmd]
        ...         if self.socket_name:
        ...             cmd_args.insert(0, f"-L{self.socket_name}")
        ...         cmd_args.insert(0, "-f/dev/null")
        ...         return tmux_cmd(*cmd_args, *args)
        ...
        ...     default_option_scope = OptionScope.Server

        >>> MyServer().cmd('new-session', '-d')
        <libtmux.common.tmux_cmd object at ...>

        >>> MyServer()._show_option('exit-unattached', global_=True)
        False
        """
        cmd = self._show_option_raw(
            option=option,
            global_=global_,
            scope=scope,
            ignore_errors=ignore_errors,
            include_hooks=include_hooks,
            include_inherited=include_inherited,
        )

        if cmd.stderr is not None and len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        options_output = cmd.stdout

        if not len(options_output):
            return None

        # Parse raw output first (preserves indexed keys like "status-format[0]")
        output_raw = parse_options_to_dict(io.StringIO("\n".join(cmd.stdout)))

        # Handle tmux's inherited option marker: tmux appends "*" to option names
        # that are inherited from a parent scope (e.g., "visual-activity*" for an
        # option inherited from global scope). We need to check for both the exact
        # option name and the name with "*" suffix.
        option_key = option
        if option not in output_raw and f"{option}*" in output_raw:
            option_key = f"{option}*"

        # Direct lookup for indexed queries (e.g., "status-format[0]")
        # tmux returns only that index's value, so we handle it before exploding
        if option_key in output_raw:
            return convert_value(output_raw[option_key])

        # For base name queries, explode arrays and return structured data
        output_exploded = convert_values(explode_complex(explode_arrays(output_raw)))

        if not isinstance(output_exploded, (dict, SparseArray)):
            return t.cast("ConvertedValue", output_exploded)

        # Check for inherited marker in exploded output as well
        exploded_key = option
        if isinstance(output_exploded, dict):
            if option not in output_exploded and f"{option}*" in output_exploded:
                exploded_key = f"{option}*"
            if exploded_key not in output_exploded:
                return None

        if isinstance(output_exploded, SparseArray):
            try:
                index = int(option)
                return output_exploded[index]
            except (ValueError, KeyError):
                return None

        return t.cast("ConvertedValue | None", output_exploded[exploded_key])

    def show_option(
        self,
        option: str,
        global_: bool = False,
        g: bool = False,
        scope: OptionScope | _DefaultOptionScope | None = DEFAULT_OPTION_SCOPE,
        ignore_errors: bool | None = None,
        include_hooks: bool | None = None,
        include_inherited: bool | None = None,
    ) -> t.Any | None:
        """Return option value for the target.

        Parameters
        ----------
        option : str
        g : bool, optional
            .. deprecated:: 0.50.0
               Use ``global_`` instead.

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`

        Examples
        --------
        >>> import typing as t
        >>> from libtmux.common import tmux_cmd
        >>> from libtmux.constants import OptionScope

        >>> class MyServer(OptionsMixin):
        ...     socket_name = server.socket_name
        ...     def cmd(self, cmd: str, *args: object):
        ...         cmd_args: t.List[t.Union[str, int]] = [cmd]
        ...         if self.socket_name:
        ...             cmd_args.insert(0, f"-L{self.socket_name}")
        ...         cmd_args.insert(0, "-f/dev/null")
        ...         return tmux_cmd(*cmd_args, *args)
        ...
        ...     default_option_scope = OptionScope.Server

        >>> MyServer().cmd('new-session', '-d')
        <libtmux.common.tmux_cmd object at ...>

        >>> MyServer().show_option('exit-unattached', global_=True)
        False
        """
        if g:
            warnings.warn(
                "g argument is deprecated in favor of global_",
                category=DeprecationWarning,
                stacklevel=2,
            )
            global_ = g

        return self._show_option(
            option=option,
            global_=global_,
            scope=scope,
            ignore_errors=ignore_errors,
            include_hooks=include_hooks,
            include_inherited=include_inherited,
        )
