"""Pane-scope facades demonstrating "mode lives in the type".

Two thin facades over the *same* operation spine show why the execution mode
belongs in the class rather than a runtime flag:

- :class:`EagerPane` executes immediately and returns *live* handles
  (``split()`` -> :class:`EagerPane`), so its return types are concrete.
- :class:`LazyPane` records into a :class:`~libtmux.experimental.ops.plan.LazyPlan`
  and returns *deferred* handles (``split()`` -> :class:`LazyPane`), executing
  only when the plan runs.

Each ``split()`` therefore has exactly one statically-known return type -- a
single ``Pane`` class with a runtime engine attribute could not express that.
The same :class:`~libtmux.experimental.ops.SplitWindow` operation backs both;
only the facade differs. This is the seed of the wider facade matrix
(``AsyncPane``, ``LazyControlWindow``, ...) described in issue 689.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops import (
    CapturePane,
    NewPane,
    SendKeys,
    SplitWindow,
    arun,
    run,
)
from libtmux.experimental.ops._types import PaneId

if t.TYPE_CHECKING:
    from collections.abc import Mapping

    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops._types import Target
    from libtmux.experimental.ops.plan import LazyPlan
    from libtmux.experimental.ops.results import CapturePaneResult, Result


def _new_pane_op(
    target: Target,
    *,
    width: int | str | None,
    height: int | str | None,
    x: int | str | None,
    y: int | str | None,
    zoom: bool,
    detach: bool,
    empty: bool,
    start_directory: str | None,
    environment: Mapping[str, str] | None,
    style: str | None,
    active_border_style: str | None,
    inactive_border_style: str | None,
    message: str | None,
    shell_command: str | None,
) -> NewPane:
    """Build a :class:`~..ops.NewPane` for *target* (shared by the facades)."""
    return NewPane(
        target=target,
        width=width,
        height=height,
        x=x,
        y=y,
        zoom=zoom,
        detach=detach,
        empty=empty,
        start_directory=start_directory,
        environment=environment,
        style=style,
        active_border_style=active_border_style,
        inactive_border_style=inactive_border_style,
        message=message,
        shell_command=shell_command,
    )


@dataclass(frozen=True)
class EagerPane:
    """A live pane handle bound to an engine; methods execute immediately.

    Parameters
    ----------
    engine : TmuxEngine
        The engine commands run through.
    pane_id : str
        The concrete tmux pane id (``%N``).
    version : str or None
        tmux version to render against.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> pane = EagerPane(ConcreteEngine(), "%0")
    >>> child = pane.split(horizontal=True)
    >>> child.pane_id
    '%1'
    >>> floating = pane.new_pane(width=80, height=20)
    >>> floating.pane_id
    '%2'
    >>> isinstance(pane.capture().lines, tuple)
    True
    """

    engine: TmuxEngine
    pane_id: str
    version: str | None = None

    def split(
        self,
        *,
        horizontal: bool = False,
        start_directory: str | None = None,
        shell: str | None = None,
    ) -> EagerPane:
        """Split this pane and return a live handle to the new pane."""
        result = run(
            SplitWindow(
                target=PaneId(self.pane_id),
                horizontal=horizontal,
                start_directory=start_directory,
                shell=shell,
            ),
            self.engine,
            version=self.version,
        )
        result.raise_for_status()
        assert result.new_pane_id is not None
        return EagerPane(self.engine, result.new_pane_id, self.version)

    def new_pane(
        self,
        *,
        width: int | str | None = None,
        height: int | str | None = None,
        x: int | str | None = None,
        y: int | str | None = None,
        zoom: bool = False,
        detach: bool = True,
        empty: bool = False,
        start_directory: str | None = None,
        environment: Mapping[str, str] | None = None,
        style: str | None = None,
        active_border_style: str | None = None,
        inactive_border_style: str | None = None,
        message: str | None = None,
        shell_command: str | None = None,
    ) -> EagerPane:
        """Create a floating pane (tmux 3.7+) and return a live handle to it."""
        result = run(
            _new_pane_op(
                PaneId(self.pane_id),
                width=width,
                height=height,
                x=x,
                y=y,
                zoom=zoom,
                detach=detach,
                empty=empty,
                start_directory=start_directory,
                environment=environment,
                style=style,
                active_border_style=active_border_style,
                inactive_border_style=inactive_border_style,
                message=message,
                shell_command=shell_command,
            ),
            self.engine,
            version=self.version,
        )
        result.raise_for_status()
        assert result.new_pane_id is not None
        return EagerPane(self.engine, result.new_pane_id, self.version)

    def send_keys(self, keys: str, *, enter: bool = False) -> Result:
        """Send keys to this pane; return the typed result."""
        return run(
            SendKeys(target=PaneId(self.pane_id), keys=keys, enter=enter),
            self.engine,
            version=self.version,
        )

    def capture(
        self, *, start: int | None = None, end: int | None = None
    ) -> CapturePaneResult:
        """Capture this pane's contents; return the typed result."""
        return run(
            CapturePane(target=PaneId(self.pane_id), start=start, end=end),
            self.engine,
            version=self.version,
        )


