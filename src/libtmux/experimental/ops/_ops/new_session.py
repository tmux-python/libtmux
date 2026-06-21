"""The ``new-session`` operation (creates a session, captures its id)."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import CreateResult

if t.TYPE_CHECKING:
    from collections.abc import Mapping

    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class NewSession(Operation[CreateResult]):
    """Create a detached session; capture the new session's id.

    Examples
    --------
    >>> NewSession(session_name="work").render()
    ('new-session', '-d', '-s', 'work', '-P', '-F', '#{session_id}')
    >>> NewSession().build_result(returncode=0, stdout=("$2",)).new_id
    '$2'
    """

    kind = "new_session"
    command = "new-session"
    scope = "server"
    result_cls = CreateResult
    safety = "mutating"
    chainable = False
    effects = Effects(creates="session")
    flag_version_map: t.ClassVar[Mapping[str, str]] = {"environment": "3.0"}

    session_name: str | None = None
    start_directory: str | None = None
    environment: Mapping[str, str] | None = None
    width: int | None = None
    height: int | None = None
    capture: bool = True

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render ``new-session`` flags (always detached for headless use)."""
        out: list[str] = ["-d"]
        if self.session_name is not None:
            out.extend(("-s", self.session_name))
        if self.start_directory is not None:
            out.append(f"-c{self.start_directory}")
        if self.environment and self.flag_available("environment", version):
            out.extend(f"-e{key}={value}" for key, value in self.environment.items())
        if self.width is not None:
            out.extend(("-x", str(self.width)))
        if self.height is not None:
            out.extend(("-y", str(self.height)))
        if self.capture:
            out.extend(("-P", "-F", "#{session_id}"))
        return tuple(out)

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
        version: str | None = None,
    ) -> CreateResult:
        """Parse the captured new-session id."""
        new_id = stdout[0].strip() if status == "complete" and stdout else None
        return CreateResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            new_id=new_id,
        )
