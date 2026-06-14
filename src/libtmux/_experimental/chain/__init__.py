r"""Typed, chainable tmux command sequences (experimental).

This package promotes the converged design from the ``chainable-commands``
research into a typed, documented API. It lets callers author an ordered
sequence of tmux commands that compiles to **one** native ``tmux ... \\; ...``
invocation and dispatches once, instead of issuing one subprocess per command.

The layers build on each other:

- :mod:`~libtmux._experimental.chain.ir` -- the immutable argv
  intermediate representation (``CommandCall``, ``CommandChain``).

Note
----
This is an **experimental** API, not covered by the project's versioning policy.
It may change or be removed between any releases without notice.
"""

from __future__ import annotations

from libtmux._experimental.chain.ir import (
    Arg,
    CommandCall,
    CommandChain,
    CommandResultLike,
    CommandRunner,
    CommandScope,
    CommandSpec,
)

__all__ = [
    "Arg",
    "CommandCall",
    "CommandChain",
    "CommandResultLike",
    "CommandRunner",
    "CommandScope",
    "CommandSpec",
]
