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

    Parameters
    ----------
    capture_pane : bool
        Also capture the new window's first pane id (into
        :attr:`~.results.CreateResult.first_pane_id`), so a plan can target it
        via ``slot.pane``.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import SessionId
    >>> NewWindow(target=SessionId("$0"), name="build").render()
    ('new-window', '-t', '$0', '-d', '-n', 'build', '-P', '-F', '#{window_id}')
    >>> NewWindow(target=SessionId("$0"), capture_pane=True).render()[-1]
    '#{window_id} #{pane_id}'
    >>> NewWindow(target=SessionId("$0")).build_result(
    ...     returncode=0, stdout=("@5",)
    ... ).new_id
    '@5'
    >>> r = NewWindow(capture_pane=True).build_result(returncode=0, stdout=("@5 %6",))
    >>> (r.new_id, r.first_pane_id)
    ('@5', '%6')
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
    capture_pane: bool = False
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
            fmt = "#{window_id} #{pane_id}" if self.capture_pane else "#{window_id}"
            out.extend(("-P", "-F", fmt))
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
        """Parse the captured window id (and first pane id if captured)."""
        ids = stdout[0].split() if status == "complete" and stdout else []
        return CreateResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            new_id=ids[0] if ids else None,
            first_pane_id=ids[1] if len(ids) > 1 else None,
        )
