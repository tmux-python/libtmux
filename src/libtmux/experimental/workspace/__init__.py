"""Declarative workspace: a structural object language over the Core ops.

The *Declarative* tier (à la SQLAlchemy Declarative on Core). Declare a workspace
shape with :class:`~.ir.Workspace` / :class:`~.ir.Window` / :class:`~.ir.Pane`;
:func:`~.analyzer.analyze` builds that tree from a tmuxp-style YAML/dict (and
:meth:`~.ir.Workspace.to_dict` is its inverse); the compiler lowers it to a Core
:class:`~libtmux.experimental.ops.plan.LazyPlan`; the runner executes it over any
engine, sync or async; :func:`~.confirm.confirm` verifies the live result.

Everything here is experimental and outside the versioning policy.

Examples
--------
>>> from libtmux.experimental.engines import ConcreteEngine
>>> ws = analyze({
...     "session_name": "dev",
...     "windows": [{"window_name": "editor", "panes": ["vim", "pytest -q"]}],
... })
>>> ws.build(ConcreteEngine(), preflight=False).ok
True
"""

from __future__ import annotations

from libtmux.experimental.workspace.analyzer import analyze
from libtmux.experimental.workspace.compiler import (
    Compiled,
    HostStep,
    WorkspaceCompileError,
    compile_full,
    compile_workspace,
)
from libtmux.experimental.workspace.confirm import ConfirmReport, confirm
from libtmux.experimental.workspace.events import (
    BuildEvent,
    PaneCreated,
    SessionCreated,
    WindowCreated,
    WorkspaceBuilt,
)
from libtmux.experimental.workspace.ir import (
    Command,
    Float,
    FloatingPane,
    Pane,
    Window,
    Workspace,
)
from libtmux.experimental.workspace.runner import abuild_workspace, build_workspace

__all__ = (
    "BuildEvent",
    "Command",
    "Compiled",
    "ConfirmReport",
    "Float",
    "FloatingPane",
    "HostStep",
    "Pane",
    "PaneCreated",
    "SessionCreated",
    "Window",
    "WindowCreated",
    "Workspace",
    "WorkspaceBuilt",
    "WorkspaceCompileError",
    "abuild_workspace",
    "analyze",
    "build_workspace",
    "compile_full",
    "compile_workspace",
    "confirm",
)
