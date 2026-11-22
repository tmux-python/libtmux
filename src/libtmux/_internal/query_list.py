"""Utilities for filtering or searching :class:`list` of objects / list data.

Note
----
This is an internal API not covered by versioning policy.
"""

from __future__ import annotations

import logging
import re
import typing as t
from collections.abc import Callable, Iterable, Mapping, Sequence

from libtmux.exc import (
    MultipleObjectsReturned as MultipleObjectsReturned,
    ObjectDoesNotExist as ObjectDoesNotExist,
)

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:

    class LookupProtocol(t.Protocol):
        """Protocol for :class:`QueryList` filtering operators."""

        def __call__(
            self,
            data: object,
            rhs: object,
        ) -> bool:
            """Return callback for :class:`QueryList` filtering operators."""
            ...


T = t.TypeVar("T")
_DefaultT = t.TypeVar("_DefaultT")

no_arg = object()


def keygetter(
    obj: object,
    path: str,
) -> object:
    """Fetch values in objects and keys, supported nested data.

    **With dictionaries**:

    >>> keygetter({ "food": { "breakfast": "cereal" } }, "food")
    {'breakfast': 'cereal'}

    >>> keygetter({ "food": { "breakfast": "cereal" } }, "food__breakfast")
    'cereal'

    **With objects**:

    >>> from typing import List, Optional
    >>> from dataclasses import dataclass, field

    >>> @dataclass()
    ... class Food:
    ...     fruit: List[str] = field(default_factory=list)
    ...     breakfast: Optional[str] = None


    >>> @dataclass()
    ... class Restaurant:
    ...     place: str
    ...     city: str
    ...     state: str
    ...     food: Food = field(default_factory=Food)


    >>> restaurant = Restaurant(
    ...     place="Largo",
    ...     city="Tampa",
    ...     state="Florida",
    ...     food=Food(
    ...         fruit=["banana", "orange"], breakfast="cereal"
    ...     )
    ... )

    >>> restaurant
    Restaurant(place='Largo',
        city='Tampa',
        state='Florida',
        food=Food(fruit=['banana', 'orange'], breakfast='cereal'))

    >>> keygetter(restaurant, "food")
    Food(fruit=['banana', 'orange'], breakfast='cereal')

    >>> keygetter(restaurant, "food__breakfast")
    'cereal'
    """
    try:
        sub_fields = path.split("__")
        dct = obj
        for sub_field in sub_fields:
            if isinstance(dct, dict):
                dct = dct[sub_field]
            elif hasattr(dct, sub_field):
                dct = getattr(dct, sub_field)

    except Exception:
        logger.debug(
            "key lookup failed for path: %s",
            path,
            exc_info=True,
        )
        return None

    return dct


def parse_lookup(
    obj: object,
    path: str,
    lookup: str,
) -> object:
    """Check if field lookup key, e.g. "my__path__contains" has comparator, return val.

    If comparator not used or value not found, return None.

    >>> parse_lookup({ "food": "red apple" }, "food__istartswith", "__istartswith")
    'red apple'

    It can also look up objects:

    >>> from dataclasses import dataclass

    >>> @dataclass()
    ... class Inventory:
    ...     food: str

    >>> item = Inventory(food="red apple")

    >>> item
    Inventory(food='red apple')

    >>> parse_lookup(item, "food__istartswith", "__istartswith")
    'red apple'
    """
    try:
        if path.endswith(lookup):
            field_name = path.split(lookup, maxsplit=1)[0]
            return keygetter(obj, field_name)
    except Exception:
        logger.debug(
            "lookup parsing failed for path: %s",
            path,
            exc_info=True,
        )
    return None


def lookup_exact(
    data: object,
    rhs: object,
) -> bool:
    return rhs == data


def lookup_iexact(
    data: object,
    rhs: object,
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, str):
        return False

    return rhs.lower() == data.lower()


def lookup_contains(
    data: object,
    rhs: object,
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, (str, Mapping, list)):
        return False

    return rhs in data


