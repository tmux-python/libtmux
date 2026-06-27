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
>>> ws.windows[0].panes[0].commands
('vim',)
>>> ws.windows[0].panes[1].commands
('cd src', 'pytest -q')
"""

from __future__ import annotations

import collections.abc
import typing as t

from libtmux.experimental.workspace.ir import Pane, Window, Workspace


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
        panes=[_pane(p) for p in raw.get("panes", []) or []],
    )


def _pane(raw: t.Any) -> Pane:
    """Normalize one pane config (None / bare string / mapping)."""
    if raw is None:
        return Pane()
    if isinstance(raw, str):
        return Pane(run=raw)
    if isinstance(raw, collections.abc.Mapping):
        return Pane(
            run=_shell_commands(raw.get("shell_command")),
            focus=bool(raw.get("focus", False)),
            start_directory=raw.get("start_directory"),
            sleep_before=raw.get("sleep_before"),
            sleep_after=raw.get("sleep_after"),
            environment=dict(raw.get("environment", {}) or {}),
            shell=raw.get("shell"),
        )
    msg = f"unsupported pane config: {raw!r}"
    raise TypeError(msg)


def _shell_commands(value: t.Any) -> tuple[str, ...]:
    """Normalize a ``shell_command`` (None / string / list of str|{cmd})."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    out: list[str] = []
    for item in t.cast("collections.abc.Sequence[t.Any]", value):
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, collections.abc.Mapping):
            out.append(str(item["cmd"]))
    return tuple(out)
