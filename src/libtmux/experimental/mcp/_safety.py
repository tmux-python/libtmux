"""Safety tiers for the MCP tool surface.

A small, dependency-light core: the three safety-tier tags every tool is
registered under, the ``LIBTMUX_SAFETY`` resolver, and the expected-error type
the middleware demotes to ``WARNING``. Imported only from the fastmcp edge (the
adapter wiring and the middleware), so it stays cycle-free -- fastmcp + logging
only, never the framework-agnostic core.
"""

from __future__ import annotations

import logging

from fastmcp.exceptions import ToolError

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