def lookup_icontains(
    data: object,
    rhs: object,
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, (str, Mapping, list)):
        return False

    if isinstance(data, str):
        return rhs.lower() in data.lower()
    if isinstance(data, Mapping):
        return rhs.lower() in [str(k).lower() for k in data]

    return False


def lookup_startswith(
    data: object,
    rhs: object,
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, str):
        return False

    return data.startswith(rhs)


def lookup_istartswith(
    data: object,
    rhs: object,
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, str):
        return False

    return data.lower().startswith(rhs.lower())


def lookup_endswith(
    data: object,
    rhs: object,
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, str):
        return False

    return data.endswith(rhs)


def lookup_iendswith(
    data: object,
    rhs: object,
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, str):
        return False
    return data.lower().endswith(rhs.lower())


def lookup_in(
    data: object,
    rhs: object,
) -> bool:
    if isinstance(rhs, list):
        return data in rhs

    try:
        if isinstance(rhs, str) and isinstance(data, (str, list, Mapping)):
            return rhs in data
    except Exception:
        return False
    return False


def lookup_nin(
    data: object,
    rhs: object,
) -> bool:
    if isinstance(rhs, list):
        return data not in rhs

    try:
        if isinstance(rhs, str) and isinstance(data, (str, list, Mapping)):
            return rhs not in data
    except Exception:
        return False
    return False


def lookup_regex(
    data: object,
    rhs: object,
) -> bool:
    if isinstance(data, str) and isinstance(rhs, str):
        return bool(re.search(rhs, data))
    if isinstance(data, bytes) and isinstance(rhs, bytes):
        return bool(re.search(rhs, data))
    return False


def lookup_iregex(
    data: object,
    rhs: object,
) -> bool:
    if isinstance(data, str) and isinstance(rhs, str):
        return bool(re.search(rhs, data, re.IGNORECASE))
    if isinstance(data, bytes) and isinstance(rhs, bytes):
        return bool(re.search(rhs, data, re.IGNORECASE))
    return False


LOOKUP_NAME_MAP: Mapping[str, LookupProtocol] = {
    "eq": lookup_exact,
    "exact": lookup_exact,
    "iexact": lookup_iexact,
    "contains": lookup_contains,
    "icontains": lookup_icontains,
    "startswith": lookup_startswith,
    "istartswith": lookup_istartswith,
    "endswith": lookup_endswith,
    "iendswith": lookup_iendswith,
    "in": lookup_in,
    "nin": lookup_nin,
    "regex": lookup_regex,
    "iregex": lookup_iregex,
}


class PKRequiredException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__("items() require a pk_key exists")


class OpNotFound(ValueError):
    def __init__(self, op: str, *args: object) -> None:
        super().__init__(f"{op} not in LOOKUP_NAME_MAP")


