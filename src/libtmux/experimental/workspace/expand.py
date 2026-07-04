"""Pure variant expansion for declarative workspace specs."""

from __future__ import annotations

import collections.abc
import dataclasses
import re
import typing as t
from collections.abc import Callable, Iterable, Mapping

from libtmux.experimental.workspace.ir import Workspace

Variant: t.TypeAlias = Mapping[str, object]
NameFactory: t.TypeAlias = Callable[[str, Mapping[str, object]], str]

_TOKEN_RE = re.compile(
    r"\$(?P<escaped>\$)|\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}"
    r"|\$(?P<named>[A-Za-z_][A-Za-z0-9_]*)",
)


def expand(
    workspace: Workspace,
    variants: Iterable[Mapping[str, object]],
    *,
    variables: Mapping[str, object] | None = None,
    name: NameFactory | None = None,
) -> tuple[Workspace, ...]:
    """Return one rendered workspace per variant, without mutating *workspace*.

    String fields use shell-style ``$name`` / ``${name}`` placeholders. Unknown
    variables stay intact, so shell variables and tmux formats survive expansion.

    Examples
    --------
    >>> from libtmux.experimental.workspace import Pane, Window, Workspace, expand
    >>> base = Workspace("svc-$app", windows=[Window("$app", panes=[Pane("$cmd")])])
    >>> [ws.name for ws in expand(base, [{"app": "api", "cmd": "uvicorn"}])]
    ['svc-api']
    """
    expanded: list[Workspace] = []
    for variant in variants:
        context: dict[str, object] = dict(variables or {})
        context.update(variant)
        rendered = t.cast("Workspace", _render(workspace, context))
        if name is not None:
            rendered = dataclasses.replace(
                rendered,
                name=name(workspace.name, context),
            )
        expanded.append(rendered)
    return tuple(expanded)


def _render(value: t.Any, context: collections.abc.Mapping[str, object]) -> t.Any:
    """Recursively render strings inside dataclasses, mappings, and sequences."""
    if isinstance(value, str):
        return _render_string(value, context)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        changes = {
            field.name: _render(getattr(value, field.name), context)
            for field in dataclasses.fields(value)
        }
        return dataclasses.replace(value, **changes)
    if isinstance(value, collections.abc.Mapping):
        return {
            _render(key, context): _render(item, context) for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_render(item, context) for item in value)
    if isinstance(value, list):
        return [_render(item, context) for item in value]
    return value


def _render_string(value: str, context: collections.abc.Mapping[str, object]) -> str:
    """Render known ``$name`` tokens and leave unknown shell text intact."""

    def repl(match: re.Match[str]) -> str:
        if match.group("escaped") is not None:
            return "$"
        key = match.group("braced") or match.group("named")
        if key is None or key not in context:
            return match.group(0)
        return str(context[key])

    return _TOKEN_RE.sub(repl, value)
