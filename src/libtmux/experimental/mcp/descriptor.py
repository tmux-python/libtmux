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
    """One typed tool parameter, projected from an operation dataclass field.

    Attributes
    ----------
    name : str
        Parameter name accepted by the tool.
    origin : str
        Python annotation origin used to select the JSON Schema type.
    is_required : bool
        Whether callers must provide the parameter.
    item_origin : str or None
        Python annotation origin used for list items, when applicable.
    description : str or None
        Human-readable parameter description.
    """

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

    Attributes
    ----------
    name : str
        Operation kind used as the tool name.
    title : str
        Short human-readable tool title.
    description : str
        Full tool description exposed to agents.
    scope : str
        tmux object scope targeted by the operation.
    safety : str
        Safety tier used to derive annotations and tags.
    params : Mapping[str, ParamDescriptor]
        Typed parameter descriptors, excluding resolved targets.
    result_type : str
        Name of the tool's result class.
    result_schema : Mapping[str, Any]
        JSON schema for the result payload.
    annotations : Mapping[str, bool]
        MCP annotations derived from safety, effects, and kill-capable variants.
    tags : frozenset[str]
        Tool tags derived from the safety tier.
    operation_cls : type[Operation[Any]]
        Operation class instantiated by :meth:`build`.
    min_version : str or None
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
        for name in ("target", "src_target"):
            if name in fields:
                fields[name] = resolve_target(fields[name])
        return self.operation_cls(**fields)
