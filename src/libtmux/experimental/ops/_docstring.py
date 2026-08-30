"""Docstring introspection shared by the projections of an operation.

An operation's docstring is its user-facing text: the catalog renders it into the
operation reference, and the MCP registry / adapter render it into a tool
description. All three want the same one-line summary, so it is derived once,
here.
"""

from __future__ import annotations


def first_line(doc: str | None) -> str:
    r"""Return the first non-empty line of *doc* (``""`` when there is none).

    Parameters
    ----------
    doc : str | None
        A docstring (``__doc__`` is ``None`` under ``python -OO``).

    Returns
    -------
    str

    Examples
    --------
    >>> first_line("Split a window.\n\nLonger prose follows.\n")
    'Split a window.'
    >>> first_line("\n    Indented summary.\n")
    'Indented summary.'
    >>> first_line(None)
    ''
    """
    for line in (doc or "").splitlines():
        if line.strip():
            return line.strip()
    return ""
