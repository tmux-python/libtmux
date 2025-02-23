"""Constants for libtmux test helpers."""

from __future__ import annotations

import os

TEST_SESSION_PREFIX = "libtmux_"
RETRY_TIMEOUT_SECONDS = int(os.getenv("RETRY_TIMEOUT_SECONDS", 8))
RETRY_INTERVAL_SECONDS = float(os.getenv("RETRY_INTERVAL_SECONDS", 0.05))
