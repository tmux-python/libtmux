"""Experimental libtmux APIs.

This package hosts work that is **not** covered by the project's versioning
policy. Anything under :mod:`libtmux.experimental` may change shape or be
removed between any two releases without notice.

The package centers on inert, typed tmux operation values and interchangeable
execution engines. Operations render commands, carry result types, and
serialize without a live tmux server; engines execute them and return the same
typed result shapes.
"""

from __future__ import annotations
