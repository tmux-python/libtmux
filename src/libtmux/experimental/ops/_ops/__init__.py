"""Concrete seed operations.

Importing this package registers each operation in the default registry
(:data:`libtmux.experimental.ops.registry.registry`) as a side effect of the
``@register`` decorator on each class.
"""

from __future__ import annotations

from libtmux.experimental.ops._ops.capture_pane import CapturePane
from libtmux.experimental.ops._ops.select_layout import SelectLayout
from libtmux.experimental.ops._ops.send_keys import SendKeys
from libtmux.experimental.ops._ops.split_window import SplitWindow

__all__ = (
    "CapturePane",
    "SelectLayout",
    "SendKeys",
    "SplitWindow",
)