@dataclass(frozen=True)
class LazyPane:
    """A deferred pane handle; methods record into a plan instead of running.

    Parameters
    ----------
    plan : LazyPlan
        The plan operations are recorded into.
    ref : Target
        The target this handle addresses (a concrete id, or a SlotRef for a
        pane created earlier in the plan).

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> from libtmux.experimental.ops import LazyPlan
    >>> from libtmux.experimental.ops._types import PaneId
    >>> plan = LazyPlan()
    >>> root = LazyPane(plan, PaneId("%0"))
    >>> child = root.split()
    >>> _ = child.send_keys("vim", enter=True)
    >>> outcome = plan.execute(ConcreteEngine())
    >>> outcome.results[0].new_pane_id
    '%1'
    >>> outcome.results[1].argv
    ('send-keys', '-t', '%1', 'vim', 'Enter')
    """

    plan: LazyPlan
    ref: Target

    def split(
        self,
        *,
        horizontal: bool = False,
        start_directory: str | None = None,
        shell: str | None = None,
    ) -> LazyPane:
        """Record a split; return a deferred handle to the pane it will create."""
        slot = self.plan.add(
            SplitWindow(
                target=self.ref,
                horizontal=horizontal,
                start_directory=start_directory,
                shell=shell,
            ),
        )
        return LazyPane(self.plan, slot)

    def new_pane(
        self,
        *,
        width: int | str | None = None,
        height: int | str | None = None,
        x: int | str | None = None,
        y: int | str | None = None,
        zoom: bool = False,
        detach: bool = True,
        empty: bool = False,
        start_directory: str | None = None,
        environment: Mapping[str, str] | None = None,
        style: str | None = None,
        active_border_style: str | None = None,
        inactive_border_style: str | None = None,
        message: str | None = None,
        shell_command: str | None = None,
    ) -> LazyPane:
        """Record a floating-pane creation; return a deferred handle to it."""
        slot = self.plan.add(
            _new_pane_op(
                self.ref,
                width=width,
                height=height,
                x=x,
                y=y,
                zoom=zoom,
                detach=detach,
                empty=empty,
                start_directory=start_directory,
                environment=environment,
                style=style,
                active_border_style=active_border_style,
                inactive_border_style=inactive_border_style,
                message=message,
                shell_command=shell_command,
            ),
        )
        return LazyPane(self.plan, slot)

    def send_keys(self, keys: str, *, enter: bool = False) -> LazyPane:
        """Record a send-keys against this handle; return self for chaining."""
        self.plan.add(SendKeys(target=self.ref, keys=keys, enter=enter))
        return self

    def capture(self, *, start: int | None = None, end: int | None = None) -> LazyPane:
        """Record a capture against this handle; return self for chaining."""
        self.plan.add(CapturePane(target=self.ref, start=start, end=end))
        return self


@dataclass(frozen=True)
class AsyncPane:
    """An async live pane handle: the eager pane, awaited.

    Identical in shape to :class:`EagerPane` -- same operations, same spine --
    but bound to an :class:`~..engines.base.AsyncTmuxEngine` and awaited. This is
    why async is a sibling facade, not a transformation.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.experimental.engines import AsyncConcreteEngine
    >>> async def main():
    ...     pane = AsyncPane(AsyncConcreteEngine(), "%0")
    ...     child = await pane.split(horizontal=True)
    ...     return child.pane_id
    >>> asyncio.run(main())
    '%1'
    """

    engine: AsyncTmuxEngine
    pane_id: str
    version: str | None = None

    async def split(
        self,
        *,
        horizontal: bool = False,
        start_directory: str | None = None,
        shell: str | None = None,
    ) -> AsyncPane:
        """Split this pane and return a live async handle to the new pane."""
        result = await arun(
            SplitWindow(
                target=PaneId(self.pane_id),
                horizontal=horizontal,
                start_directory=start_directory,
                shell=shell,
            ),
            self.engine,
            version=self.version,
        )
        result.raise_for_status()
        assert result.new_pane_id is not None
        return AsyncPane(self.engine, result.new_pane_id, self.version)

    async def new_pane(
        self,
        *,
        width: int | str | None = None,
        height: int | str | None = None,
        x: int | str | None = None,
        y: int | str | None = None,
        zoom: bool = False,
        detach: bool = True,
        empty: bool = False,
        start_directory: str | None = None,
        environment: Mapping[str, str] | None = None,
        style: str | None = None,
        active_border_style: str | None = None,
        inactive_border_style: str | None = None,
        message: str | None = None,
        shell_command: str | None = None,
    ) -> AsyncPane:
        """Create a floating pane (tmux 3.7+) and return a live async handle."""
        result = await arun(
            _new_pane_op(
                PaneId(self.pane_id),
                width=width,
                height=height,
                x=x,
                y=y,
                zoom=zoom,
                detach=detach,
                empty=empty,
                start_directory=start_directory,
                environment=environment,
                style=style,
                active_border_style=active_border_style,
                inactive_border_style=inactive_border_style,
                message=message,
                shell_command=shell_command,
            ),
            self.engine,
            version=self.version,
        )
        result.raise_for_status()
        assert result.new_pane_id is not None
        return AsyncPane(self.engine, result.new_pane_id, self.version)

    async def send_keys(self, keys: str, *, enter: bool = False) -> Result:
        """Send keys to this pane; return the typed result."""
        return await arun(
            SendKeys(target=PaneId(self.pane_id), keys=keys, enter=enter),
            self.engine,
            version=self.version,
        )

    async def capture(
        self,
        *,
        start: int | None = None,
        end: int | None = None,
    ) -> CapturePaneResult:
        """Capture this pane's contents; return the typed result."""
        return await arun(
            CapturePane(target=PaneId(self.pane_id), start=start, end=end),
            self.engine,
            version=self.version,
        )
