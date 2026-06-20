"""The chainability contract: what may fold into one dispatch.

A tmux command sequence is dispatched once, so a command may only join a chain
if its output is **not** consumed mid-chain. This module wires the two halves of
that rule together:

- *static* -- a :class:`~libtmux._experimental.chain.ir.CommandSpec`
  per command declares ``chainable`` (see :data:`COMMAND_SPECS` /
  :func:`is_chainable`). Output commands such as ``show-option`` are
  ``chainable=False``.
- *dynamic* -- :class:`DeferredCommandResult` stands in for a call folded into a
  chain. It raises :class:`DeferredOutputUnavailable` if its output is read
  before the chain runs, and resolves to the chain's merged result afterwards.
  :meth:`~libtmux._experimental.chain.plan.CommandPlan.run_deferred` (and its
  async counterpart) dispatch once and hand back resolved deferred results.

Note
----
This is an **experimental** API, not covered by the project's versioning policy.
It may change or be removed between any releases without notice.
"""

from __future__ import annotations

from dataclasses import dataclass

from libtmux._experimental.chain.ir import (
    CommandCall,
    CommandResultLike,
    CommandSpec,
)

COMMAND_SPECS: dict[str, CommandSpec] = {
    "new-window": CommandSpec("new-window", "session"),
    "split-window": CommandSpec("split-window", "pane"),
    "rename-window": CommandSpec("rename-window", "window"),
    "select-layout": CommandSpec("select-layout", "window"),
    "send-keys": CommandSpec("send-keys", "pane"),
    "resize-pane": CommandSpec("resize-pane", "pane"),
    "set-option": CommandSpec("set-option", "server"),
    # Output commands cannot fold into a chain -- they need stdout immediately.
    "show-option": CommandSpec("show-option", "server", chainable=False),
    "capture-pane": CommandSpec("capture-pane", "pane", chainable=False),
    "display-message": CommandSpec("display-message", "server", chainable=False),
}
"""Known command metadata, including each command's ``chainable`` flag."""


class DeferredOutputUnavailable(RuntimeError):
    """Raised when a deferred command result is inspected before dispatch."""


class ChainabilityError(RuntimeError):
    """Raised when a non-chainable command is added to a chain."""


def is_chainable(name: str) -> bool:
    """Return whether a command may fold into a one-dispatch chain.

    Unknown commands are treated as chainable; commands in :data:`COMMAND_SPECS`
    use their declared ``chainable`` flag.

    Examples
    --------
    >>> is_chainable("rename-window")
    True
    >>> is_chainable("show-option")
    False
    >>> is_chainable("some-unknown-command")
    True
    """
    spec = COMMAND_SPECS.get(name)
    if spec is None:
        return True
    return spec.chainable


@dataclass(frozen=True, slots=True)
class DeferredCommandResult:
    r"""A result handle for a call folded into a one-dispatch chain.

    A chained call has no result of its own until the chain runs: a ``\\;``
    sequence dispatches once and returns a single merged result. While
    ``result`` is ``None`` the handle is *unresolved* and reading output raises
    :class:`DeferredOutputUnavailable`; once resolved it hands back the chain's
    merged result -- the same result for every call in the chain, since a
    ``\\;`` dispatch is not separable per command.

    Examples
    --------
    Unresolved -- the value does not exist yet:

    >>> pending = DeferredCommandResult(CommandCall("rename-window", ("work",)))
    >>> try:
    ...     pending.stdout
    ... except DeferredOutputUnavailable:
    ...     print("unavailable until the chain runs")
    unavailable until the chain runs

    Resolved -- the chain's merged result is handed back:

    >>> class _Merged:
    ...     stdout, stderr, returncode = [], [], 0
    >>> done = pending.resolve(_Merged())
    >>> done.returncode
    0
    """

    call: CommandCall
    result: CommandResultLike | None = None

    def resolve(self, result: CommandResultLike) -> DeferredCommandResult:
        """Return a resolved copy bound to the chain's merged result.

        Examples
        --------
        >>> class _Merged:
        ...     stdout, stderr, returncode = ["ok"], [], 0
        >>> DeferredCommandResult(
        ...     CommandCall("rename-window", ("work",))
        ... ).resolve(_Merged()).stdout
        ['ok']
        """
        return DeferredCommandResult(self.call, result)

    @property
    def stdout(self) -> list[str]:
        """Chain stdout once resolved; otherwise reject."""
        if self.result is None:
            msg = "deferred command output is unavailable until the chain is run"
            raise DeferredOutputUnavailable(msg)
        return self.result.stdout

    @property
    def stderr(self) -> list[str]:
        """Chain stderr once resolved; otherwise reject."""
        if self.result is None:
            msg = "deferred command errors are unavailable until the chain is run"
            raise DeferredOutputUnavailable(msg)
        return self.result.stderr

    @property
    def returncode(self) -> int:
        """Chain return code once resolved; otherwise reject."""
        if self.result is None:
            msg = "deferred command status is unavailable until the chain is run"
            raise DeferredOutputUnavailable(msg)
        return self.result.returncode
