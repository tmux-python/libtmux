"""Helper utilities for waiter tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.window import Window


def ensure_pane(pane: Pane | None) -> Pane:
    """Ensure that a pane is not None.

    This helper is needed for type safety in the examples.

    Args:
        pane: The pane to check

    Returns
    -------
        The pane if it's not None

    Raises
    ------
        ValueError: If the pane is None
    """
    if pane is None:
        msg = "Pane cannot be None"
        raise ValueError(msg)
    return pane


def send_keys(pane: Pane | None, keys: str) -> None:
    """Send keys to a pane after ensuring it's not None.

    Args:
        pane: The pane to send keys to
        keys: The keys to send

    Raises
    ------
        ValueError: If the pane is None
    """
    ensure_pane(pane).send_keys(keys)


def kill_window_safely(window: Window | None) -> None:
    """Kill a window if it's not None.

    Args:
        window: The window to kill
    """
    if window is not None:
        window.kill()
