"""Constants for libtmux test helpers."""

from __future__ import annotations

import os

#: Prefix used for test session names to identify and cleanup test sessions
TEST_SESSION_PREFIX = "libtmux_"

#: Number of seconds to wait before timing out when retrying operations
#: Can be configured via :envvar:`RETRY_TIMEOUT_SECONDS` environment variable
#: Defaults to 8 seconds
RETRY_TIMEOUT_SECONDS = int(os.getenv("RETRY_TIMEOUT_SECONDS", 8))

#: Interval in seconds between retry attempts
#: Can be configured via :envvar:`RETRY_INTERVAL_SECONDS` environment variable
#: Defaults to 0.05 seconds (50ms)
RETRY_INTERVAL_SECONDS = float(os.getenv("RETRY_INTERVAL_SECONDS", 0.05))
