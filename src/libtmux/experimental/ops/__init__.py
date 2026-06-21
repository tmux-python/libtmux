"""Inert, typed tmux operation values.

This package is the pure source of truth for tmux commands: each
:class:`~.operation.Operation` renders a tmux argv, carries its result type and
metadata, and adapts raw output into a typed :class:`~.results.Result` -- all
without a live tmux server. Engines (:mod:`libtmux.experimental.engines`)
execute operations; :func:`run` / :func:`arun` bridge the two.

Everything here is experimental and not covered by the versioning policy.

Examples
--------
>>> from libtmux.experimental.ops import SplitWindow, run
>>> from libtmux.experimental.ops._types import PaneId
>>> from libtmux.experimental.engines import CommandResult
>>> SplitWindow(target=PaneId("%1"), horizontal=True).render()
('split-window', '-t', '%1', '-h', '-P', '-F', '#{pane_id}')
"""

from __future__ import annotations

from libtmux.experimental.ops._chain import OpChain
from libtmux.experimental.ops._ops import (
    CapturePane,
    DetachClient,
    KillPane,
    KillSession,
    KillWindow,
    ListPanes,
    ListSessions,
    ListWindows,
    NewSession,
    NewWindow,
    RefreshClient,
    RenameSession,
    RenameWindow,
    SelectLayout,
    SendKeys,
    SplitWindow,
    SwitchClient,
)
from libtmux.experimental.ops._types import (
    ClientName,
    Effects,
    IndexRef,
    NameRef,
    PaneId,
    Safety,
    Scope,
    SessionId,
    SlotRef,
    Special,
    Status,
    Target,
    WindowId,
    render_target,
)
from libtmux.experimental.ops.catalog import CatalogEntry, catalog
from libtmux.experimental.ops.exc import (
    DuplicateOperation,
    OperationError,
    TmuxCommandError,
    UnknownOperation,
    VersionUnsupported,
)
from libtmux.experimental.ops.execute import arun, run
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.plan import LazyPlan, PlanResult
from libtmux.experimental.ops.registry import (
    OperationRegistry,
    OpSpec,
    register,
    registry,
)
from libtmux.experimental.ops.results import (
    AckResult,
    CapturePaneResult,
    CreateResult,
    ListPanesResult,
    ListSessionsResult,
    ListWindowsResult,
    Result,
    SplitWindowResult,
    status_for,
)
from libtmux.experimental.ops.serialize import (
    operation_from_dict,
    operation_to_dict,
    result_from_dict,
    result_to_dict,
    target_from_dict,
    target_to_dict,
)

__all__ = (
    "AckResult",
    "CapturePane",
    "CapturePaneResult",
    "CatalogEntry",
    "ClientName",
    "CreateResult",
    "DetachClient",
    "DuplicateOperation",
    "Effects",
    "IndexRef",
    "KillPane",
    "KillSession",
    "KillWindow",
    "LazyPlan",
    "ListPanes",
    "ListPanesResult",
    "ListSessions",
    "ListSessionsResult",
    "ListWindows",
    "ListWindowsResult",
    "NameRef",
    "NewSession",
    "NewWindow",
    "OpChain",
    "OpSpec",
    "Operation",
    "OperationError",
    "OperationRegistry",
    "PaneId",
    "PlanResult",
    "RefreshClient",
    "RenameSession",
    "RenameWindow",
    "Result",
    "Safety",
    "Scope",
    "SelectLayout",
    "SendKeys",
    "SessionId",
    "SlotRef",
    "Special",
    "SplitWindow",
    "SplitWindowResult",
    "Status",
    "SwitchClient",
    "Target",
    "TmuxCommandError",
    "UnknownOperation",
    "VersionUnsupported",
    "WindowId",
    "arun",
    "catalog",
    "operation_from_dict",
    "operation_to_dict",
    "register",
    "registry",
    "render_target",
    "result_from_dict",
    "result_to_dict",
    "run",
    "status_for",
    "target_from_dict",
    "target_to_dict",
)
