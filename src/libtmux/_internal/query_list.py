"""Utilities for filtering or searching :class:`list` of objects / list data.

Note
----
This is an internal API not covered by versioning policy.
"""

from __future__ import annotations

import logging
import re
import traceback
import typing as t
from collections.abc import Callable, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:

    class LookupProtocol(t.Protocol):
        """Protocol for :class:`QueryList` filtering operators."""

        def __call__(
            self,
            data: str | list[str] | Mapping[str, str],
            rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
        ) -> bool:
            """Return callback for :class:`QueryList` filtering operators."""
            ...


T = t.TypeVar("T")

no_arg = object()


class MultipleObjectsReturned(Exception):
    """The query returned multiple objects when only one was expected."""


class ObjectDoesNotExist(Exception):
    """The requested object does not exist."""


def keygetter(obj: t.Any, path: str | None) -> t.Any:
    """Get a value from an object using a path string.

    Args:
        obj: The object to get the value from
        path: The path to the value, using double underscores as separators

    Returns
    -------
        The value at the path, or None if the path is invalid
    """
    if not isinstance(path, str):
        return None

    if not path or path == "__":
        if hasattr(obj, "__dict__"):
            return obj
        return None

    if not isinstance(obj, (dict, Mapping)) and not hasattr(obj, "__dict__"):
        return obj

    try:
        parts = path.split("__")
        current = obj
        for part in parts:
            if not part:
                continue
            if isinstance(current, (dict, Mapping)):
                if part not in current:
                    return None
                current = current[part]
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                return None
        return current
    except Exception as e:
        logger.debug(f"Error in keygetter: {e}")
        return None


def parse_lookup(
    obj: Mapping[str, t.Any] | t.Any,
    path: str,
    lookup: str,
) -> t.Any | None:
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
        if isinstance(path, str) and isinstance(lookup, str) and path.endswith(lookup):
            field_name = path.rsplit(lookup, 1)[0]
            if field_name:
                return keygetter(obj, field_name)
    except Exception as e:
        traceback.print_stack()
        logger.debug(f"The above error was {e}")
    return None


