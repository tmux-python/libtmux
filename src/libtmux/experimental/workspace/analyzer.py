"""Analyze a tmuxp-style YAML/dict workspace into the declarative IR.

A small subset of tmuxp's ``loader.expand``/``trickle``: it normalizes shorthand
(a bare-string pane, a string/list ``shell_command``, a ``cmd``-dict list) into the
canonical :class:`~.ir.Workspace` / :class:`~.ir.Window` / :class:`~.ir.Pane` tree.
Pure -- no tmux.

Examples
--------
>>> ws = analyze({
...     "session_name": "dev",
...     "start_directory": "~/work",
...     "windows": [
...         {"window_name": "editor", "layout": "main-vertical",
...          "panes": ["vim", {"shell_command": ["cd src", "pytest -q"]}]},
...         {"window_name": "logs", "panes": ["tail -f app.log"]},
...     ],
... })
>>> ws.name
'dev'
>>> [w.name for w in ws.windows]
['editor', 'logs']
>>> [c.cmd for c in ws.windows[0].panes[0].commands]
['vim']
>>> [c.cmd for c in ws.windows[0].panes[1].commands]
['cd src', 'pytest -q']
"""

from __future__ import annotations

import collections.abc
import typing as t

from libtmux.experimental.workspace.ir import (
    Command,
    Float,
    FloatingPane,
    Pane,
    Window,
    Workspace,
)


def analyze(raw: collections.abc.Mapping[str, t.Any] | str) -> Workspace:
    """Normalize a tmuxp-style config (dict or YAML string) into a Workspace."""
    data = _load(raw)
    windows = [_window(w) for w in data.get("windows", []) or []]
    return Workspace(
        name=data["session_name"],
        dimensions=_dimensions(data.get("dimensions")),
        start_directory=data.get("start_directory"),
        environment=dict(data.get("environment", {}) or {}),
        options=dict(data.get("options", {}) or {}),
        global_options=dict(data.get("global_options", {}) or {}),
        windows=windows,
        before_script=data.get("before_script"),
        on_exists=data.get("on_exists", "error"),
        wait_pane=bool(data.get("wait_pane", False)),
    )


def _load(
    raw: collections.abc.Mapping[str, t.Any] | str,
) -> collections.abc.Mapping[str, t.Any]:
    """Return a mapping from a dict or a YAML string."""
    if isinstance(raw, str):
        import yaml  # type: ignore[import-untyped]

        loaded = yaml.safe_load(raw)
        if not isinstance(loaded, collections.abc.Mapping):
            msg = "workspace YAML must be a mapping"
            raise TypeError(msg)
        return loaded
    return raw


def _dimensions(value: t.Any) -> tuple[int, int] | None:
    """Coerce a ``[x, y]`` / ``{width, height}`` value to a dimensions tuple."""
    if value is None:
        return None
    if isinstance(value, collections.abc.Mapping):
        return (int(value["width"]), int(value["height"]))
    width, height = value
    return (int(width), int(height))


def _window(raw: collections.abc.Mapping[str, t.Any]) -> Window:
    """Normalize one window config."""
    return Window(
        name=raw.get("window_name"),
        layout=raw.get("layout"),
        start_directory=raw.get("start_directory"),
        focus=bool(raw.get("focus", False)),
        options=dict(raw.get("options", {}) or {}),
        options_after=dict(raw.get("options_after", {}) or {}),
        environment=dict(raw.get("environment", {}) or {}),
        window_shell=raw.get("window_shell"),
        window_index=raw.get("window_index"),
        panes=[_pane(p) for p in raw.get("panes", []) or []],
        floats=[_floating_pane(f) for f in raw.get("floats", []) or []],
    )


def _floating_pane(raw: collections.abc.Mapping[str, t.Any]) -> FloatingPane:
    """Normalize one floating-pane config (a pane config plus ``float``)."""
    return FloatingPane(
        pane=_pane(raw),
        geometry=_float(raw.get("float")),
        attach_to=raw.get("attach_to"),
    )


def _float(raw: t.Any) -> Float:
    """Coerce a ``float`` geometry value (mapping / None / marker) into a Float."""
    if not isinstance(raw, collections.abc.Mapping):
        return Float()
    return Float(
        width=raw.get("width"),
        height=raw.get("height"),
        x=raw.get("x"),
        y=raw.get("y"),
        zoom=bool(raw.get("zoom", False)),
        empty=bool(raw.get("empty", False)),
        style=raw.get("style"),
        active_border_style=raw.get("active_border_style"),
        inactive_border_style=raw.get("inactive_border_style"),
        message=raw.get("message"),
    )


#: Pane shorthands that mean "an empty pane" (no command sent), per tmuxp.
_BLANK_PANE = frozenset({"", "blank", "pane"})


def _is_blank_command(item: t.Any) -> bool:
    """Whether a pane/command shorthand means an empty pane (None/blank/pane)."""
    return item is None or (isinstance(item, str) and item.strip() in _BLANK_PANE)


def _pane(raw: t.Any) -> Pane:
    """Normalize one pane config (None / bare string / mapping).

    The bare-string shorthands ``blank`` / ``pane`` (and an empty/``None`` entry)
    mean "create an empty pane" -- they are markers, not commands, matching
    tmuxp.
    """
    if raw is None or (isinstance(raw, str) and raw.strip() in _BLANK_PANE):
        return Pane()
    if isinstance(raw, str):
        return Pane(run=raw)
    if isinstance(raw, collections.abc.Mapping):
        return Pane(
            run=_shell_commands(raw.get("shell_command")),
            focus=bool(raw.get("focus", False)),
            start_directory=raw.get("start_directory"),
            suppress_history=bool(raw.get("suppress_history", True)),
            sleep_before=raw.get("sleep_before"),
            sleep_after=raw.get("sleep_after"),
            environment=dict(raw.get("environment", {}) or {}),
            shell=raw.get("shell"),
        )
    msg = f"unsupported pane config: {raw!r}"
    raise TypeError(msg)


def _shell_commands(value: t.Any) -> tuple[str | Command, ...]:
    """Normalize a ``shell_command`` (None / string / list of str|{cmd}).

    A ``{cmd}`` mapping that carries ``enter``/``sleep_before``/``sleep_after``
    becomes a :class:`~.ir.Command` preserving that orchestration; a plain
    command stays a bare string.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return () if value.strip() in _BLANK_PANE else (value,)
    items = list(t.cast("collections.abc.Sequence[t.Any]", value))
    # A sole blank/pane/None element means "an empty pane" (tmuxp parity); a
    # blank mixed with real commands is left alone.
    if len(items) == 1 and _is_blank_command(items[0]):
        return ()
    out: list[str | Command] = []
    for item in items:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, collections.abc.Mapping):
            out.append(_command(item))
        elif item is None:
            continue  # a None mixed with real commands is a blank (tmuxp parity)
        else:
            msg = f"unsupported shell_command item: {item!r}"
            raise TypeError(msg)
    return tuple(out)


def _command(item: collections.abc.Mapping[str, t.Any]) -> str | Command:
    """Build a Command from a ``{cmd, enter?, sleep_before?, sleep_after?}`` map.

    Stays a bare string when no per-command overrides are present.
    """
    cmd = str(item["cmd"])
    enter = bool(item.get("enter", True))
    sleep_before = item.get("sleep_before")
    sleep_after = item.get("sleep_after")
    if enter and sleep_before is None and sleep_after is None:
        return cmd
    return Command(cmd, enter=enter, sleep_before=sleep_before, sleep_after=sleep_after)
