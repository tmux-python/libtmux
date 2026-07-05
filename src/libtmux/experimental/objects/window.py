"""Window-scope objects (eager / lazy / async) over the operation spine.

Mirrors the pane objects one scope up: an :class:`EagerWindow` executes now and
returns live objects (``split()`` -> :class:`~.pane.EagerPane`), a
:class:`LazyWindow` records into a plan, and an :class:`AsyncWindow` awaits. All
three drive the *same* window-scope operations; only the object differs.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.objects.pane import AsyncPane, EagerPane, LazyPane
from libtmux.experimental.ops import (
    KillWindow,
    RenameWindow,
    SelectLayout,
    SplitWindow,
    arun,
    run,
)
from libtmux.experimental.ops._types import WindowId

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops._types import Target
    from libtmux.experimental.ops.plan import LazyPlan
    from libtmux.experimental.ops.results import Result


@dataclass(frozen=True)
class EagerWindow:
    """A live window object bound to an engine; methods execute immediately.

    Examples
    --------
    >>> from libtmux.experimental.engines import MockEngine
    >>> window = EagerWindow(MockEngine(), "@1")
    >>> pane = window.split(horizontal=True)
    >>> pane.pane_id
    '%1'
    >>> window.rename("build").ok
    True
    """

    engine: TmuxEngine
    window_id: str
    version: str | None = None

    def split(
        self,
        *,
        horizontal: bool = False,
        start_directory: str | None = None,
        shell: str | None = None,
    ) -> EagerPane:
        """Split this window's active pane; return a live pane object."""
        result = run(
            SplitWindow(
                target=WindowId(self.window_id),
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

    def rename(self, name: str) -> Result:
        """Rename this window."""
        return run(
            RenameWindow(target=WindowId(self.window_id), name=name),
            self.engine,
            version=self.version,
        )

    def select_layout(self, layout: str) -> Result:
        """Apply a layout to this window."""
        return run(
            SelectLayout(target=WindowId(self.window_id), layout=layout),
            self.engine,
            version=self.version,
        )

    def kill(self) -> Result:
        """Kill this window."""
        return run(
            KillWindow(target=WindowId(self.window_id)),
            self.engine,
            version=self.version,
        )


@dataclass(frozen=True)
class LazyWindow:
    """A deferred window object; methods record into a plan.

    Examples
    --------
    >>> from libtmux.experimental.engines import MockEngine
    >>> from libtmux.experimental.ops import LazyPlan
    >>> from libtmux.experimental.ops._types import WindowId
    >>> plan = LazyPlan()
    >>> window = LazyWindow(plan, WindowId("@1"))
    >>> pane = window.split()
    >>> _ = window.rename("build")
    >>> outcome = plan.execute(MockEngine())
    >>> outcome.ok
    True
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
        """Record a split; return a deferred pane object to the new pane."""
        slot = self.plan.add(
            SplitWindow(
                target=self.ref,
                horizontal=horizontal,
                start_directory=start_directory,
                shell=shell,
            ),
        )
        return LazyPane(self.plan, slot)

    def rename(self, name: str) -> LazyWindow:
        """Record a rename; return self for chaining."""
        self.plan.add(RenameWindow(target=self.ref, name=name))
        return self

    def select_layout(self, layout: str) -> LazyWindow:
        """Record a layout change; return self for chaining."""
        self.plan.add(SelectLayout(target=self.ref, layout=layout))
        return self

    def kill(self) -> LazyWindow:
        """Record a kill; return self for chaining."""
        self.plan.add(KillWindow(target=self.ref))
        return self


@dataclass(frozen=True)
class AsyncWindow:
    """An async live window object: the eager window, awaited."""

    engine: AsyncTmuxEngine
    window_id: str
    version: str | None = None

    async def split(
        self,
        *,
        horizontal: bool = False,
        start_directory: str | None = None,
        shell: str | None = None,
    ) -> AsyncPane:
        """Split this window's active pane; return a live async pane object."""
        result = await arun(
            SplitWindow(
                target=WindowId(self.window_id),
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

    async def rename(self, name: str) -> Result:
        """Rename this window."""
        return await arun(
            RenameWindow(target=WindowId(self.window_id), name=name),
            self.engine,
            version=self.version,
        )

    async def select_layout(self, layout: str) -> Result:
        """Apply a layout to this window."""
        return await arun(
            SelectLayout(target=WindowId(self.window_id), layout=layout),
            self.engine,
            version=self.version,
        )

    async def kill(self) -> Result:
        """Kill this window."""
        return await arun(
            KillWindow(target=WindowId(self.window_id)),
            self.engine,
            version=self.version,
        )
