"""Typed primitives shared across :mod:`libtmux.experimental.ops`.

These are the small, inert vocabulary types the operation substrate is built
from: the tmux object :data:`Scope`, the :data:`Safety` tier and execution
:data:`Status` enumerations, the :class:`Effects` descriptor, and the closed
:data:`Target` sum that types a ``-t`` target so an illegal target is a type
error rather than a runtime surprise.

Everything here is pure: no tmux server is required to construct, render, or
compare any of these values.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

Scope: t.TypeAlias = t.Literal["server", "session", "window", "pane", "client"]
"""The tmux object scope an operation targets.

``client`` is a view into a live attachment rather than part of the ownership
chain, but it still has operation scope because tmux exposes client-scoped
commands (``detach-client``, ``switch-client``).
"""

Safety: t.TypeAlias = t.Literal["readonly", "mutating", "destructive"]
"""Coarse safety tier, mirroring the MCP tool-annotation vocabulary.

``readonly`` reads state, ``mutating`` changes it reversibly, ``destructive``
removes objects (``kill-session``, ``kill-window``).
"""

Status: t.TypeAlias = t.Literal["complete", "failed", "skipped", "unknown"]
"""Execution status of a result.

``complete``
    The command ran and tmux reported success.
``failed``
    The command ran and tmux reported an error.
``skipped``
    The operation was never dispatched (e.g. an earlier command in a chain
    failed, or a lazy plan was inspected but not executed).
``unknown``
    The outcome could not be determined (e.g. a control-mode timeout).
