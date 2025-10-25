"""Sparse array for libtmux options and hooks."""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from typing_extensions import TypeAlias, TypeGuard

    from libtmux.options import ExplodedComplexUntypedOptionsDict


T = t.TypeVar("T")
HookArray: TypeAlias = "dict[str, SparseArray[str]]"


def is_sparse_array_list(
    items: ExplodedComplexUntypedOptionsDict,
) -> TypeGuard[HookArray]:
    return all(
        isinstance(
            v,
            SparseArray,
        )
        for k, v in items.items()
    )


class SparseArray(dict[int, T], t.Generic[T]):
    """Support non-sequential indexes while maintaining :class:`list`-like behavior.

    A normal :class:`list` would raise :exc:`IndexError`.

    There are no native sparse arrays in python that contain non-sequential indexes and
    maintain list-like behavior. This is useful for handling libtmux options and hooks:

    ``command-alias[1] split-pane=split-window`` to
    ``{'command-alias[1]': {'split-pane=split-window'}}``

    :class:`list` would lose indice info, and :class:`dict` would lose list-like
    behavior.
    """

    def add(self, index: int, value: T) -> None:
        self[index] = value

    def append(self, value: T) -> None:
        index = max(self.keys()) + 1
        self[index] = value

    def iter_values(self) -> t.Iterator[T]:
        for index in sorted(self.keys()):
            yield self[index]

    def as_list(self) -> list[T]:
        return [self[index] for index in sorted(self.keys())]
