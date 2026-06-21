"""Session-scope eager facade over the operation spine."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.facade.window import EagerWindow
from libtmux.experimental.ops import (
    KillSession,
    NewWindow,
    RenameSession,
    run,
)
from libtmux.experimental.ops._types import SessionId

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import TmuxEngine
    from libtmux.experimental.ops.results import Result


@dataclass(frozen=True)
class EagerSession:
    """A live session handle; methods execute immediately.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> session = EagerSession(ConcreteEngine(), "$0")
    >>> window = session.new_window(name="build")
    >>> window.window_id
    '@1'
    >>> session.rename("work").ok
    True
    """

    engine: TmuxEngine
    session_id: str
    version: str | None = None

    def new_window(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
    ) -> EagerWindow:
        """Create a window in this session; return a live window handle."""
        result = run(
            NewWindow(
                target=SessionId(self.session_id),
                name=name,
                start_directory=start_directory,
            ),
            self.engine,
            version=self.version,
        )
        result.raise_for_status()
        assert result.new_id is not None
        return EagerWindow(self.engine, result.new_id, self.version)

    def rename(self, name: str) -> Result:
        """Rename this session."""
        return run(
            RenameSession(target=SessionId(self.session_id), name=name),
            self.engine,
            version=self.version,
        )

    def kill(self) -> Result:
        """Kill this session."""
        return run(
            KillSession(target=SessionId(self.session_id)),
            self.engine,
            version=self.version,
        )
