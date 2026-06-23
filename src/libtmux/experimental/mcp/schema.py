"""Best-effort JSON-schema generation for result types.

The single place pydantic is *optional*: if installed, its ``TypeAdapter`` gives a
precise schema; otherwise a small stdlib introspection produces a serviceable one.
Either way the projection core has no hard pydantic dependency.
"""

from __future__ import annotations

import collections.abc
import dataclasses
import typing as t

_SCALARS: dict[type, str] = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
}


def schema_for_type(tp: type) -> dict[str, t.Any]:
    """Return a JSON-schema dict for *tp* (pydantic if available, else stdlib).

    Examples
    --------
    >>> schema_for_type(int)
    {'type': 'integer'}
    >>> schema_for_type(str)
    {'type': 'string'}
    """
    import importlib

    try:
        type_adapter = importlib.import_module("pydantic").TypeAdapter
    except ImportError:
        return _introspect(tp)
    try:
        return dict(type_adapter(tp).json_schema())
    except Exception:  # pydantic rejects some dataclasses -- fall back to stdlib
        return _introspect(tp)


def _introspect(tp: t.Any) -> dict[str, t.Any]:
    """Render a coarse JSON schema by walking dataclass fields / generics."""
    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        try:
            hints = t.get_type_hints(tp)
        except Exception:
            hints = {}
        props: dict[str, t.Any] = {}
        required: list[str] = []
        for field in dataclasses.fields(tp):
            if field.name == "operation":  # back-reference to the source op, not output
                continue
            props[field.name] = _introspect(hints.get(field.name, str))
            if (
                field.default is dataclasses.MISSING
                and field.default_factory is dataclasses.MISSING
            ):
                required.append(field.name)
        schema: dict[str, t.Any] = {"type": "object", "properties": props}
        if required:
            schema["required"] = required
        return schema
    if tp in _SCALARS:
        return {"type": _SCALARS[tp]}
    origin = t.get_origin(tp)
    if origin in (list, tuple):
        args = t.get_args(tp)
        item = _introspect(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item}
    if origin in (dict, collections.abc.Mapping):
        return {"type": "object"}
    return {"type": "string"}
