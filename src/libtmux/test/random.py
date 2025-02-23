"""Random helpers for libtmux and downstream libtmux libraries."""

from __future__ import annotations

import logging
import random
import typing as t

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:
    import sys

    if sys.version_info >= (3, 11):
        pass


class RandomStrSequence:
    """Factory to generate random string."""

    def __init__(
        self,
        characters: str = "abcdefghijklmnopqrstuvwxyz0123456789_",
    ) -> None:
        """Create a random letter / number generator. 8 chars in length.

        >>> rng = RandomStrSequence()
        >>> next(rng)
        '...'
        >>> len(next(rng))
        8
        >>> type(next(rng))
        <class 'str'>
        """
        self.characters: str = characters

    def __iter__(self) -> RandomStrSequence:
        """Return self."""
        return self

    def __next__(self) -> str:
        """Return next random string."""
        return "".join(random.sample(self.characters, k=8))


namer = RandomStrSequence()