class QueryList(list[T], t.Generic[T]):
    """Filter list of object/dictionaries. For small, local datasets.

    *Experimental, unstable*.

    **With dictionaries**:

    >>> query = QueryList(
    ...     [
    ...         {
    ...             "place": "Largo",
    ...             "city": "Tampa",
    ...             "state": "Florida",
    ...             "foods": {"fruit": ["banana", "orange"], "breakfast": "cereal"},
    ...         },
    ...         {
    ...             "place": "Chicago suburbs",
    ...             "city": "Elmhurst",
    ...             "state": "Illinois",
    ...             "foods": {"fruit": ["apple", "cantelope"], "breakfast": "waffles"},
    ...         },
    ...     ]
    ... )

    >>> query.filter(place="Chicago suburbs")[0]['city']
    'Elmhurst'
    >>> query.filter(place__icontains="chicago")[0]['city']
    'Elmhurst'
    >>> query.filter(foods__breakfast="waffles")[0]['city']
    'Elmhurst'
    >>> query.filter(foods__fruit__in="cantelope")[0]['city']
    'Elmhurst'
    >>> query.filter(foods__fruit__in="orange")[0]['city']
    'Tampa'

    >>> query.filter(foods__fruit__in="apple")
    [{'place': 'Chicago suburbs',
        'city': 'Elmhurst',
        'state': 'Illinois',
        'foods':
            {'fruit': ['apple', 'cantelope'], 'breakfast': 'waffles'}}]

    >>> query.filter(foods__fruit__in="non_existent")
    []

    **With objects**:

    >>> from typing import Any, Dict
    >>> from dataclasses import dataclass, field

    >>> @dataclass()
    ... class Restaurant:
    ...     place: str
    ...     city: str
    ...     state: str
    ...     foods: Dict[str, Any]

    >>> restaurant = Restaurant(
    ...     place="Largo",
    ...     city="Tampa",
    ...     state="Florida",
    ...     foods={
    ...         "fruit": ["banana", "orange"], "breakfast": "cereal"
    ...     }
    ... )

    >>> restaurant
    Restaurant(place='Largo',
        city='Tampa',
        state='Florida',
        foods={'fruit': ['banana', 'orange'], 'breakfast': 'cereal'})

    >>> query = QueryList([restaurant])

    >>> query.filter(foods__fruit__in="banana")
    [Restaurant(place='Largo',
        city='Tampa',
        state='Florida',
        foods={'fruit': ['banana', 'orange'], 'breakfast': 'cereal'})]

    >>> query.filter(foods__fruit__in="banana")[0].city
    'Tampa'

    >>> query.get(foods__fruit__in="banana").city
    'Tampa'

    **With objects (nested)**:

    >>> from typing import List, Optional
    >>> from dataclasses import dataclass, field

    >>> @dataclass()
    ... class Food:
    ...     fruit: List[str] = field(default_factory=list)
    ...     breakfast: Optional[str] = None


    >>> @dataclass()
    ... class Restaurant:
    ...     place: str
    ...     city: str
    ...     state: str
    ...     food: Food = field(default_factory=Food)


    >>> query = QueryList([
    ...     Restaurant(
    ...         place="Largo",
    ...         city="Tampa",
    ...         state="Florida",
    ...         food=Food(
    ...             fruit=["banana", "orange"], breakfast="cereal"
    ...         )
    ...     ),
    ...     Restaurant(
    ...         place="Chicago suburbs",
    ...         city="Elmhurst",
    ...         state="Illinois",
    ...         food=Food(
    ...             fruit=["apple", "cantelope"], breakfast="waffles"
    ...         )
    ...     )
    ... ])

    >>> query.filter(food__fruit__in="banana")
    [Restaurant(place='Largo',
        city='Tampa',
        state='Florida',
        food=Food(fruit=['banana', 'orange'], breakfast='cereal'))]

    >>> query.filter(food__fruit__in="banana")[0].city
    'Tampa'

    >>> query.get(food__fruit__in="banana").city
    'Tampa'

    >>> query.filter(food__breakfast="waffles")
    [Restaurant(place='Chicago suburbs',
        city='Elmhurst',
        state='Illinois',
        food=Food(fruit=['apple', 'cantelope'], breakfast='waffles'))]

    >>> query.filter(food__breakfast="waffles")[0].city
    'Elmhurst'

    >>> query.filter(food__breakfast="non_existent")
    []
    """

    data: Sequence[T]
    pk_key: str | None

    def __init__(self, items: Iterable[T] | None = None) -> None:
        super().__init__(items if items is not None else [])

    def items(self) -> list[tuple[str, T]]:
        if self.pk_key is None:
            raise PKRequiredException
        return [(getattr(item, self.pk_key), item) for item in self]

    def __eq__(
        self,
        other: object,
    ) -> bool:
        data = other

        if not isinstance(data, list):
            return False

        if len(self) == len(data):
            for a, b in zip(self, data, strict=False):
                if isinstance(a, Mapping):
                    if not isinstance(b, Mapping):
                        return False
                    a_keys = a.keys()
                    if a.keys == b.keys():
                        for key in a_keys:
                            if abs(a[key] - b[key]) > 1:
                                return False
                elif a != b:
                    return False

            return True
        return False

    def filter(
        self,
        matcher: Callable[[T], bool] | list[T] | T | None = None,
        /,
        **kwargs: object,
    ) -> QueryList[T]:
        """Filter list of objects."""

        def filter_lookup(obj: T) -> bool:
            for path, v in kwargs.items():
                try:
                    lhs, op = path.rsplit("__", 1)

                    if op not in LOOKUP_NAME_MAP:
                        raise OpNotFound(op=op)
                except ValueError:
                    lhs = path
                    op = "exact"

                assert op in LOOKUP_NAME_MAP
                path = lhs
                data = keygetter(obj, path)

                if data is None or not LOOKUP_NAME_MAP[op](data, v):
                    return False

            return True

        if callable(matcher):

            def call_match(obj: T) -> bool:
                return bool(matcher(obj))

            filter_: Callable[[T], bool] = call_match
        elif matcher is not None:

            def val_match(obj: T) -> bool:
                if isinstance(matcher, list):
                    return obj in matcher
                return bool(obj == matcher)

            filter_ = val_match
        else:
            filter_ = filter_lookup

        return self.__class__(k for k in self if filter_(k))

    @t.overload
    def get(
        self,
        matcher: Callable[[T], bool] | list[T] | T | None = None,
        /,
        *,
        default: _DefaultT,
        **kwargs: object,
    ) -> T | _DefaultT: ...

    @t.overload
    def get(
        self,
        matcher: Callable[[T], bool] | list[T] | T | None,
        /,
        default: _DefaultT,
        **kwargs: object,
    ) -> T | _DefaultT: ...

    @t.overload
    def get(
        self,
        matcher: Callable[[T], bool] | list[T] | T | None = None,
        /,
        **kwargs: object,
    ) -> T | None: ...

    def get(
        self,
        matcher: Callable[[T], bool] | list[T] | T | None = None,
        /,
        default: object = no_arg,
        **kwargs: object,
    ) -> object:
        """Retrieve exactly one object.

        Parameters
        ----------
        matcher : :class:`~collections.abc.Callable` or object, optional
            Same matcher :meth:`filter` takes.
        default : object, optional
            Returned instead of raising when *nothing* matches.
        **kwargs : object
            Lookups, as passed to :meth:`filter`.

        Returns
        -------
        object
            The single match, or *default* when there is no match and one was
            given.

        Raises
        ------
        :exc:`~libtmux.exc.ObjectDoesNotExist`
            When nothing matches and no *default* was passed.
        :exc:`~libtmux.exc.MultipleObjectsReturned`
            When more than one object matches. A *default* does not suppress
            this: it stands in for an object that is absent, and an ambiguous
            lookup is not an absent one.

        Examples
        --------
        >>> from libtmux._internal.query_list import QueryList
        >>> from libtmux import exc
        >>> qs = QueryList([{"pane_id": "%0"}, {"pane_id": "%0"}, {"pane_id": "%1"}])

        >>> qs.get(pane_id="%1")
        {'pane_id': '%1'}

        A lookup that matches nothing says what it went looking for:

        >>> try:
        ...     qs.get(pane_id="%9")
        ... except exc.ObjectDoesNotExist as e:
        ...     print(e)
        No objects found: pane_id='%9'

        >>> qs.get(pane_id="%9", default=None) is None
        True

        A lookup that matches several says how many, and for what:

        >>> try:
        ...     qs.get(pane_id="%0")
        ... except exc.MultipleObjectsReturned as e:
        ...     print(e)
        Multiple objects returned (2): pane_id='%0'
        """
        objs = self.filter(matcher, **kwargs)
        if len(objs) > 1:
            raise MultipleObjectsReturned(count=len(objs), query=kwargs)
        if len(objs) == 0:
            if default is no_arg:
                raise ObjectDoesNotExist(query=kwargs)
            return default
        return objs[0]
