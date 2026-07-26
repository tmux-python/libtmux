"""The ``break-pane`` operation (creates a window, captures its id)."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import SourceTargetOperation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import CreateResult
from libtmux.neo import _normalize_tmux_version

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Status
    from libtmux.experimental.ops.operation import Operation


def _breaks_without_name(version: str | None) -> bool:
    """Whether this tmux needs a placeholder ``-n`` for a nameless break-pane.

    tmux 3.7 NULL-derefs ``break-pane`` when ``-n`` is absent (fixed upstream
    after 3.7), so exactly 3.7 must be handed a placeholder name.
    """
    if version is None:
        return False
    return _normalize_tmux_version(version) == _normalize_tmux_version("3.7")


@register
@dataclass(frozen=True, kw_only=True)
class BreakPane(SourceTargetOperation[CreateResult]):
    """Break a pane out into a new window (``break-pane``).

    The pane to break is the ``-s`` source (``src_target``); there is no ``-t``.
    By default it appends ``-P -F '#{window_id}'`` so the new window's id is
    captured into :attr:`~.results.CreateResult.new_id`.

    Attributes
    ----------
    detach : bool
        Do not switch to the new window (``-d``).
    name : str or None
        Requested name for the new window. On tmux 3.7 the executor applies it
        with ``rename-window`` after the break.
    capture : bool
        Expose the captured new window id. A named tmux 3.7 break captures it
        internally even when this is ``False`` so the executor can rename it.

    Notes
    -----
    tmux 3.7 crashes the server on a nameless ``break-pane`` (a NULL-deref fixed
    upstream after 3.7) and ignores the value passed to ``-n``. Exactly 3.7 is
    therefore handed a placeholder name. When
    :func:`~libtmux.experimental.ops.execute.run` or
    :func:`~libtmux.experimental.ops.execute.arun` executes a named break, it
    follows the successful command with a typed ``rename-window`` operation.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> BreakPane(src_target=PaneId("%2"), name="logs").render()
    ('break-pane', '-d', '-n', 'logs', '-P', '-F', '#{window_id}', '-s', '%2')

    On exactly tmux 3.7 every break-pane is given a placeholder name; other
    builds render normally:

    >>> BreakPane(src_target=PaneId("%2"), name="logs").render(version="3.7")
    ('break-pane', '-d', '-n', 'libtmux', '-P', '-F', '#{window_id}', '-s', '%2')
    >>> BreakPane(src_target=PaneId("%2")).render(version="3.8")
    ('break-pane', '-d', '-P', '-F', '#{window_id}', '-s', '%2')

    >>> BreakPane(src_target=PaneId("%2")).build_result(
    ...     returncode=0, stdout=("@7",)
    ... ).new_id
    '@7'
    """

    kind = "break_pane"
    command = "break-pane"
    scope = "window"
    result_cls = CreateResult
    safety = "mutating"
    chainable = False
    primitive = False
    effects = Effects(creates="window")

    detach: bool = True
    name: str | None = None
    capture: bool = True

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the break flags, capture template, and ``-s`` source."""
        out: list[str] = []
        if self.detach:
            out.append("-d")
        workaround = _breaks_without_name(version)
        if workaround:
            out.extend(("-n", "libtmux"))
        elif self.name is not None:
            out.extend(("-n", self.name))
        if self.capture or (workaround and self.name is not None):
            out.extend(("-P", "-F", "#{window_id}"))
        out.extend(self.src_args())
        return tuple(out)

    def _follow_up(
        self,
        result: CreateResult,
        *,
        version: str | None = None,
    ) -> Operation[t.Any] | None:
        """Rename the captured window after tmux 3.7 ignored ``-n``.

        Examples
        --------
        >>> from libtmux.experimental.ops._types import PaneId
        >>> op = BreakPane(src_target=PaneId("%2"), name="logs")
        >>> primary = op.build_result(
        ...     returncode=0, stdout=("@7",), version="3.7"
        ... )
        >>> op._follow_up(primary, version="3.7").render()
        ('rename-window', '-t', '@7', '--', 'logs')
        """
        if (
            not _breaks_without_name(version)
            or self.name is None
            or not result.ok
            or not result.stdout
        ):
            return None
        from libtmux.experimental.ops._ops.rename_window import RenameWindow
        from libtmux.experimental.ops._types import WindowId

        return RenameWindow(
            target=WindowId(result.stdout[0].strip()),
            name=self.name,
        )

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
        captured_id = (
            stdout[0].strip() if status == "complete" and stdout else None
        ) or None
        if (
            status == "complete"
            and _breaks_without_name(version)
            and self.name is not None
            and captured_id is None
        ):
            status = "failed"
            stderr = (*stderr, "break-pane did not capture its new window id")
        new_id = captured_id if status == "complete" and self.capture else None
        return CreateResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            new_id=new_id,
        )
