r"""Typed, chainable tmux command sequences (experimental).

This package promotes the converged design from the ``chainable-commands``
research into a typed, documented API. It lets callers author an ordered
sequence of tmux commands that compiles to **one** native ``tmux ... \\; ...``
invocation and dispatches once, instead of issuing one subprocess per command.

The layers build on each other:

- :mod:`~libtmux._experimental.chain.ir` -- the immutable argv
  intermediate representation (``CommandCall``, ``CommandChain``).
- :mod:`~libtmux._experimental.chain.plan` -- typed, target-safe
  deferred query-command plans (``panes()``, ``CommandPlan``).
- :mod:`~libtmux._experimental.chain._async` -- an async facade over
  the same engine, exposed publicly as ``aio`` (``aio.panes()``), preserving
  one dispatch per plan.
- :mod:`~libtmux._experimental.chain._connection` -- live-tmux
  connection helpers (``snapshot_from_session``, ``SessionPlanExecutor``,
  ``AsyncSessionPlanExecutor``).
- :mod:`~libtmux._experimental.chain.chain` -- the chainability
  contract that decides which commands may fold into one dispatch
  (``CommandSpec.chainable`` + ``DeferredCommandResult``).

Forward references come in two shapes; pick by whether the handles are
independent:

- A **linear chain** -- ``PaneRef.split().split().do(...)`` in
  :mod:`~libtmux._experimental.chain.plan`. Each step creates the object the next
  step builds on (split a pane, then split *that* pane). Because tmux keeps the
  freshly-created object active, the whole chain addresses it with no ``-t`` and
  folds into **one** ``\\;`` invocation (``to_chain()`` / ``run()``). Use it when
  the forward objects form a single line of descent.
- A **multi-handle plan** -- ``ForwardPlan``. Hands out
  **independent** handles (two splits off one pane, two windows in a new
  session) and resolves them over the minimum number of dispatches, capturing each
  new id with ``-P -F`` and substituting it downstream. Use it when you hold more
  than one forward object at once, or need a new id back
  (``Resolved.bindings`` / ``Resolved.pane(...)``).

A lone-pane ``ForwardPlan`` still folds to one dispatch (via the marked register),
so the two shapes overlap only there; reach for the linear chain for a pure line
of splits and ``ForwardPlan`` the moment the handles fan out.

Note
----
This is an **experimental** API, not covered by the project's versioning policy.
It may change or be removed between any releases without notice. A ``\\;``
sequence returns one merged result, so per-command output is not separable; reach
for individual typed calls (or ``run_deferred``) when you need a command's own
output.
"""

from __future__ import annotations

from libtmux._experimental.chain import _async as aio
from libtmux._experimental.chain._connection import (
    AsyncServerPlanRunner,
    AsyncSessionPlanExecutor,
    ServerPlanRunner,
    SessionPlanExecutor,
    snapshot_from_session,
)
from libtmux._experimental.chain._resolve import (
    ForwardDispatchError,
    ForwardHandle,
    ForwardPlan,
    Resolved,
)
from libtmux._experimental.chain.chain import (
    ChainabilityError,
    DeferredCommandResult,
    DeferredOutputUnavailable,
    is_chainable,
)
from libtmux._experimental.chain.ir import (
    Arg,
    CommandCall,
    CommandChain,
    CommandResultLike,
    CommandRunner,
    CommandScope,
    CommandSpec,
)
from libtmux._experimental.chain.plan import (
    CommandPlan,
    CommandValue,
    ForwardDataUnavailable,
    NoCommandsResolved,
    PaneQuery,
    PaneRef,
    PaneTarget,
    PendingTarget,
    PlanRunner,
    SessionRef,
    SessionTarget,
    TmuxSnapshot,
    WindowRef,
    WindowTarget,
    new_session,
    panes,
)

__all__ = [
    "Arg",
    "AsyncServerPlanRunner",
    "AsyncSessionPlanExecutor",
    "ChainabilityError",
    "CommandCall",
    "CommandChain",
    "CommandPlan",
    "CommandResultLike",
    "CommandRunner",
    "CommandScope",
    "CommandSpec",
    "CommandValue",
    "DeferredCommandResult",
    "DeferredOutputUnavailable",
    "ForwardDataUnavailable",
    "ForwardDispatchError",
    "ForwardHandle",
    "ForwardPlan",
    "NoCommandsResolved",
    "PaneQuery",
    "PaneRef",
    "PaneTarget",
    "PendingTarget",
    "PlanRunner",
    "Resolved",
    "ServerPlanRunner",
    "SessionPlanExecutor",
    "SessionRef",
    "SessionTarget",
    "TmuxSnapshot",
    "WindowRef",
    "WindowTarget",
    "aio",
    "is_chainable",
    "new_session",
    "panes",
    "snapshot_from_session",
]
