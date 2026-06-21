"""The ``split-window`` operation."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import SplitWindowResult

if t.TYPE_CHECKING:
    from collections.abc import Mapping

    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class SplitWindow(Operation[SplitWindowResult]):
    """Split a pane, creating a new pane.

    By default the operation appends ``-P -F '#{pane_id}'`` so the new pane's id
    is captured on stdout; :meth:`build_result` reads it into
    :attr:`~.results.SplitWindowResult.new_pane_id`.

    Parameters
    ----------
    horizontal : bool
        Split left/right (``-h``) instead of top/bottom (``-v``).
    start_directory : str or None
        Working directory for the new pane (``-c``).
    environment : Mapping[str, str] or None
        Environment variables for the new pane (``-e``; tmux 3.0+).
    shell : str or None
        A shell command to run in the new pane instead of the default shell.
    capture : bool
        Append ``-P -F '#{pane_id}'`` to capture the new pane id.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> SplitWindow(target=PaneId("%1"), horizontal=True).render()
    ('split-window', '-t', '%1', '-h', '-P', '-F', '#{pane_id}')

    The ``-e`` environment flag is dropped on tmux older than 3.0:

    >>> op = SplitWindow(target=PaneId("%1"), environment={"E": "1"})
    >>> op.render(version="2.9")
    ('split-window', '-t', '%1', '-v', '-P', '-F', '#{pane_id}')
    >>> op.render(version="3.3")
    ('split-window', '-t', '%1', '-v', '-eE=1', '-P', '-F', '#{pane_id}')

    The created pane id is parsed into the typed result:

    >>> result = op.build_result(returncode=0, stdout=("%2",))
    >>> result.new_pane_id
    '%2'
    """

    kind = "split_window"
    command = "split-window"
    scope = "window"
    result_cls = SplitWindowResult
    safety = "mutating"
    effects = Effects(creates="pane")
    flag_version_map: t.ClassVar[Mapping[str, str]] = {"environment": "3.0"}

    horizontal: bool = False
    start_directory: str | None = None
    environment: Mapping[str, str] | None = None
    shell: str | None = None
    capture: bool = True

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render ``split-window`` flags."""
        out: list[str] = ["-h" if self.horizontal else "-v"]
        if self.start_directory is not None:
            out.append(f"-c{self.start_directory}")
        if self.environment and self.flag_available("environment", version):
            out.extend(f"-e{key}={value}" for key, value in self.environment.items())
        if self.capture:
            out.extend(("-P", "-F", "#{pane_id}"))
        if self.shell is not None:
            out.append(self.shell)
        return tuple(out)

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
        version: str | None = None,
    ) -> SplitWindowResult:
        """Parse the captured new-pane id into the typed result."""
        new_pane_id = stdout[0].strip() if status == "complete" and stdout else None
        return SplitWindowResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            new_pane_id=new_pane_id,
        )
