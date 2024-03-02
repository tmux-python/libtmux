""":mod:`dataclasses` utilities.

Note
----
This is an internal API not covered by versioning policy.
"""

import dataclasses
import typing as t
from operator import attrgetter

if t.TYPE_CHECKING:
    from _typeshed import DataclassInstance


class SkipDefaultFieldsReprMixin:
    r"""Skip default fields in :func:`~dataclasses.dataclass` object representation.

    See Also
    --------
    :func:`object representation <repr()>`

    Notes
    -----
    Credit: Pietro Oldrati, 2022-05-08, Unilicense

    https://stackoverflow.com/a/72161437/1396928

    Examples
    --------
    >>> @dataclasses.dataclass()
    ... class Item:
    ...     name: str
    ...     unit_price: float = 1.00
    ...     quantity_on_hand: int = 0
    ...

    >>> @dataclasses.dataclass(repr=False)
    ... class ItemWithMixin(SkipDefaultFieldsReprMixin):
    ...     name: str
    ...     unit_price: float = 1.00
    ...     quantity_on_hand: int = 0
    ...

    >>> Item('Test')
    Item(name='Test', unit_price=1.0, quantity_on_hand=0)

    >>> ItemWithMixin('Test')
    ItemWithMixin(name=Test)

    >>> Item('Test', quantity_on_hand=2)
    Item(name='Test', unit_price=1.0, quantity_on_hand=2)

    >>> ItemWithMixin('Test', quantity_on_hand=2)
    ItemWithMixin(name=Test, quantity_on_hand=2)

    If you want to copy/paste the :meth:`~.__repr__()`
    directly, you can omit the ``repr=False``:

    >>> @dataclasses.dataclass
    ... class ItemWithMixin(SkipDefaultFieldsReprMixin):
    ...     name: str
    ...     unit_price: float = 1.00
    ...     quantity_on_hand: int = 0
    ...     __repr__ = SkipDefaultFieldsReprMixin.__repr__
    ...

    >>> ItemWithMixin('Test')
    ItemWithMixin(name=Test)

    >>> ItemWithMixin('Test', unit_price=2.00)
    ItemWithMixin(name=Test, unit_price=2.0)

    >>> item = ItemWithMixin('Test')
    >>> item.unit_price = 2.05

    >>> item
    ItemWithMixin(name=Test, unit_price=2.05)
    """

    def __repr__(self: "DataclassInstance") -> str:
        """Omit default fields in object representation."""
        nodef_f_vals = (
            (f.name, attrgetter(f.name)(self))
            for f in dataclasses.fields(self)
            if attrgetter(f.name)(self) != f.default
        )

        nodef_f_repr = ", ".join(f"{name}={value}" for name, value in nodef_f_vals)
        return f"{self.__class__.__name__}({nodef_f_repr})"
