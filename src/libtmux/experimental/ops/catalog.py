"""A registry-driven operation catalog (the documentation data source).

:func:`catalog` walks the operation registry and emits one structured
:class:`CatalogEntry` per operation -- scope, version gates, effects, safety,
result type, and a one-line summary. This is the data a Sphinx ``tmuxop`` domain
directive renders into the operation reference, so the registry is the single
source of truth for both runtime *and* docs and the two cannot drift apart.
"""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops.registry import registry as default_registry

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Safety, Scope
    from libtmux.experimental.ops.registry import OperationRegistry


def _summary(doc: str | None) -> str:
    """Return the first non-empty line of a docstring."""
    if not doc:
        return ""
    for line in doc.strip().splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


@dataclass(frozen=True)
class CatalogEntry:
    """One operation's catalog record, derived from its registry spec."""

    kind: str
    command: str
    scope: Scope
    safety: Safety
    primitive: bool
    chainable: bool
    result_type: str
    min_version: str | None
    flag_version_gates: dict[str, str]
    effects: dict[str, t.Any]
    summary: str


def catalog(registry: OperationRegistry | None = None) -> list[CatalogEntry]:
    """Build catalog entries for every registered operation, sorted by kind.

    Parameters
    ----------
    registry : OperationRegistry or None
        The registry to read; defaults to the process-wide registry.

    Returns
    -------
    list[CatalogEntry]

    Examples
    --------
    >>> from libtmux.experimental.ops import catalog
    >>> entries = catalog()
    >>> [entry.kind for entry in entries]
    ['break_pane', 'capture_pane', 'clear_history', 'detach_client',
    'display_message', 'has_session', 'join_pane', 'kill_pane', 'kill_server',
    'kill_session', 'kill_window', 'last_pane', 'last_window', 'link_window',
    'list_clients', 'list_panes', 'list_sessions', 'list_windows', 'move_pane',
    'move_window', 'new_session', 'new_window', 'next_window', 'pipe_pane',
    'previous_window', 'refresh_client', 'rename_session', 'rename_window',
    'resize_pane', 'resize_window', 'respawn_pane', 'respawn_window',
    'rotate_window', 'run_shell', 'select_layout', 'select_pane', 'select_window',
    'send_keys', 'set_environment', 'set_hook', 'set_option', 'set_window_option',
    'show_options', 'source_file', 'split_window', 'start_server',
    'suspend_client', 'swap_pane', 'swap_window', 'switch_client', 'unlink_window']
    >>> capture = next(entry for entry in entries if entry.kind == "capture_pane")
    >>> capture.scope, capture.safety, capture.result_type
    ('pane', 'readonly', 'CapturePaneResult')
    >>> capture.flag_version_gates["trim_trailing"]
    '3.4'
    """
    reg = registry if registry is not None else default_registry
    return [
        CatalogEntry(
            kind=spec.kind,
            command=spec.command,
            scope=spec.scope,
            safety=spec.safety,
            primitive=spec.primitive,
            chainable=spec.chainable,
            result_type=spec.result_cls.__name__,
            min_version=spec.min_version,
            flag_version_gates=dict(spec.flag_version_map),
            effects=dataclasses.asdict(spec.effects),
            summary=_summary(spec.operation_cls.__doc__),
        )
        for spec in reg.select()
    ]
