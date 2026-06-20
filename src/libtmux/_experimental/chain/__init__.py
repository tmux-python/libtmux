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

Note
----
This is an **experimental** API, not covered by the project's versioning policy.
It may change or be removed between any releases without notice.
"""

from __future__ import annotations

from libtmux._experimental.chain import _async as aio
from libtmux._experimental.chain._connection import (
    AsyncSessionPlanExecutor,
    SessionPlanExecutor,
    snapshot_from_session,
)
from libtmux._experimental.chain._resolve import (
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
    "ForwardHandle",
    "ForwardPlan",
    "NoCommandsResolved",
    "PaneQuery",
    "PaneRef",
    "PaneTarget",
    "PendingTarget",
    "PlanRunner",
    "Resolved",
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
