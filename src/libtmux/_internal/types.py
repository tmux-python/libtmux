"""Internal type annotations.

Notes
-----
:class:`StrPath` is based on `typeshed's`_.

.. _typeshed's: https://github.com/python/typeshed/blob/5ff32f3/stdlib/_typeshed/__init__.pyi#L176-L179
"""  # E501

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from os import PathLike
    from typing import TypeAlias

StrPath: TypeAlias = "str | PathLike[str]"
