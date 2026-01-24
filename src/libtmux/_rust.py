"""Rust-backed libtmux bindings.

This module is intentionally thin: it re-exports Rust types from the
vibe-tmux extension so libtmux can opt into the Rust backend.
"""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS = ("Server",)
_NATIVE: Any | None = None


def _load_native() -> Any:
    global _NATIVE
    if _NATIVE is None:
        try:
            _NATIVE = importlib.import_module("vibe_tmux")
        except Exception as exc:  # pragma: no cover - import path is env-dependent
            raise ImportError(
                "libtmux rust backend requires the vibe_tmux extension to be installed"
            ) from exc
    return _NATIVE


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        native = _load_native()
        return getattr(native, name)
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_EXPORTS))


__all__ = _EXPORTS
