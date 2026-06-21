"""Shared helpers for read (list) operations.

These re-export neo's format-template builder and output parser so the list
operations render the ``-F`` template and parse it with the *exact same* logic
the ORM's reader uses -- one source of truth, no drift. The list ops are a
separate, engine-pluggable read surface that yields immutable
:mod:`~libtmux.experimental.models` snapshots; neo itself is untouched.
"""

from __future__ import annotations

from libtmux.formats import FORMAT_SEPARATOR
from libtmux.neo import get_output_format, parse_output

DEFAULT_LIST_VERSION = "3.2a"
"""tmux version assumed when the caller supplies none (the project floor).

Rendering and parsing must use the *same* version, so a list op renders its
``-F`` template and parses its output at this version unless an explicit one is
threaded through. Older = a safe field subset on any newer server.
"""

__all__ = (
    "DEFAULT_LIST_VERSION",
    "FORMAT_SEPARATOR",
    "get_output_format",
    "parse_output",
)