"""


@dataclass(frozen=True)
class Effects:
    """Declarative description of what an operation does to tmux state.

    Carrying effects as typed data (rather than a hand-maintained table in a
    downstream consumer) lets MCP annotations and safety tiers derive directly
    from the operation.

    Parameters
    ----------
    read_only : bool
        The operation does not change tmux state.
    destructive : bool
        The operation removes an object.
    idempotent : bool
        Re-running the operation has the same effect as running it once.
    creates : Scope or None
        The scope of the object the operation creates, if any (e.g.
        ``split-window`` creates a ``pane``).
    writes_input : bool
        The operation sends input into a pane (e.g. ``send-keys``).
    reads_output : bool
        The operation captures output from a pane (e.g. ``capture-pane``).
    mutates_layout : bool
        The operation rearranges panes/windows (e.g. ``select-layout``).

    Examples
    --------
    >>> Effects(read_only=True, idempotent=True)
    Effects(read_only=True, destructive=False, idempotent=True, creates=None,
    writes_input=False, reads_output=False, mutates_layout=False)
    >>> Effects(creates="pane").creates
    'pane'
    """

    read_only: bool = False
    destructive: bool = False
    idempotent: bool = False
    creates: Scope | None = None
    writes_input: bool = False
    reads_output: bool = False
    mutates_layout: bool = False


@dataclass(frozen=True, slots=True)
class PaneId:
    """A concrete tmux pane id, ``%N``.

    Examples
    --------
    >>> PaneId("%1").render()
    '%1'
    >>> PaneId("1")
    Traceback (most recent call last):
    ...
    ValueError: PaneId must start with '%', got '1'
    """

    value: str

    def __post_init__(self) -> None:
        """Validate the id sigil (fail closed)."""
        if not self.value.startswith("%"):
            msg = f"PaneId must start with '%', got {self.value!r}"
            raise ValueError(msg)

    def render(self) -> str:
        """Render as a tmux ``-t`` target token."""
        return self.value


@dataclass(frozen=True, slots=True)
class WindowId:
    """A concrete tmux window id, ``@N``.

    Examples
    --------
    >>> WindowId("@2").render()
    '@2'
    """

    value: str

    def __post_init__(self) -> None:
        """Validate the id sigil (fail closed)."""
        if not self.value.startswith("@"):
            msg = f"WindowId must start with '@', got {self.value!r}"
            raise ValueError(msg)

    def render(self) -> str:
        """Render as a tmux ``-t`` target token."""
        return self.value


@dataclass(frozen=True, slots=True)
class SessionId:
    """A concrete tmux session id, ``$N``.

    Examples
    --------
    >>> SessionId("$0").render()
    '$0'
    """

    value: str

    def __post_init__(self) -> None:
        """Validate the id sigil (fail closed)."""
        if not self.value.startswith("$"):
            msg = f"SessionId must start with '$', got {self.value!r}"
            raise ValueError(msg)

    def render(self) -> str:
        """Render as a tmux ``-t`` target token."""
        return self.value


@dataclass(frozen=True, slots=True)
class ClientName:
    """A tmux client name (a tty path such as ``/dev/pts/3``).

    Examples
    --------
    >>> ClientName("/dev/pts/3").render()
    '/dev/pts/3'
    """

    value: str

    def __post_init__(self) -> None:
        """Reject an empty client name (fail closed)."""
        if not self.value:
            msg = "ClientName must be a non-empty string"
            raise ValueError(msg)

    def render(self) -> str:
        """Render as a tmux ``-t`` target token."""
        return self.value


@dataclass(frozen=True, slots=True)
class NameRef:
    """A target addressed by name, optionally requiring an exact match.

    tmux matches names as a prefix by default; prefixing with ``=`` forces an
    exact match.

    Examples
    --------
    >>> NameRef("work").render()
    'work'
    >>> NameRef("work", exact=True).render()
    '=work'
    """

    name: str
    exact: bool = False

    def __post_init__(self) -> None:
        """Reject an empty name (fail closed)."""
        if not self.name:
            msg = "NameRef name must be a non-empty string"
            raise ValueError(msg)

    def render(self) -> str:
        """Render as a tmux ``-t`` target token."""
        return f"={self.name}" if self.exact else self.name


@dataclass(frozen=True, slots=True)
class IndexRef:
    """A target addressed by integer index (window or session index).

    Examples
    --------
    >>> IndexRef(0).render()
    '0'
    >>> IndexRef(2, parent="$1").render()
    '$1:2'
    """

    index: int
    parent: str | None = None

    def render(self) -> str:
        """Render as a tmux ``-t`` target token, qualified by parent if set."""
        if self.parent is not None:
            return f"{self.parent}:{self.index}"
        return str(self.index)


@dataclass(frozen=True, slots=True)
class Special:
    """A tmux special target token, e.g. ``{marked}``, ``{last}``, ``{up-of}``.

    The token vocabulary comes from tmux's target-resolution tables (see
    ``cmd-find.c``). This wrapper keeps a symbolic target distinct from a
    concrete id at the type level.

    Examples
    --------
    >>> Special("{marked}").render()
    '{marked}'
    >>> Special("last").render()
    'last'
    """

    token: str

    def __post_init__(self) -> None:
        """Reject an empty token (fail closed)."""
        if not self.token:
            msg = "Special token must be a non-empty string"
            raise ValueError(msg)

    def render(self) -> str:
        """Render as a tmux ``-t`` target token."""
        return self.token


@dataclass(frozen=True, slots=True)
class SlotRef:
    """A deferred target: "the id of forward slot N", filled at resolve time.

    Carried by an operation built against an object that does not exist yet in
    a multi-operation plan. A resolver replaces it with the captured concrete
    id plus ``suffix`` before the operation renders; rendering an unresolved
    :class:`SlotRef` is a planner bug and raises (see
    :meth:`libtmux.experimental.ops.operation.Operation.render`). ``suffix``
    lets a command needing a qualified target -- e.g. ``new-window -t $N:`` --
    reuse a plain captured ``$N``.

    Examples
    --------
    >>> SlotRef(0)
    SlotRef(slot=0, suffix='')
    >>> SlotRef(0, ":")
    SlotRef(slot=0, suffix=':')
    """

    slot: int
    suffix: str = ""

    def render(self) -> str:
        """Raise -- an unresolved deferred ref cannot be rendered."""
        msg = "cannot render an unresolved SlotRef; resolve the plan first"
        raise TypeError(msg)


Target: t.TypeAlias = (
    "PaneId | WindowId | SessionId | ClientName | NameRef | IndexRef "
    "| Special | SlotRef"
)
"""The closed sum of everything that can appear as an operation ``-t`` target."""


def render_target(target: Target | None) -> str | None:
    """Render any :data:`Target` to its tmux token, or ``None`` for no target.

    Parameters
    ----------
    target : Target or None
        The typed target to render.

    Returns
    -------
    str or None
        The ``-t`` token string, or ``None`` when there is no target.

    Examples
    --------
    >>> render_target(PaneId("%1"))
    '%1'
    >>> render_target(None) is None
    True
    """
    if target is None:
        return None
    return target.render()
