"""Pure pane-geometry helpers for directional and corner resolution.

tmux's own ``{up-of}`` / ``{down-of}`` target tokens always pivot on the
*active* pane and vary across tmux versions, so resolving "the pane to the right
of %5" robustly means reading the layout geometry and computing the neighbour
ourselves -- the same lesson libtmux-mcp's ``select_pane``/``find_pane_by_position``
encode. These helpers operate on the ``pane_left/top/right/bottom`` and
``pane_at_*`` fields the ``list-panes`` template already carries, so they need no
extra tmux round-trip beyond the one list.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

if t.TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: Directions a pane neighbour can be resolved in.
Direction = t.Literal["up", "down", "left", "right"]
#: The four window corners.
Corner = t.Literal["top-left", "top-right", "bottom-left", "bottom-right"]


def _as_int(value: str | None) -> int:
    """Parse a tmux integer format value, defaulting to ``0``."""
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _as_bool(value: str | None) -> bool:
    """Parse a tmux flag value (``"1"``/``"0"``/``""``)."""
    return value == "1"


@dataclass(frozen=True)
class PaneBox:
    """One pane's geometry, parsed from a ``list-panes`` format row."""

    pane_id: str
    left: int
    top: int
    right: int
    bottom: int
    at_left: bool
    at_right: bool
    at_top: bool
    at_bottom: bool
    active: bool

    @classmethod
    def from_row(cls, row: Mapping[str, str]) -> PaneBox:
        """Build a box from a tmux format mapping."""
        return cls(
            pane_id=row.get("pane_id", ""),
            left=_as_int(row.get("pane_left")),
            top=_as_int(row.get("pane_top")),
            right=_as_int(row.get("pane_right")),
            bottom=_as_int(row.get("pane_bottom")),
            at_left=_as_bool(row.get("pane_at_left")),
            at_right=_as_bool(row.get("pane_at_right")),
            at_top=_as_bool(row.get("pane_at_top")),
            at_bottom=_as_bool(row.get("pane_at_bottom")),
            active=_as_bool(row.get("pane_active")),
        )


def parse_boxes(rows: Sequence[Mapping[str, str]]) -> list[PaneBox]:
    """Parse ``list-panes`` rows into geometry boxes."""
    return [PaneBox.from_row(row) for row in rows]


def _overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    """Inclusive 1-D overlap length of ``[a0, a1]`` and ``[b0, b1]``."""
    return max(0, min(a1, b1) - max(a0, b0) + 1)


def neighbor(
    boxes: Sequence[PaneBox],
    origin_id: str,
    direction: Direction,
) -> str | None:
    """Return the id of the pane adjacent to *origin_id* in *direction*.

    Picks the nearest pane on the requested side that shares a perpendicular
    overlap with the origin; ``None`` when the origin is unknown or has no
    neighbour that way.

    Examples
    --------
    Two side-by-side panes -- the right neighbour of the left pane is the right
    one, and the left pane has no neighbour above it:

    >>> rows = [
    ...     {"pane_id": "%1", "pane_left": "0", "pane_top": "0",
    ...      "pane_right": "39", "pane_bottom": "23"},
    ...     {"pane_id": "%2", "pane_left": "41", "pane_top": "0",
    ...      "pane_right": "80", "pane_bottom": "23"},
    ... ]
    >>> boxes = parse_boxes(rows)
    >>> neighbor(boxes, "%1", "right")
    '%2'
    >>> neighbor(boxes, "%1", "up") is None
    True
    """
    origin = next((b for b in boxes if b.pane_id == origin_id), None)
    if origin is None:
        return None
    ranked: list[tuple[int, int, str]] = []
    for box in boxes:
        if box.pane_id == origin_id:
            continue
        vspan = _overlap(box.top, box.bottom, origin.top, origin.bottom)
        hspan = _overlap(box.left, box.right, origin.left, origin.right)
        if direction == "right" and box.left > origin.right and vspan:
            ranked.append((box.left, box.top, box.pane_id))
        elif direction == "left" and box.right < origin.left and vspan:
            ranked.append((-box.right, box.top, box.pane_id))
        elif direction == "down" and box.top > origin.bottom and hspan:
            ranked.append((box.top, box.left, box.pane_id))
        elif direction == "up" and box.bottom < origin.top and hspan:
            ranked.append((-box.bottom, box.left, box.pane_id))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][2]


def corner_pane(boxes: Sequence[PaneBox], corner: Corner) -> str | None:
    """Return the id of the pane occupying *corner* of the window.

    Composes the two ``pane_at_*`` edge predicates; ties (e.g. a single pane
    touching every edge) break toward the visually innermost pane.

    Examples
    --------
    >>> rows = [
    ...     {"pane_id": "%1", "pane_left": "0", "pane_top": "0",
    ...      "pane_at_left": "1", "pane_at_top": "1", "pane_at_right": "0",
    ...      "pane_at_bottom": "1"},
    ...     {"pane_id": "%2", "pane_left": "41", "pane_top": "0",
    ...      "pane_at_left": "0", "pane_at_top": "1", "pane_at_right": "1",
    ...      "pane_at_bottom": "1"},
    ... ]
    >>> corner_pane(parse_boxes(rows), "top-right")
    '%2'
    """
    vertical, horizontal = corner.split("-")
    matches = [
        box
        for box in boxes
        if getattr(box, f"at_{vertical}") and getattr(box, f"at_{horizontal}")
    ]
    if not matches:
        return None
    matches.sort(key=lambda b: b.left + b.top, reverse=True)
    return matches[0].pane_id
