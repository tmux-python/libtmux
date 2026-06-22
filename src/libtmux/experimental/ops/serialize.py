"""Serialize operations and results to/from plain dicts.

Serialized payloads contain only stable, JSON-friendly data -- a ``kind``
discriminator, target descriptors, scalar fields, and captured output. They hold
no live :class:`~libtmux.Server`/:class:`~libtmux.Pane`, subprocess handles, or
event-loop objects, so an operation built in one process can be reconstructed in
another. Reconstruction goes through the registry, so only registered operations
can be revived (fail closed).
"""

from __future__ import annotations

import dataclasses
import typing as t

from libtmux.experimental.ops._types import (
    ClientName,
    IndexRef,
    NameRef,
    PaneId,
    SessionId,
    SlotRef,
    Special,
    WindowId,
)
from libtmux.experimental.ops.registry import registry

if t.TYPE_CHECKING:
    from collections.abc import Mapping

    from libtmux.experimental.ops._types import Target
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.results import Result

_TARGET_TYPES: dict[str, type] = {
    cls.__name__: cls
    for cls in (
        PaneId,
        WindowId,
        SessionId,
        ClientName,
        NameRef,
        IndexRef,
        Special,
        SlotRef,
    )
}


def target_to_dict(target: Target | None) -> dict[str, t.Any] | None:
    """Serialize a :data:`~._types.Target` to a tagged dict (or ``None``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> target_to_dict(PaneId("%1"))
    {'type': 'PaneId', 'value': '%1'}
    >>> target_to_dict(None) is None
    True
    """
    if target is None:
        return None
    return {"type": type(target).__name__, **dataclasses.asdict(target)}


def target_from_dict(data: Mapping[str, t.Any] | None) -> Target | None:
    """Reconstruct a :data:`~._types.Target` from :func:`target_to_dict` output.

    Examples
    --------
    >>> target_from_dict({"type": "PaneId", "value": "%1"})
    PaneId(value='%1')
    >>> target_from_dict(None) is None
    True
    """
    if data is None:
        return None
    cls = _TARGET_TYPES[data["type"]]
    fields = {key: value for key, value in data.items() if key != "type"}
    return t.cast("Target", cls(**fields))


def _jsonify(value: t.Any) -> t.Any:
    """Render a field value as JSON-friendly data."""
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


def operation_to_dict(operation: Operation[t.Any]) -> dict[str, t.Any]:
    """Serialize an operation to a plain dict.

    Examples
    --------
    >>> from libtmux.experimental.ops import SplitWindow
    >>> from libtmux.experimental.ops._types import PaneId
    >>> data = operation_to_dict(SplitWindow(target=PaneId("%1"), horizontal=True))
    >>> data["kind"], data["target"], data["horizontal"]
    ('split_window', {'type': 'PaneId', 'value': '%1'}, True)
    """
    data: dict[str, t.Any] = {"kind": operation.kind}
    for field in dataclasses.fields(operation):
        value = getattr(operation, field.name)
        if field.name in {"target", "src_target"}:
            data[field.name] = target_to_dict(value)
        else:
            data[field.name] = _jsonify(value)
    return data


def operation_from_dict(data: Mapping[str, t.Any]) -> Operation[t.Any]:
    """Reconstruct an operation from :func:`operation_to_dict` output.

    Examples
    --------
    >>> from libtmux.experimental.ops import SplitWindow
    >>> from libtmux.experimental.ops._types import PaneId
    >>> op = SplitWindow(target=PaneId("%1"), horizontal=True)
    >>> operation_from_dict(operation_to_dict(op)) == op
    True
    """
    operation_cls = registry.operation(data["kind"])
    kwargs: dict[str, t.Any] = {}
    for field in dataclasses.fields(operation_cls):
        if field.name not in data:
            continue
        if field.name in {"target", "src_target"}:
            kwargs[field.name] = target_from_dict(data[field.name])
        else:
            kwargs[field.name] = data[field.name]
    return operation_cls(**kwargs)


def _coerce_field(value: t.Any) -> t.Any:
    """Coerce a JSON list back into the tuple a result field expects."""
    if isinstance(value, list):
        return tuple(value)
    return value


def result_to_dict(result: Result) -> dict[str, t.Any]:
    """Serialize a result (and its operation) to a plain dict.

    Examples
    --------
    >>> from libtmux.experimental.ops import SplitWindow
    >>> from libtmux.experimental.ops._types import PaneId
    >>> r = SplitWindow(target=PaneId("%1")).build_result(returncode=0, stdout=("%2",))
    >>> data = result_to_dict(r)
    >>> data["status"], data["new_pane_id"]
    ('complete', '%2')
    """
    data: dict[str, t.Any] = {"operation": operation_to_dict(result.operation)}
    for field in dataclasses.fields(result):
        if field.name == "operation":
            continue
        data[field.name] = _jsonify(getattr(result, field.name))
    return data


def result_from_dict(data: Mapping[str, t.Any]) -> Result:
    """Reconstruct a result from :func:`result_to_dict` output.

    Examples
    --------
    >>> from libtmux.experimental.ops import SplitWindow
    >>> from libtmux.experimental.ops._types import PaneId
    >>> r = SplitWindow(target=PaneId("%1")).build_result(returncode=0, stdout=("%2",))
    >>> result_from_dict(result_to_dict(r)) == r
    True
    """
    operation = operation_from_dict(data["operation"])
    result_cls = type(operation).result_cls
    kwargs: dict[str, t.Any] = {"operation": operation}
    for field in dataclasses.fields(result_cls):
        if field.name == "operation" or field.name not in data:
            continue
        kwargs[field.name] = _coerce_field(data[field.name])
    return result_cls(**kwargs)


def bindings_to_dict(bindings: Mapping[int | tuple[int, str], str]) -> dict[str, str]:
    """Serialize plan bindings to a JSON-friendly ``str``-keyed dict.

    A plain slot key ``N`` becomes ``"N"``; a sub-ref key ``(N, part)`` becomes
    ``"N:part"`` (e.g. ``(0, "pane")`` -> ``"0:pane"``) so a forward-ref binding
    survives a JSON round-trip.

    Examples
    --------
    >>> bindings_to_dict({0: "$1", (0, "pane"): "%2"})
    {'0': '$1', '0:pane': '%2'}
    """
    out: dict[str, str] = {}
    for key, value in bindings.items():
        out[f"{key[0]}:{key[1]}" if isinstance(key, tuple) else str(key)] = value
    return out


def bindings_from_dict(data: Mapping[str, str]) -> dict[int | tuple[int, str], str]:
    """Reconstruct plan bindings from :func:`bindings_to_dict` output.

    Examples
    --------
    >>> bindings_from_dict({"0": "$1", "0:pane": "%2"}) == {0: "$1", (0, "pane"): "%2"}
    True
    """
    out: dict[int | tuple[int, str], str] = {}
    for key, value in data.items():
        if ":" in key:
            slot, part = key.split(":", 1)
            out[int(slot), part] = value
        else:
            out[int(key)] = value
    return out
