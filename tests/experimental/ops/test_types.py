"""Tests for the typed primitives in :mod:`libtmux.experimental.ops._types`."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.ops._types import (
    ClientName,
    Effects,
    IndexRef,
    NameRef,
    PaneId,
    SessionId,
    SlotRef,
    Special,
    WindowId,
    render_target,
)

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Target


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        pytest.param(PaneId("%1"), "%1", id="pane-id"),
        pytest.param(WindowId("@2"), "@2", id="window-id"),
        pytest.param(SessionId("$0"), "$0", id="session-id"),
        pytest.param(ClientName("/dev/pts/3"), "/dev/pts/3", id="client-name"),
        pytest.param(NameRef("work"), "work", id="name-ref"),
        pytest.param(NameRef("work", exact=True), "=work", id="name-ref-exact"),
        pytest.param(IndexRef(0), "0", id="index-ref"),
        pytest.param(IndexRef(2, parent="$1"), "$1:2", id="index-ref-parent"),
        pytest.param(Special("{marked}"), "{marked}", id="special"),
    ],
)
def test_target_render(target: Target, expected: str) -> None:
    """Each concrete target renders to its tmux ``-t`` token."""
    assert target.render() == expected
    assert render_target(target) == expected


def test_render_target_none() -> None:
    """``render_target(None)`` yields ``None`` (no target)."""
    assert render_target(None) is None


@pytest.mark.parametrize(
    ("ctor", "value"),
    [
        pytest.param(PaneId, "1", id="pane-missing-sigil"),
        pytest.param(WindowId, "2", id="window-missing-sigil"),
        pytest.param(SessionId, "0", id="session-missing-sigil"),
        pytest.param(ClientName, "", id="client-empty"),
        pytest.param(NameRef, "", id="name-empty"),
        pytest.param(Special, "", id="special-empty"),
    ],
)
def test_target_validation_fails_closed(
    ctor: t.Callable[[str], object],
    value: str,
) -> None:
    """Malformed targets raise at construction rather than at tmux time."""
    with pytest.raises(ValueError, match="must"):
        ctor(value)


def test_slot_ref_render_raises() -> None:
    """An unresolved deferred ref cannot render -- that is a planner bug."""
    with pytest.raises(TypeError, match="unresolved SlotRef"):
        SlotRef(0).render()


def test_effects_defaults() -> None:
    """An empty :class:`Effects` is all-false / no-creates."""
    effects = Effects()
    assert not effects.read_only
    assert not effects.destructive
    assert effects.creates is None
