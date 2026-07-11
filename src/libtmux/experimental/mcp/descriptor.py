"""Framework-agnostic typed tool descriptors.

A :class:`ToolDescriptor` is the projection of one tmux :class:`~..ops.operation.
Operation` into a tool: its name, typed parameters, safety annotations, result
schema, and a :meth:`~ToolDescriptor.build` factory that turns agent-supplied
params into a typed operation (resolving targets). It holds **no** MCP framework
object -- a thin adapter (fastmcp, click, …) binds it at runtime.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.mcp.target_resolver import resolve_target

if t.TYPE_CHECKING:
    from collections.abc import Mapping

    from libtmux.experimental.ops.operation import Operation

_JSON_TYPES = {
    "int": "integer",
    "float": "number",
    "str": "string",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
}


@dataclass(frozen=True, slots=True)
class ParamDescriptor:
    """One typed tool parameter, projected from an operation dataclass field."""

    name: str
    origin: str
    is_required: bool = True
    item_origin: str | None = None
    description: str | None = None

    def to_json_schema(self) -> dict[str, t.Any]:
        """Render this parameter as a JSON-schema fragment.

        Examples
        --------
        >>> p = ParamDescriptor("horizontal", "bool", description="split L/R")
        >>> p.to_json_schema()
        {'type': 'boolean', 'description': 'split L/R'}
        """
        schema: dict[str, t.Any] = {"type": _JSON_TYPES.get(self.origin, "string")}
        if self.origin == "list":
            schema["items"] = {
                "type": _JSON_TYPES.get(self.item_origin or "str", "string")
            }
        if self.description:
            schema["description"] = self.description
        return schema


@dataclass(frozen=True)
class ToolDescriptor:
    """A typed tool projected from one operation -- metadata plus a builder.

    Parameters
    ----------
    name, title, description
        Identity and human text (``name`` is the operation ``kind``).
    scope, safety
        tmux object scope and the safety tier (drives annotations/tags).
    params
        Typed parameter descriptors (target/src_target handled by :meth:`build`).
    result_type, result_schema
        The result class name and a JSON schema for its payload.
    annotations, tags
        MCP-style hints derived from the safety tier.
    operation_cls
        The operation class :meth:`build` instantiates.
    min_version
        Minimum tmux version the whole operation requires, if any (surfaced in
        the tool description so agents see the gate before dispatch).
    """

    name: str
    title: str
    description: str
    scope: str
    safety: str
    params: Mapping[str, ParamDescriptor]
    result_type: str
    result_schema: Mapping[str, t.Any]
    annotations: Mapping[str, bool]
    tags: frozenset[str]
    operation_cls: type[Operation[t.Any]]
    min_version: str | None = None

    def input_schema(self) -> dict[str, t.Any]:
        """Render the JSON schema for this tool's input object."""
        props = {name: param.to_json_schema() for name, param in self.params.items()}
        required = [name for name, param in self.params.items() if param.is_required]
        schema: dict[str, t.Any] = {"type": "object", "properties": props}
        if required:
            schema["required"] = required
        return schema

    def build(self, **kwargs: t.Any) -> Operation[t.Any]:
        """Construct the typed operation from agent params, resolving targets.

        ``target`` / ``src_target`` accept the polymorphic forms
        :func:`~.target_resolver.resolve_target` understands; the rest are passed
        through as operation fields (an unknown field fails closed via
        ``TypeError``).
        """
        fields = dict(kwargs)
        target = resolve_target(fields.pop("target", None))
        src_target = resolve_target(fields.pop("src_target", None))
        return self.operation_cls(target=target, src_target=src_target, **fields)
