"""Helper methods for libtmux and downstream libtmux libraries."""

from __future__ import annotations

import contextlib
import logging
import os
import pathlib
import random
import time
import typing as t

from libtmux.exc import WaitTimeout
from libtmux.test.constants import (
    RETRY_INTERVAL_SECONDS,
    RETRY_TIMEOUT_SECONDS,
    TEST_SESSION_PREFIX,
)

from .random import namer

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:
    import sys
    import types
    from collections.abc import Callable, Generator

    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self
