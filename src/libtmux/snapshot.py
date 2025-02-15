"""Snapshot and recording functionality for tmux panes."""

from __future__ import annotations

import dataclasses
import datetime
import json
import typing as t
from abc import ABC, abstractmethod

from typing_extensions import Self

from libtmux.formats import PANE_FORMATS

if t.TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from libtmux.pane import Pane


class SnapshotOutputAdapter(ABC):
    """Base class for snapshot output adapters.

    This class defines the interface for converting a PaneSnapshot
    into different output formats.
    """

    @abstractmethod
    def format(self, snapshot: PaneSnapshot) -> str:
        """Format the snapshot for output.

        Parameters
        ----------
        snapshot : PaneSnapshot
            The snapshot to format

        Returns
        -------
        str
            The formatted output
        """


class TerminalOutputAdapter(SnapshotOutputAdapter):
    """Format snapshot for terminal output with ANSI colors."""

    def format(self, snapshot: PaneSnapshot) -> str:
        """Format snapshot with ANSI colors for terminal display.

        Parameters
        ----------
        snapshot : PaneSnapshot
            The snapshot to format

        Returns
        -------
        str
            ANSI-colored terminal output
        """
        header = (
            f"\033[1;34m=== Pane Snapshot ===\033[0m\n"
            f"\033[1;36mPane:\033[0m {snapshot.pane_id}\n"
            f"\033[1;36mWindow:\033[0m {snapshot.window_id}\n"
            f"\033[1;36mSession:\033[0m {snapshot.session_id}\n"
            f"\033[1;36mServer:\033[0m {snapshot.server_name}\n"
            f"\033[1;36mTimestamp:\033[0m {snapshot.timestamp.isoformat()}\n"
            f"\033[1;33m=== Content ===\033[0m\n"
        )
        return header + snapshot.content_str


class CLIOutputAdapter(SnapshotOutputAdapter):
    """Format snapshot for plain text CLI output."""

    def format(self, snapshot: PaneSnapshot) -> str:
        """Format snapshot as plain text.

        Parameters
        ----------
        snapshot : PaneSnapshot
            The snapshot to format

        Returns
        -------
        str
            Plain text output suitable for CLI
        """
        header = (
            f"=== Pane Snapshot ===\n"
            f"Pane: {snapshot.pane_id}\n"
            f"Window: {snapshot.window_id}\n"
            f"Session: {snapshot.session_id}\n"
            f"Server: {snapshot.server_name}\n"
            f"Timestamp: {snapshot.timestamp.isoformat()}\n"
            f"=== Content ===\n"
        )
        return header + snapshot.content_str


class PytestDiffAdapter(SnapshotOutputAdapter):
    """Format snapshot for pytest assertion diffs."""

    def format(self, snapshot: PaneSnapshot) -> str:
        """Format snapshot for optimal pytest diff output.

        Parameters
        ----------
        snapshot : PaneSnapshot
            The snapshot to format

        Returns
        -------
        str
            Pytest-friendly diff output
        """
        lines = [
            "PaneSnapshot(",
            f"    pane_id={snapshot.pane_id!r},",
            f"    window_id={snapshot.window_id!r},",
            f"    session_id={snapshot.session_id!r},",
            f"    server_name={snapshot.server_name!r},",
            f"    timestamp={snapshot.timestamp.isoformat()!r},",
            "    content=[",
            *(f"        {line!r}," for line in snapshot.content),
            "    ],",
            "    metadata={",
            *(f"        {k!r}: {v!r}," for k, v in sorted(snapshot.metadata.items())),
            "    },",
            ")",
        ]
        return "\n".join(lines)


class SyrupySnapshotAdapter(SnapshotOutputAdapter):
    """Format snapshot for syrupy snapshot testing."""

    def format(self, snapshot: PaneSnapshot) -> str:
        """Format snapshot for syrupy compatibility.

        Parameters
        ----------
        snapshot : PaneSnapshot
            The snapshot to format

        Returns
        -------
        str
            JSON-serialized snapshot data
        """
        data = {
            "pane_id": snapshot.pane_id,
            "window_id": snapshot.window_id,
            "session_id": snapshot.session_id,
            "server_name": snapshot.server_name,
            "timestamp": snapshot.timestamp.isoformat(),
            "content": snapshot.content,
            "metadata": snapshot.metadata,
        }
        return json.dumps(data, indent=2, sort_keys=True)