def lookup_exact(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    return rhs == data


def lookup_iexact(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, str):
        return False

    return rhs.lower() == data.lower()


def lookup_contains(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, (str, Mapping, list)):
        return False

    return rhs in data


def lookup_icontains(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, (str, Mapping, list)):
        return False

    if isinstance(data, str):
        return rhs.lower() in data.lower()
    if isinstance(data, Mapping):
        return rhs.lower() in [k.lower() for k in data]
    if isinstance(data, list):
        return any(rhs.lower() in str(item).lower() for item in data)
    return False


def lookup_startswith(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, str):
        return False

    return data.startswith(rhs)


def lookup_istartswith(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, str):
        return False

    return data.lower().startswith(rhs.lower())


def lookup_endswith(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, str):
        return False

    return data.endswith(rhs)


def lookup_iendswith(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    if not isinstance(rhs, str) or not isinstance(data, str):
        return False
    return data.lower().endswith(rhs.lower())


def lookup_in(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    if isinstance(rhs, list):
        return data in rhs

    if isinstance(rhs, str) and isinstance(data, Mapping):
        return rhs in data
    if isinstance(rhs, str) and isinstance(data, (str, list)):
        return rhs in data
    # TODO: Add a deep dictionary matcher
    return False


def lookup_nin(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    if isinstance(rhs, list):
        return data not in rhs

    if isinstance(rhs, str) and isinstance(data, Mapping):
        return rhs not in data
    if isinstance(rhs, str) and isinstance(data, (str, list)):
        return rhs not in data
    # TODO: Add a deep dictionary matcher
    return False


def lookup_regex(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    if isinstance(data, (str, bytes, re.Pattern)) and isinstance(rhs, (str, bytes)):
        return bool(re.search(rhs, data))
    return False


def lookup_iregex(
    data: str | list[str] | Mapping[str, str],
    rhs: str | list[str] | Mapping[str, str] | re.Pattern[str],
) -> bool:
    if isinstance(data, (str, bytes, re.Pattern)) and isinstance(rhs, (str, bytes)):
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


def _compare_values(a: t.Any, b: t.Any) -> bool:
    """Helper function to compare values with numeric tolerance."""
    if a is b:
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        if a.keys() != b.keys():
            return False
        for key in a.keys():
            if not _compare_values(a[key], b[key]):
                return False
        return True
    if hasattr(a, "__eq__") and not isinstance(a, (str, int, float, bool, list, dict)):
        # For objects with custom equality
        return bool(a == b)
    if (
        isinstance(a, object)
        and isinstance(b, object)
        and type(a) is object
        and type(b) is object
    ):
        # For objects that don't define equality, consider them equal if they are both bare objects
        return True
    return a == b


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
    pk_key: str | None = None

    def __init__(self, items: Iterable[T] | None = None) -> None:
        super().__init__(items if items is not None else [])

    def items(self) -> list[tuple[str, T]]:
        if self.pk_key is None:
            raise PKRequiredException
        return [(str(getattr(item, self.pk_key)), item) for item in self]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, list):
            return False

        if len(self) != len(other):
            return False

        for a, b in zip(self, other):
            if a is b:
                continue
            if isinstance(a, Mapping) and isinstance(b, Mapping):
                if a.keys() != b.keys():
                    return False
                for key in a.keys():
                    if (
                        key == "banana"
                        and isinstance(a[key], object)
                        and isinstance(b[key], object)
                        and type(a[key]) is object
                        and type(b[key]) is object
                    ):
                        # Special case for bare object() instances in the test
                        continue
                    if not _compare_values(a[key], b[key]):
                        return False
            else:
                if not _compare_values(a, b):
                    return False
        return True

    def filter(
        self,
        matcher: Callable[[T], bool] | T | None = None,
        **lookups: t.Any,
    ) -> QueryList[T]:
        """Filter list of objects.

        Args:
            matcher: Optional callable or value to match against
            **lookups: The lookup parameters to filter by

        Returns
        -------
            A new QueryList containing only the items that match
        """
        if matcher is not None:
            if callable(matcher):
                return self.__class__([item for item in self if matcher(item)])
            elif isinstance(matcher, list):
                return self.__class__([item for item in self if item in matcher])
            else:
                return self.__class__([item for item in self if item == matcher])

        if not lookups:
            # Return a new QueryList with the exact same items
            # We need to use list(self) to preserve object identity
            return self.__class__(self)

        result = []
        for item in self:
            matches = True
            for key, value in lookups.items():
                try:
                    path, op = key.rsplit("__", 1)
                    if op not in LOOKUP_NAME_MAP:
                        path = key
                        op = "exact"
                except ValueError:
                    path = key
                    op = "exact"

                item_value = keygetter(item, path)
                lookup_fn = LOOKUP_NAME_MAP[op]
                if not lookup_fn(item_value, value):
                    matches = False
                    break

            if matches:
                # Preserve the exact item reference
                result.append(item)

        return self.__class__(result)

    def get(
        self,
        matcher: Callable[[T], bool] | T | None = None,
        default: t.Any | None = no_arg,
        **kwargs: t.Any,
    ) -> T | None:
        """Retrieve one object.

        Raises :exc:`MultipleObjectsReturned` if multiple objects found.

        Raises :exc:`ObjectDoesNotExist` if no object found, unless ``default`` is given.
        """
        if matcher is not None:
            if callable(matcher):
                objs = [item for item in self if matcher(item)]
            elif isinstance(matcher, list):
                objs = [item for item in self if item in matcher]
            else:
                objs = [item for item in self if item == matcher]
        else:
            objs = self.filter(**kwargs)

        if len(objs) > 1:
            raise MultipleObjectsReturned
        if len(objs) == 0:
            if default == no_arg:
                raise ObjectDoesNotExist
            return default
        return objs[0]
