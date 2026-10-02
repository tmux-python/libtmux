"""How adopter code reads numeric tmux fields under ``mypy --strict``."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from typing import assert_type
else:
    from typing_extensions import assert_type

from libtmux import Client, Pane, Session, Window


def numbers_and_flags_need_no_conversion(pane: Pane) -> int:
    """Use ``typed`` where an ``int`` or ``bool`` is wanted."""
    width: int = pane.typed.pane_width
    height: int = pane.typed.pane_height
    active: bool = pane.typed.pane_active
    assert_type(pane.typed.history_size, int)
    assert_type(pane.typed.pane_dead, bool)
    return width * height + (1 if active else 0)


def a_value_tmux_can_leave_empty_is_optional(pane: Pane) -> None:
    """Narrow ``None`` where tmux leaves the field empty."""
    assert_type(pane.typed.pane_dead_status, int | None)
    assert_type(pane.typed.pane_pid, int | None)
    status = pane.typed.pane_dead_status
    if status is not None:
        assert_type(status, int)
    bad: int = pane.typed.pane_dead_status  # type: ignore[assignment]
    del bad


def every_object_with_a_listing_has_the_view(
    window: Window,
    session: Session,
    client: Client,
) -> None:
    """Read window, session and client fields the same way."""
    assert_type(window.typed.window_panes, int)
    assert_type(window.typed.window_zoomed_flag, bool)
    assert_type(session.typed.session_windows, int)
    assert_type(session.typed.session_attached, int)
    assert_type(client.typed.client_pid, int | None)
    assert_type(client.typed.pane_width, int)


def the_raw_text_fields_keep_their_type(pane: Pane) -> None:
    """Keep ``str | None`` on the dataclass fields."""
    assert_type(pane.pane_width, str | None)
    assert_type(pane.pane_active, str | None)
    wrong: int = pane.pane_width  # type: ignore[assignment]
    del wrong


def a_client_field_is_not_on_a_pane_view(pane: Pane) -> None:
    """Reject ``client_*`` fields on a view that cannot report them."""
    _ = pane.typed.client_pid  # type: ignore[attr-defined]
