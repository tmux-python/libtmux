"""Sparse array for libtmux options and hooks."""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from typing import TypeAlias, TypeGuard

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

    Examples
    --------
    Create a sparse array and add values at non-sequential indices:

    >>> from libtmux._internal.sparse_array import SparseArray

    >>> arr: SparseArray[str] = SparseArray()
    >>> arr.add(0, "first hook command")
    >>> arr.add(5, "fifth hook command")
    >>> arr.add(2, "second hook command")

    Access values by index (dict-style):

    >>> arr[0]
    'first hook command'
    >>> arr[5]
    'fifth hook command'

    Check index existence:

    >>> 0 in arr
    True
    >>> 3 in arr
    False

    Iterate values in sorted index order:

    >>> list(arr.iter_values())
    ['first hook command', 'second hook command', 'fifth hook command']

    Convert to a list (values only, sorted by index):

    >>> arr.as_list()
    ['first hook command', 'second hook command', 'fifth hook command']

    Append adds at max index + 1:

    >>> arr.append("appended command")
    >>> arr[6]
    'appended command'

    Access raw indices:

    >>> sorted(arr.keys())
    [0, 2, 5, 6]
    """

    def add(self, index: int, value: T) -> None:
        """Add a value at a specific index.

        Parameters
        ----------
        index : int
            The index at which to store the value.
        value : T
            The value to store.

        Examples
        --------
        >>> from libtmux._internal.sparse_array import SparseArray

        >>> arr: SparseArray[str] = SparseArray()
        >>> arr.add(0, "hook at index 0")
        >>> arr.add(10, "hook at index 10")
        >>> arr[0]
        'hook at index 0'
        >>> arr[10]
        'hook at index 10'
        >>> sorted(arr.keys())
        [0, 10]
        """
        self[index] = value

    def append(self, value: T) -> None:
        """Append a value at the next available index (max + 1).

        Parameters
        ----------
        value : T
            The value to append.

        Examples
        --------
        >>> from libtmux._internal.sparse_array import SparseArray

        Appending to an empty array starts at index 0:

        >>> arr: SparseArray[str] = SparseArray()
        >>> arr.append("first")
        >>> arr[0]
        'first'

        Appending to a non-empty array adds at max index + 1:

        >>> arr.add(5, "at index 5")
        >>> arr.append("appended")
        >>> arr[6]
        'appended'
        >>> arr.append("another")
        >>> arr[7]
        'another'
        """
        index = max(self.keys(), default=-1) + 1
        self[index] = value

    def iter_values(self) -> t.Iterator[T]:
        """Iterate over values in sorted index order.

        Yields
        ------
        T
            Values in ascending index order.

        Examples
        --------
        >>> from libtmux._internal.sparse_array import SparseArray

        >>> arr: SparseArray[str] = SparseArray()
        >>> arr.add(5, "fifth")
        >>> arr.add(0, "first")
        >>> arr.add(2, "second")
        >>> for val in arr.iter_values():
        ...     print(val)
        first
        second
        fifth
        """
        for index in sorted(self.keys()):
            yield self[index]

    def as_list(self) -> list[T]:
        """Return values as a list in sorted index order.

        Returns
        -------
        list[T]
            List of values sorted by their indices.

        Examples
        --------
        >>> from libtmux._internal.sparse_array import SparseArray

        >>> arr: SparseArray[str] = SparseArray()
        >>> arr.add(10, "tenth")
        >>> arr.add(0, "zeroth")
        >>> arr.add(5, "fifth")
        >>> arr.as_list()
        ['zeroth', 'fifth', 'tenth']
        """
        return [self[index] for index in sorted(self.keys())]
