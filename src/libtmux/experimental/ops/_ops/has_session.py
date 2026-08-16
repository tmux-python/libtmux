"""The ``has-session`` operation -- a typed existence query."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import HasSessionResult

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class HasSession(Operation[HasSessionResult]):
    """Check whether a session exists (``has-session``).

    ``target`` is the session. A missing session is a valid answer (rc 1), not
    an error, so the result is always ``complete`` and carries the answer in
    :attr:`~.HasSessionResult.exists`.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import SessionId
    >>> HasSession(target=SessionId("$0")).render()
    ('has-session', '-t', '$0')
    >>> HasSession(target=SessionId("$0")).build_result(returncode=1).exists
    False
    """

    kind = "has_session"
    command = "has-session"
    scope = "session"
    result_cls = HasSessionResult
    safety = "readonly"
    chainable = False
    effects = Effects(read_only=True, idempotent=True)

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """No positional arguments beyond the target."""
        return ()

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
        version: str | None = None,
    ) -> HasSessionResult:
        """Map the exit code to existence; the query itself always completes.

        ``has-session`` writes its "can't find session" message to stderr; surface
        it in stdout here (rather than in each engine) so the result is consistent
        across engines.
        """
        if stderr and not stdout:
            stdout = (stderr[0],)
        return HasSessionResult(
            operation=self,
            argv=argv,
            status="complete",
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            exists=returncode == 0,
        )