@dataclasses.dataclass(frozen=True)
class PaneSnapshot:
    """A frozen snapshot of a pane's state at a point in time.

    This class captures both the content and metadata of a tmux pane,
    making it suitable for testing and debugging purposes.

    Attributes
    ----------
    content : list[str]
        The captured content of the pane
    timestamp : datetime.datetime
        When the snapshot was taken (in UTC)
    pane_id : str
        The ID of the pane
    window_id : str
        The ID of the window containing the pane
    session_id : str
        The ID of the session containing the window
    server_name : str
        The name of the tmux server
    metadata : dict[str, str]
        Additional pane metadata from tmux formats
    """

    content: list[str]
    timestamp: datetime.datetime
    pane_id: str
    window_id: str
    session_id: str
    server_name: str
    metadata: dict[str, str]

    @classmethod
    def from_pane(
        cls,
        pane: Pane,
        start: t.Literal["-"] | int | None = None,
        end: t.Literal["-"] | int | None = None,
    ) -> Self:
        """Create a snapshot from a pane.

        Parameters
        ----------
        pane : Pane
            The pane to snapshot
        start : int | "-" | None
            Start line for capture_pane
        end : int | "-" | None
            End line for capture_pane

        Returns
        -------
        PaneSnapshot
            A frozen snapshot of the pane's state
        """
        metadata = {
            fmt: getattr(pane, fmt)
            for fmt in PANE_FORMATS
            if hasattr(pane, fmt) and getattr(pane, fmt) is not None
        }

        content = pane.capture_pane(start=start, end=end)
        if isinstance(content, str):
            content = [content]

        return cls(
            content=content,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            pane_id=str(pane.pane_id),
            window_id=str(pane.window.window_id),
            session_id=str(pane.session.session_id),
            server_name=str(pane.server.socket_name),
            metadata=metadata,
        )

    def format(self, adapter: SnapshotOutputAdapter | None = None) -> str:
        """Format the snapshot using the specified adapter.

        If no adapter is provided, uses the default string representation.

        Parameters
        ----------
        adapter : SnapshotOutputAdapter | None
            The adapter to use for formatting

        Returns
        -------
        str
            The formatted output
        """
        if adapter is None:
            return str(self)
        return adapter.format(self)

    def __str__(self) -> str:
        """Return a string representation of the snapshot.

        Returns
        -------
        str
            A formatted string showing the snapshot content and metadata
        """
        return (
            f"PaneSnapshot(pane={self.pane_id}, window={self.window_id}, "
            f"session={self.session_id}, server={self.server_name}, "
            f"timestamp={self.timestamp.isoformat()}, "
            f"content=\n{self.content_str})"
        )

    @property
    def content_str(self) -> str:
        """Get the pane content as a single string.

        Returns
        -------
        str
            The pane content with lines joined by newlines
        """
        return "\n".join(self.content)


@dataclasses.dataclass
class PaneRecording:
    """A time-series recording of pane snapshots.

    This class maintains an ordered sequence of pane snapshots,
    allowing for analysis of how a pane's content changes over time.

    Attributes
    ----------
    snapshots : list[PaneSnapshot]
        The sequence of snapshots in chronological order
    """

    snapshots: list[PaneSnapshot] = dataclasses.field(default_factory=list)

    def add_snapshot(
        self,
        pane: Pane,
        start: t.Literal["-"] | int | None = None,
        end: t.Literal["-"] | int | None = None,
    ) -> None:
        """Add a new snapshot to the recording.

        Parameters
        ----------
        pane : Pane
            The pane to snapshot
        start : int | "-" | None
            Start line for capture_pane
        end : int | "-" | None
            End line for capture_pane
        """
        self.snapshots.append(PaneSnapshot.from_pane(pane, start=start, end=end))

    def __len__(self) -> int:
        """Get the number of snapshots in the recording.

        Returns
        -------
        int
            The number of snapshots
        """
        return len(self.snapshots)

    def __iter__(self) -> Iterator[PaneSnapshot]:
        """Iterate through snapshots in chronological order.

        Returns
        -------
        Iterator[PaneSnapshot]
            Iterator over the snapshots
        """
        return iter(self.snapshots)

    def __getitem__(self, index: int) -> PaneSnapshot:
        """Get a snapshot by index.

        Parameters
        ----------
        index : int
            The index of the snapshot to retrieve

        Returns
        -------
        PaneSnapshot
            The snapshot at the specified index
        """
        return self.snapshots[index]

    @property
    def latest(self) -> PaneSnapshot | None:
        """Get the most recent snapshot.

        Returns
        -------
        PaneSnapshot | None
            The most recent snapshot, or None if no snapshots exist
        """
        return self.snapshots[-1] if self.snapshots else None

    def get_snapshots_between(
        self,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
    ) -> Sequence[PaneSnapshot]:
        """Get snapshots between two points in time.

        Parameters
        ----------
        start_time : datetime.datetime
            The start of the time range
        end_time : datetime.datetime
            The end of the time range

        Returns
        -------
        Sequence[PaneSnapshot]
            Snapshots within the specified time range
        """
        return [
            snapshot
            for snapshot in self.snapshots
            if start_time <= snapshot.timestamp <= end_time
        ]
