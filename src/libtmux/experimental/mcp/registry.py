"""Generate :class:`~.descriptor.ToolDescriptor` values from the op registry.

One descriptor per registered operation ``kind``, derived by introspecting the
operation dataclass (fields + type hints + NumPy-docstring params) and its
``OpSpec`` metadata (scope/safety/effects/version gates). Zero MCP-framework
coupling: the result is plain data + a builder.
"""

from __future__ import annotations

import dataclasses
import typing as t

from libtmux.experimental.mcp.descriptor import ParamDescriptor, ToolDescriptor
from libtmux.experimental.mcp.schema import schema_for_type
from libtmux.experimental.ops import registry as ops_registry

if t.TYPE_CHECKING:
    from libtmux.experimental.ops.registry import OpSpec

_ANNOTATIONS: dict[str, dict[str, bool]] = {
    "readonly": {"readOnlyHint": True},
    "mutating": {"readOnlyHint": False},
    "destructive": {"readOnlyHint": False, "destructiveHint": True},
}
_SKIP_FIELDS = frozenset({"target", "src_target"})
_SCALAR_NAME = {"bool": "bool", "int": "int", "float": "float", "str": "str"}
_LIST_BASES = frozenset({"list", "tuple", "Sequence", "frozenset", "set"})
_DICT_BASES = frozenset({"dict", "Mapping", "MutableMapping"})


def _origin_of(annotation: t.Any) -> tuple[str, str | None]:
    """Map a field annotation to a ``(origin, item_origin)`` schema pair.

    Parses the annotation *string* (operations use ``from __future__ import
    annotations``, and their hints reference ``TYPE_CHECKING``-only names like
    ``Mapping`` that ``get_type_hints`` cannot resolve at runtime), so it never
    needs to import the annotated types.
    """
    text = (
        annotation
        if isinstance(annotation, str)
        else getattr(annotation, "__name__", str(annotation))
    )
    text = text.replace(" ", "")
    if "|" in text:
        members = [member for member in text.split("|") if member and member != "None"]
        text = members[0] if members else "str"
    base = text.split("[", 1)[0]
    if base in _LIST_BASES:
        inner = text[len(base) + 1 : -1] if "[" in text else ""
        item = inner.split("[", 1)[0].split(",", 1)[0] if inner else "str"
        return "list", _SCALAR_NAME.get(item, "str")
    if base in _DICT_BASES:
        return "dict", None
    return _SCALAR_NAME.get(base, "str"), None


def _docstring_params(doc: str | None) -> dict[str, str]:
    """Parse ``name : type`` entries from a NumPy docstring Parameters block."""
    if not doc:
        return {}
    out: dict[str, str] = {}
    in_params = False
    pending: str | None = None
    for raw in doc.splitlines():
        line = raw.rstrip()
        if line.strip() in {"Parameters", "Attributes"}:
            in_params = True
            continue
        if not in_params:
            continue
        if line.strip().startswith(("Returns", "Examples", "Notes", "Raises")):
            break
        if " : " in line and not line.startswith("        "):
            pending = line.split(" : ", 1)[0].strip()
        elif pending and line.startswith("    ") and line.strip():
            out.setdefault(pending, line.strip())
            pending = None
    return out


def _summary(doc: str | None) -> str:
    """Return the first non-empty docstring line."""
    for line in (doc or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


class OperationToolRegistry:
    """Build (and cache) a :class:`~.descriptor.ToolDescriptor` per operation.

    Examples
    --------
    >>> reg = OperationToolRegistry()
    >>> d = reg.descriptor("split_window")
    >>> d.name, d.scope, d.safety
    ('split_window', 'window', 'mutating')
    >>> d.params["horizontal"].origin
    'bool'
    >>> d.build(target="@1", horizontal=True).render()
    ('split-window', '-t', '@1', '-h', '-P', '-F', '#{pane_id}')
    >>> len(reg.descriptors()) == len(list(reg.kinds()))
    True
    """

    def __init__(self) -> None:
        self._cache: dict[str, ToolDescriptor] = {}

    def kinds(self) -> tuple[str, ...]:
        """Return every registered operation kind, sorted."""
        return ops_registry.kinds()

    def descriptor(self, kind: str) -> ToolDescriptor:
        """Return (building + caching) the descriptor for *kind*."""
        cached = self._cache.get(kind)
        if cached is not None:
            return cached
        built = self._build(ops_registry.get(kind))
        self._cache[kind] = built
        return built

    def descriptors(self) -> list[ToolDescriptor]:
        """Return a descriptor for every registered operation, sorted by name."""
        return [self.descriptor(spec.kind) for spec in ops_registry.select()]

    def _build(self, spec: OpSpec) -> ToolDescriptor:
        """Project one ``OpSpec`` into a tool descriptor."""
        return ToolDescriptor(
            name=spec.kind,
            title=spec.kind.replace("_", " ").title(),
            description=_summary(spec.operation_cls.__doc__),
            scope=spec.scope,
            safety=spec.safety,
            params=self._params(spec),
            result_type=spec.result_cls.__name__,
            result_schema=schema_for_type(spec.result_cls),
            annotations=_ANNOTATIONS.get(spec.safety, {}),
            tags=frozenset({spec.safety}),
            version_gates=dict(spec.flag_version_map),
            effects=dataclasses.asdict(spec.effects),
            operation_cls=spec.operation_cls,
        )

    def _params(self, spec: OpSpec) -> dict[str, ParamDescriptor]:
        """Extract typed parameter descriptors from the operation's fields."""
        operation_cls = spec.operation_cls
        docs = _docstring_params(operation_cls.__doc__)
        params: dict[str, ParamDescriptor] = {}
        for field in dataclasses.fields(operation_cls):
            if field.name in _SKIP_FIELDS:
                continue
            origin, item = _origin_of(field.type)
            params[field.name] = ParamDescriptor(
                name=field.name,
                origin=origin,
                item_origin=item,
                is_required=(
                    field.default is dataclasses.MISSING
                    and field.default_factory is dataclasses.MISSING
                ),
                description=docs.get(field.name),
                version_gate=spec.flag_version_map.get(field.name),
            )
        return params
