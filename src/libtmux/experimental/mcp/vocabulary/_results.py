"""Small, typed result values returned by the curated vocabulary.

Each curated tool returns one of these frozen dataclasses exposing just the
ids/names/lines a caller cares about -- never a live ORM object and never the raw
:class:`~libtmux.experimental.ops.results.Result`. They serialize trivially
(plain scalars and tuples), which is what the MCP edge hands back to an agent.
"""

from __future__ import annotations

import collections.abc
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionResult:
    """A created session: its id, name, and captured first window/pane ids."""

    session_id: str
    name: str | None = None
    first_window_id: str | None = None
    first_pane_id: str | None = None


@dataclass(frozen=True)
class WindowResult:
    """A created window: its id, name, and captured first pane id."""

    window_id: str
    name: str | None = None
    first_pane_id: str | None = None


@dataclass(frozen=True)
class PaneResult:
    """A created pane: its id."""

    pane_id: str


@dataclass(frozen=True)
class PaneRef:
    """A resolved pane id (or ``None`` when no pane matched the query)."""

    pane_id: str | None


@dataclass(frozen=True)
class PaneCapture:
    """Captured pane contents."""

    lines: tuple[str, ...]


@dataclass(frozen=True)
class Listing:
    """A list query result: one mapping (tmux format row) per object."""

    rows: tuple[collections.abc.Mapping[str, str], ...]


@dataclass(frozen=True)
class OptionMap:
    """Parsed ``show-options`` output: ``name -> value`` pairs."""

    options: collections.abc.Mapping[str, str]


@dataclass(frozen=True)
class MessageText:
    """The formatted text of a ``display-message -p`` query."""

    text: str


@dataclass(frozen=True)
class BufferText:
    """The contents of a paste buffer (``show-buffer``)."""

    text: str


@dataclass(frozen=True)
class RawResult:
    """The raw outcome of a passthrough ``run_tmux`` invocation."""

    ok: bool
    returncode: int
    stdout: tuple[str, ...]
    stderr: tuple[str, ...]


@dataclass(frozen=True)
class PaneMatch:
    """One pane whose terminal text matched a search, with its caller flag."""

    pane_id: str
    is_caller: bool
    lines: tuple[str, ...]


@dataclass(frozen=True)
class PaneSearch:
    """The panes whose scrollback matched a ``search_panes`` query."""

    matches: tuple[PaneMatch, ...]
