"""The ``capture-pane`` operation."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import CapturePaneResult

if t.TYPE_CHECKING:
    from collections.abc import Mapping

    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class CapturePane(Operation[CapturePaneResult]):
    """Capture a pane's contents (a read-only operation).

    Parameters
    ----------
    start, end : int or None
        Start/end line for the capture (``-S`` / ``-E``).
    escape_sequences : bool
        Include escape sequences (``-e``).
    join_wrapped : bool
        Join wrapped lines (``-J``).
    trim_trailing : bool
        Trim trailing whitespace (``-T``; tmux 3.4+, dropped on older tmux).
    mode_screen : bool
        Capture the visible screen in copy mode (``-M``; tmux 3.6+).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> CapturePane(target=PaneId("%1")).render()
    ('capture-pane', '-t', '%1', '-p')

    Version-gated flags are dropped on older tmux:

    >>> op = CapturePane(target=PaneId("%1"), trim_trailing=True)
    >>> op.render(version="3.3")
    ('capture-pane', '-t', '%1', '-p')
    >>> op.render(version="3.4")
    ('capture-pane', '-t', '%1', '-p', '-T')

    Captured stdout is exposed as typed lines:

    >>> result = op.build_result(returncode=0, stdout=("foo", "bar"))
    >>> result.lines
    ('foo', 'bar')
    """

    kind = "capture_pane"
    command = "capture-pane"
    scope = "pane"
    result_cls = CapturePaneResult
    safety = "readonly"
    effects = Effects(read_only=True, reads_output=True, idempotent=True)
    flag_version_map: t.ClassVar[Mapping[str, str]] = {
        "trim_trailing": "3.4",
        "mode_screen": "3.6",
    }

    start: int | None = None
    end: int | None = None
    escape_sequences: bool = False
    join_wrapped: bool = False
    trim_trailing: bool = False
    mode_screen: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render ``capture-pane`` flags (``-p`` prints to stdout)."""
        out: list[str] = ["-p"]
        if self.start is not None:
            out.extend(("-S", str(self.start)))
        if self.end is not None:
            out.extend(("-E", str(self.end)))
        if self.escape_sequences:
            out.append("-e")
        if self.join_wrapped:
            out.append("-J")
        if self.trim_trailing and self.flag_available("trim_trailing", version):
            out.append("-T")
        if self.mode_screen and self.flag_available("mode_screen", version):
            out.append("-M")
        return tuple(out)

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
    ) -> CapturePaneResult:
        """Expose captured stdout as typed :attr:`~.CapturePaneResult.lines`."""
        return CapturePaneResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            lines=stdout,
        )
