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
    CommandScope,
    CommandSpec,
)

COMMAND_SPECS: dict[str, CommandSpec] = {
    "new-session": CommandSpec("new-session", "server"),
    "new-window": CommandSpec("new-window", "session"),
    "split-window": CommandSpec("split-window", "pane"),
    "break-pane": CommandSpec("break-pane", "pane"),
    "rename-window": CommandSpec("rename-window", "window"),
    "rename-session": CommandSpec("rename-session", "session"),
    "select-layout": CommandSpec("select-layout", "window"),
    "select-pane": CommandSpec("select-pane", "pane"),
    "select-window": CommandSpec("select-window", "window"),
    "send-keys": CommandSpec("send-keys", "pane"),
    "resize-pane": CommandSpec("resize-pane", "pane"),
    "set-option": CommandSpec("set-option", "server"),
    "set-environment": CommandSpec("set-environment", "session"),
    # Output commands cannot fold into a chain -- they need stdout immediately.
    "show-option": CommandSpec("show-option", "server", chainable=False),
    "capture-pane": CommandSpec("capture-pane", "pane", chainable=False),
    "display-message": CommandSpec("display-message", "server", chainable=False),
}
"""Known command metadata, including each command's ``chainable`` flag."""


COMMAND_TARGET_SCOPES: dict[str, frozenset[CommandScope]] = {
    "display-message": frozenset(("server", "session", "window", "pane")),
    "set-option": frozenset(("server", "session", "window", "pane")),
    "show-option": frozenset(("server", "session", "window", "pane")),
    "split-window": frozenset(("window", "pane")),
}
"""Commands whose accepted typed target scopes differ from their primary scope."""


class DeferredOutputUnavailable(RuntimeError):
    """Raised when a deferred command result is inspected before dispatch."""


class ChainabilityError(RuntimeError):
    """Raised when a non-chainable command is added to a chain."""


class CommandScopeError(RuntimeError):
    """Raised when a known command is bound to the wrong typed target scope."""


def is_chainable(name: str) -> bool:
    """Return whether a command may fold into a one-dispatch chain.

    Unknown commands fail closed. Commands in :data:`COMMAND_SPECS` use their
    declared ``chainable`` flag.

    Examples
    --------
    >>> is_chainable("rename-window")
    True
    >>> is_chainable("show-option")
    False
    >>> is_chainable("some-unknown-command")
    False
    """
    spec = COMMAND_SPECS.get(name)
    if spec is None:
        return False
    return spec.chainable


def ensure_chainable(name: str) -> None:
    """Raise unless ``name`` is a known command that may fold into a chain.

    Examples
    --------
    >>> ensure_chainable("rename-window")
    >>> ensure_chainable("show-option")  # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    libtmux...ChainabilityError: command 'show-option' is not chainable...
    >>> ensure_chainable("some-unknown-command")  # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    libtmux...ChainabilityError: unknown tmux command 'some-unknown-command'...
    """
    spec = COMMAND_SPECS.get(name)
    if spec is None:
        msg = (
            f"unknown tmux command {name!r} cannot be folded into "
            "a one-dispatch sequence"
        )
        raise ChainabilityError(msg)
    if not spec.chainable:
        msg = (
            f"command {name!r} is not chainable and cannot be "
            f"folded into a one-dispatch sequence"
        )
        raise ChainabilityError(msg)


def validate_command_scope(name: str, target_scope: CommandScope) -> None:
    """Raise if a known command cannot target ``target_scope``.

    Unknown commands are left to :func:`ensure_chainable`; raw
    :class:`CommandCall` targets are opaque and intentionally not parsed.

    Examples
    --------
    >>> validate_command_scope("rename-window", "window")
    >>> validate_command_scope("rename-window", "pane")  # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    libtmux...CommandScopeError: command 'rename-window' cannot target pane...
    >>> validate_command_scope("some-unknown-command", "pane")
    """
    spec = COMMAND_SPECS.get(name)
    if spec is None:
        return
    allowed = COMMAND_TARGET_SCOPES.get(name, frozenset((spec.scope,)))
    if target_scope not in allowed:
        msg = f"command {name!r} cannot target {target_scope} scope"
        raise CommandScopeError(msg)


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
