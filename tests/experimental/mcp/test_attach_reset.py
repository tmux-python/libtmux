"""A reconnect must clear the sticky attach so %output flows again."""

from __future__ import annotations

from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine


def test_reset_attach_clears_flag() -> None:
    """_reset_attach() must set _attached_session to None."""
    engine = AsyncControlModeEngine()
    engine._attached_session = "$0"
    engine._reset_attach()
    assert getattr(engine, "_attached_session", "sentinel") is None
