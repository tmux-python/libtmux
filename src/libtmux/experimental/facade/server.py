"""Server-scope eager facade -- the entry point for live navigation."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.facade.session import EagerSession
from libtmux.experimental.ops import NewSession, run

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import TmuxEngine


@dataclass(frozen=True)
class EagerServer:
    """A live server handle; the root of eager facade navigation.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> server = EagerServer(ConcreteEngine())
    >>> session = server.new_session(name="work")
    >>> session.session_id
    '$1'
    >>> window = session.new_window()
    >>> pane = window.split()
    >>> pane.pane_id
    '%1'
    """

    engine: TmuxEngine
    version: str | None = None

    def new_session(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
    ) -> EagerSession:
        """Create a detached session; return a live session handle."""
        result = run(
            NewSession(session_name=name, start_directory=start_directory),
            self.engine,
            version=self.version,
        )
        result.raise_for_status()
        assert result.new_id is not None
        return EagerSession(self.engine, result.new_id, self.version)

    @classmethod
    def for_server(cls, server: t.Any, *, version: str | None = None) -> EagerServer:
        """Bind an eager facade to a live :class:`libtmux.Server`'s classic engine."""
        from libtmux.experimental.engines import SubprocessEngine

        return cls(SubprocessEngine.for_server(server), version=version)
