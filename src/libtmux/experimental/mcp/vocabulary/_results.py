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
    """A created session: its id, name, and captured first window/pane ids.

    Attributes
    ----------
    session_id : str
        Created tmux session id.
    name : str or None
        Created session name.
    first_window_id : str or None
        First window id captured during creation.
    first_pane_id : str or None
        First pane id captured during creation.
    """

    session_id: str
    name: str | None = None
    first_window_id: str | None = None
    first_pane_id: str | None = None


@dataclass(frozen=True)
class WindowResult:
    """A created window: its id, name, and captured first pane id.

    Attributes
    ----------
    window_id : str
        Created tmux window id.
    name : str or None
        Created window name.
    first_pane_id : str or None
        First pane id captured during creation.
    """

    window_id: str
    name: str | None = None
    first_pane_id: str | None = None


@dataclass(frozen=True)
class PaneResult:
    """A created pane: its id.

    Attributes
    ----------
    pane_id : str
        Created tmux pane id.
    """

    pane_id: str


@dataclass(frozen=True)
class PaneRef:
    """A resolved pane id (or ``None`` when no pane matched the query).

    Attributes
    ----------
    pane_id : str or None
        Resolved pane id, or ``None`` when no pane matched.
    """

    pane_id: str | None


@dataclass(frozen=True)
class PaneCapture:
    """Captured pane contents.

    Attributes
    ----------
    lines : tuple[str, ...]
        Captured terminal lines.
    """

    lines: tuple[str, ...]


@dataclass(frozen=True)
class Listing:
    """A list query result: one mapping (tmux format row) per object.

    Attributes
    ----------
    rows : tuple[collections.abc.Mapping[str, str], ...]
        Tmux-format mappings returned by the list query.
    """

    rows: tuple[collections.abc.Mapping[str, str], ...]


@dataclass(frozen=True)
class OptionMap:
    """Parsed ``show-options`` output: ``name -> value`` pairs.

    Attributes
    ----------
    options : collections.abc.Mapping[str, str]
        Parsed option names and values.
    """

    options: collections.abc.Mapping[str, str]


@dataclass(frozen=True)
class MessageText:
    """The formatted text of a ``display-message -p`` query.

    Attributes
    ----------
    text : str
        Formatted tmux message text.
    """

    text: str


@dataclass(frozen=True)
class BufferText:
    """The contents of a paste buffer (``show-buffer``).

    Attributes
    ----------
    text : str
        Paste-buffer contents.
    """

    text: str


@dataclass(frozen=True)
class RawResult:
    """The raw outcome of a passthrough ``run_tmux`` invocation.

    Attributes
    ----------
    ok : bool
        Whether the tmux command succeeded.
    returncode : int
        Process exit status returned by tmux.
    stdout : tuple[str, ...]
        Captured standard-output lines.
    stderr : tuple[str, ...]
        Captured standard-error lines.
    """

    ok: bool
    returncode: int
    stdout: tuple[str, ...]
    stderr: tuple[str, ...]


@dataclass(frozen=True)
class PaneMatch:
    """One pane whose terminal text matched a search, with its caller flag.

    Attributes
    ----------
    pane_id : str
        Id of the pane containing the match.
    is_caller : bool
        Whether the pane is the MCP caller's pane.
    lines : tuple[str, ...]
        Matching terminal lines.
    """

    pane_id: str
    is_caller: bool
    lines: tuple[str, ...]


@dataclass(frozen=True)
class PaneSearch:
    """The panes whose scrollback matched a ``search_panes`` query.

    Attributes
    ----------
    matches : tuple[PaneMatch, ...]
        Matching panes and their captured lines.
    """

    matches: tuple[PaneMatch, ...]
