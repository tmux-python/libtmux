"""Pytest configuration for docs/_ext doctests."""

from __future__ import annotations

import pathlib
import sys

_ext_dir = pathlib.Path(__file__).parent
if str(_ext_dir) not in sys.path:
    sys.path.insert(0, str(_ext_dir))
