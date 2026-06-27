"""Latest-wins ordering: when two updates for one pane race, keep the newer.

A ``Stamp`` is a logical clock ``(counter, writer)``. ``latest`` decides whether
an incoming stamp should replace the current one. The clock is pluggable: a
monotonic counter is single-host-correct; an HLC can drop in later for multi-host
without touching call sites.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

Clock = t.Callable[[], int]


@dataclass(frozen=True, order=True)
class Stamp:
    """A logical-clock tag on one state update.

    Ordered by ``counter`` first, then ``writer`` (a deterministic tie-break when
    two sources stamp the same counter).

    Examples
    --------
    >>> Stamp(2, "option") > Stamp(1, "osc")
    True
    >>> Stamp(1, "osc") > Stamp(1, "option")
    True
    """

    counter: int
    writer: str


def latest(current: Stamp | None, incoming: Stamp) -> bool:
    """Return ``True`` if *incoming* should replace *current* (it is newer).

    Examples
    --------
    >>> latest(None, Stamp(0, "option"))
    True
    >>> latest(Stamp(5, "option"), Stamp(4, "option"))
    False
    """
    return current is None or incoming > current


class MonotonicCounter:
    """A strictly-increasing integer clock for single-host stamping.

    Examples
    --------
    >>> clock = MonotonicCounter()
    >>> clock(), clock()
    (1, 2)
    """

    def __init__(self) -> None:
        self._value = 0

    def __call__(self) -> int:
        """Return the next integer (strictly greater than the previous)."""
        self._value += 1
        return self._value
