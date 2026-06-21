"""The ``new-window`` operation (creates a window, captures its id)."""

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
class NewWindow(Operation[CreateResult]):
    """Create a window in a session; capture the new window's id.

    ``target`` is the session the window is created in.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import SessionId
    >>> NewWindow(target=SessionId("$0"), name="build").render()
    ('new-window', '-t', '$0', '-d', '-n', 'build', '-P', '-F', '#{window_id}')
    >>> NewWindow(target=SessionId("$0")).build_result(
    ...     returncode=0, stdout=("@5",)
    ... ).new_id
    '@5'
    """

    kind = "new_window"
    command = "new-window"
    scope = "session"
    result_cls = CreateResult
    safety = "mutating"
    chainable = False
    effects = Effects(creates="window")
    flag_version_map: t.ClassVar[Mapping[str, str]] = {"environment": "3.0"}

    name: str | None = None
    start_directory: str | None = None
    environment: Mapping[str, str] | None = None
    detach: bool = True
    capture: bool = True
    window_shell: str | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render ``new-window`` flags."""
        out: list[str] = []
        if self.detach:
            out.append("-d")
        if self.name is not None:
            out.extend(("-n", self.name))
        if self.start_directory is not None:
            out.append(f"-c{self.start_directory}")
        if self.environment and self.flag_available("environment", version):
            out.extend(f"-e{key}={value}" for key, value in self.environment.items())
        if self.capture:
            out.extend(("-P", "-F", "#{window_id}"))
        if self.window_shell is not None:
            out.append(self.window_shell)
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
        """Parse the captured new-window id."""
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
