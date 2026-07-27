"""Resolve agent-supplied targets to typed :data:`~..ops._types.Target` values.

The string/dict boundary between an MCP client (which speaks JSON) and the typed
operation spine. Fail-closed: an unrecognised target raises rather than guessing.
"""

from __future__ import annotations

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
from libtmux.experimental.ops.serialize import target_from_dict

if t.TYPE_CHECKING:
    from collections.abc import Mapping

    from libtmux.experimental.ops._types import Target

_TARGET_CLASSES = (
    PaneId,
    WindowId,
    SessionId,
    ClientName,
    NameRef,
    IndexRef,
    Special,
    SlotRef,
)


def resolve_target(value: str | Mapping[str, t.Any] | Target | None) -> Target | None:
    """Coerce a target spec into a typed :data:`~..ops._types.Target`.

    Accepts an already-typed target (passthrough), the tagged dict form from
    :func:`~..ops.serialize.target_to_dict`, ``None``, or a string using tmux
    sigils: ``%``→pane, ``@``→window, ``$``→session, ``/``→client, ``{...}``→
    special, ``=name``→exact name, otherwise a prefix-matched name.

    Examples
    --------
    >>> resolve_target("%1")
    PaneId(value='%1')
    >>> resolve_target("@2")
    WindowId(value='@2')
    >>> resolve_target("work")
    NameRef(name='work', exact=False)
    >>> resolve_target({"type": "PaneId", "value": "%3"})
    PaneId(value='%3')
    >>> resolve_target(None) is None
    True
    """
    if value is None:
        return None
    if isinstance(value, _TARGET_CLASSES):
        return value
    if isinstance(value, str):
        return _from_string(value)
    return target_from_dict(value)


def _from_string(value: str) -> Target:
    """Parse a target string by its tmux sigil (fail-closed on empty)."""
    if not value:
        msg = "empty target string"
        raise ValueError(msg)
    if value.startswith("%"):
        return PaneId(value)
    if value.startswith("@"):
        return WindowId(value)
    if value.startswith("$"):
        return SessionId(value)
    if value.startswith("/"):
        return ClientName(value)
    if value.startswith("{") and value.endswith("}"):
        return Special(value)
    if value.startswith("="):
        return NameRef(value[1:], exact=True)
    return NameRef(value)
