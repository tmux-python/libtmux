"""Safety tiers for the MCP tool surface.

A small, dependency-light core: the three safety-tier tags every tool is
registered under, the ``LIBTMUX_SAFETY`` resolver, and the expected-error type
the middleware demotes to ``WARNING``. Imported only from the fastmcp edge (the
adapter wiring and the middleware), so it stays cycle-free -- fastmcp + logging
only, never the framework-agnostic core.
"""

from __future__ import annotations

import logging
import typing as t

from fastmcp.exceptions import ToolError

from libtmux.experimental.mcp._policy import operation_safety

if t.TYPE_CHECKING:
    from collections.abc import Iterable

    from libtmux.experimental.ops.operation import Operation

logger = logging.getLogger(__name__)

#: Safety-tier tags -- the string every tool is registered under.
TAG_READONLY = "readonly"
TAG_MUTATING = "mutating"
TAG_DESTRUCTIVE = "destructive"

#: The recognized ``LIBTMUX_SAFETY`` values.
VALID_SAFETY_LEVELS: frozenset[str] = frozenset(
    {TAG_READONLY, TAG_MUTATING, TAG_DESTRUCTIVE},
)

#: Tier ordering: a tool at level N is allowed when ``N <= the server's max``.
_TIER_LEVELS: dict[str, int] = {
    TAG_READONLY: 0,
    TAG_MUTATING: 1,
    TAG_DESTRUCTIVE: 2,
}


def resolve_safety_level(value: str | None) -> str:
    """Return the effective safety tier for a ``LIBTMUX_SAFETY`` value.

    Unset defaults to ``"mutating"`` (mutating tools visible, destructive
    hidden); a recognized value is honored verbatim; anything else fails *safe*
    to ``"readonly"`` with a warning.

    Examples
    --------
    >>> resolve_safety_level(None)
    'mutating'
    >>> resolve_safety_level("destructive")
    'destructive'
    >>> resolve_safety_level("bogus")
    'readonly'
    """
    if value is None:
        return TAG_MUTATING
    if value in VALID_SAFETY_LEVELS:
        return value
    logger.warning(
        "invalid LIBTMUX_SAFETY=%r, falling back to %s",
        value,
        TAG_READONLY,
    )
    return TAG_READONLY


def safety_allows(required: str, maximum: str) -> bool:
    """Return whether *maximum* permits an action at *required*.

    Unknown values fail closed to the read-only level.

    Examples
    --------
    >>> safety_allows("mutating", "mutating")
    True
    >>> safety_allows("destructive", "mutating")
    False
    >>> safety_allows("readonly", "bogus")
    True
    """
    return _TIER_LEVELS.get(required, 1) <= _TIER_LEVELS.get(maximum, 0)


def require_safety(required: str, maximum: str, *, subject: str) -> None:
    """Raise an agent-correctable error when *subject* exceeds *maximum*.

    Examples
    --------
    >>> require_safety("readonly", "mutating", subject="query")
    >>> require_safety("destructive", "mutating", subject="kill_session")
    Traceback (most recent call last):
    ...
    libtmux.experimental.mcp._safety.ExpectedToolError: kill_session requires
    destructive safety; current level is mutating
    """
    if safety_allows(required, maximum):
        return
    message = f"{subject} requires {required} safety; current level is {maximum}"
    suggestion = f"Set LIBTMUX_SAFETY={required} only if this action is intended."
    raise ExpectedToolError(
        message,
        suggestion=suggestion,
    )


def require_operation_safety(
    operation: Operation[t.Any],
    maximum: str,
    *,
    index: int | None = None,
) -> None:
    """Require the effective safety tier of one operation payload.

    Examples
    --------
    >>> from libtmux.experimental.ops import UnlinkWindow
    >>> require_operation_safety(UnlinkWindow(kill=False), "mutating")
    >>> require_operation_safety(UnlinkWindow(kill=True), "mutating")
    Traceback (most recent call last):
    ...
    libtmux.experimental.mcp._safety.ExpectedToolError: operation
    'unlink_window' requires destructive safety; current level is mutating
    """
    location = "" if index is None else f" at plan index {index}"
    require_safety(
        operation_safety(operation),
        maximum,
        subject=f"operation {operation.kind!r}{location}",
    )


def require_operations_safety(
    operations: Iterable[Operation[t.Any]],
    maximum: str,
) -> None:
    """Require every concrete operation payload to fit *maximum*.

    Examples
    --------
    >>> from libtmux.experimental.ops import NewSession, SendKeys
    >>> require_operations_safety((NewSession(), SendKeys(keys="pwd")), "mutating")
    """
    for index, operation in enumerate(operations):
        require_operation_safety(operation, maximum, index=index)


class ExpectedToolError(ToolError):
    """A ``ToolError`` for expected, agent-correctable failures.

    Defaults ``log_level`` to ``WARNING`` (honored by fastmcp when logging tool
    failures) so routine validation errors, missing objects, and tier denials do
    not surface as ``ERROR`` records. Carries an optional agent-facing
    ``suggestion`` the error-result middleware appends to the result text and
    mirrors into the result ``meta``.

    Examples
    --------
    >>> import logging
    >>> ExpectedToolError("Pane not found: %5").log_level == logging.WARNING
    True
    >>> ExpectedToolError("noisy", log_level=logging.INFO).log_level == logging.INFO
    True
    >>> isinstance(ExpectedToolError("x"), ToolError)
    True
    >>> ExpectedToolError("x", suggestion="Call list_panes.").suggestion
    'Call list_panes.'
    >>> ExpectedToolError("no hint").suggestion is None
    True
    """

    def __init__(
        self,
        *args: object,
        log_level: int = logging.WARNING,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(*args, log_level=log_level)
        self.suggestion = suggestion
