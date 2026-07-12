from __future__ import annotations

import dataclasses
import typing as t

import pytest

from libtmux._internal.query_list import (
    MultipleObjectsReturned,
    ObjectDoesNotExist,
    QueryList,
)

if t.TYPE_CHECKING:
    from collections.abc import Callable


@dataclasses.dataclass
class Obj:
    test: int
    fruit: list[str] = dataclasses.field(default_factory=list)


@pytest.mark.parametrize(
    ("items", "filter_expr", "expected_result"),
    [
        ([Obj(test=1)], None, [Obj(test=1)]),
        ([Obj(test=1)], {"test": 1}, [Obj(test=1)]),
        ([Obj(test=1)], {"test": 2}, []),
        (
            [Obj(test=2, fruit=["apple"])],
            {"fruit__in": "apple"},
            QueryList([Obj(test=2, fruit=["apple"])]),
        ),
        ([{"test": 1}], None, [{"test": 1}]),
        ([{"test": 1}], None, QueryList([{"test": 1}])),
        ([{"fruit": "apple"}], None, QueryList([{"fruit": "apple"}])),
        (
            [{"fruit": "apple", "banana": object()}],
            None,
            QueryList([{"fruit": "apple", "banana": object()}]),
        ),
        (
            [{"fruit": "apple", "banana": object()}],
            {"fruit__eq": "apple"},
            QueryList([{"fruit": "apple", "banana": object()}]),
        ),
        (
            [{"fruit": "apple", "banana": object()}],
            {"fruit__eq": "notmatch"},
            QueryList([]),
        ),
        (
            [{"fruit": "apple", "banana": object()}],
            {"fruit__exact": "apple"},
            QueryList([{"fruit": "apple", "banana": object()}]),
        ),
        (
            [{"fruit": "apple", "banana": object()}],
            {"fruit__exact": "notmatch"},
            QueryList([]),
        ),
        (
            [{"fruit": "apple", "banana": object()}],
            {"fruit__iexact": "Apple"},
            QueryList([{"fruit": "apple", "banana": object()}]),
        ),
        (
            [{"fruit": "apple", "banana": object()}],
            {"fruit__iexact": "Notmatch"},
            QueryList([]),
        ),
        (
            [{"fruit": "apple", "banana": object()}],
            {"fruit": "notmatch"},
            QueryList([]),
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit": "apple"},
            [{"fruit": "apple"}],
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__in": "app"},
            [{"fruit": "apple"}],
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__icontains": "App"},
            [{"fruit": "apple"}],
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__contains": "app"},
            [{"fruit": "apple"}],
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__regex": r"app.*"},
            [{"fruit": "apple"}],
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__iregex": r"App.*"},
            [{"fruit": "apple"}],
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__startswith": "a"},
            [{"fruit": "apple"}],
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__istartswith": "AP"},
            [{"fruit": "apple"}],
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__startswith": "z"},
            [],
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__endswith": "le"},
            [{"fruit": "apple"}],
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__iendswith": "LE"},
            [{"fruit": "apple"}],
        ),
        (
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__endswith": "z"},
            [],
        ),
        (
            [
                {"fruit": "apple"},
                {"fruit": "mango"},
                {"fruit": "banana"},
                {"fruit": "kiwi"},
            ],
            {"fruit__in": ["apple", "mango"]},
            [{"fruit": "apple"}, {"fruit": "mango"}],
        ),
        (
            [
                {"fruit": "apple"},
                {"fruit": "mango"},
                {"fruit": "banana"},
                {"fruit": "kiwi"},
            ],
            {"fruit__nin": ["apple", "mango"]},
            [{"fruit": "banana"}, {"fruit": "kiwi"}],
        ),
        (
            [
                {"place": "book store", "city": "Tampa", "state": "Florida"},
                {"place": "coffee shop", "city": "Tampa", "state": "Florida"},
                {
                    "place": "chinese restaurant",
                    "city": "ybor city",
                    "state": "Florida",
                },
                {
                    "place": "walt disney world",
                    "city": "Lake Buena Vista",
                    "state": "Florida",
                },
            ],
            {"city": "Tampa", "state": "Florida"},
            [
                {"place": "book store", "city": "Tampa", "state": "Florida"},
                {"place": "coffee shop", "city": "Tampa", "state": "Florida"},
            ],
        ),
        (
            [
                {"place": "book store", "city": "Tampa", "state": "Florida"},
                {"place": "coffee shop", "city": "Tampa", "state": "Florida"},
                {
                    "place": "chinese restaurant",
                    "city": "ybor city",
                    "state": "Florida",
                },
                {
                    "place": "walt disney world",
                    "city": "Lake Buena Vista",
                    "state": "Florida",
                },
            ],
            {"place__contains": "coffee", "state": "Florida"},
            [
                {"place": "coffee shop", "city": "Tampa", "state": "Florida"},
            ],
        ),
        (
            [
                {
                    "place": "Largo",
                    "city": "Tampa",
                    "state": "Florida",
                    "foods": {"fruit": ["banana", "orange"], "breakfast": "cereal"},
                },
                {
                    "place": "Chicago suburbs",
                    "city": "Elmhurst",
                    "state": "Illinois",
                    "foods": {"fruit": ["apple", "cantelope"], "breakfast": "waffles"},
                },
            ],
            {"foods__fruit__contains": "banana"},
            [
                {
                    "place": "Largo",
                    "city": "Tampa",
                    "state": "Florida",
                    "foods": {"fruit": ["banana", "orange"], "breakfast": "cereal"},
                },
            ],
        ),
        (
            [
                {
                    "place": "Largo",
                    "city": "Tampa",
                    "state": "Florida",
                    "foods": {"fruit": ["banana", "orange"], "breakfast": "cereal"},
                },
                {
                    "place": "Chicago suburbs",
                    "city": "Elmhurst",
                    "state": "Illinois",
                    "foods": {"fruit": ["apple", "cantelope"], "breakfast": "waffles"},
                },
            ],
            {"foods__breakfast": "cereal"},
            [
                {
                    "place": "Largo",
                    "city": "Tampa",
                    "state": "Florida",
                    "foods": {"fruit": ["banana", "orange"], "breakfast": "cereal"},
                },
            ],
        ),
        ([1, 2, 3, 4, 5], None, QueryList([1, 2, 3, 4, 5])),
        ([1, 2, 3, 4, 5], [1], QueryList([1])),
        ([1, 2, 3, 4, 5], [1, 4], QueryList([1, 4])),
        ([1, 2, 3, 4, 5], [9], QueryList([])),
        ([1, 2, 3, 4, 5], lambda val: val == 1, QueryList([1])),
        ([1, 2, 3, 4, 5], lambda val: val == 2, QueryList([2])),
        ([1, 2, 3, 4, 5], lambda val: val == 9, QueryList([])),
    ],
)
def test_filter(
    items: list[dict[str, t.Any]],
    filter_expr: Callable[[t.Any], bool] | t.Any | None,
    expected_result: QueryList[t.Any] | list[dict[str, t.Any]],
) -> None:
    qs = QueryList(items)
    if filter_expr is not None:
        if isinstance(filter_expr, dict):
            assert qs.filter(**filter_expr) == expected_result
        else:
            assert qs.filter(filter_expr) == expected_result
    else:
        assert qs.filter() == expected_result

    if not isinstance(expected_result, list):
        return

    # ``get()`` insists on exactly one match. Assert the message too: an
    # exception nobody can read is the defect, not just the raise.
    if len(expected_result) == 0:
        with pytest.raises(ObjectDoesNotExist) as missing:
            if isinstance(filter_expr, dict):
                qs.get(**filter_expr)
            else:
                qs.get(filter_expr)
        assert missing.match("No objects found")
        return

    if isinstance(expected_result[0], dict):
        return

    if len(expected_result) == 1:
        if isinstance(filter_expr, dict):
            assert qs.get(**filter_expr) == expected_result[0]
        else:
            assert qs.get(filter_expr) == expected_result[0]
    else:
        with pytest.raises(MultipleObjectsReturned) as multiple:
            if isinstance(filter_expr, dict):
                qs.get(**filter_expr)
            else:
                qs.get(filter_expr)
        assert multiple.match("Multiple objects returned")


def test_get_multiple_objects_exposes_ambiguity_data() -> None:
    query: dict[str, t.Any] = {"fruit": "apple"}
    qs = QueryList([query, query])

    with pytest.raises(MultipleObjectsReturned) as multiple:
        qs.get(**query)

    assert multiple.value.count == 2
    assert multiple.value.query == query


def test_query_exception_annotations_resolve() -> None:
    """Runtime introspection resolves the query annotations."""
    for initializer in (
        ObjectDoesNotExist.__init__,
        MultipleObjectsReturned.__init__,
    ):
        assert "query" in t.get_type_hints(initializer)


def test_get_default_with_broad_eq_is_returned() -> None:
    """A default whose ``__eq__`` is non-identity is returned, not raised.

    ``get`` guards the "nothing matched" branch with the ``no_arg`` sentinel.
    Comparing the default to it with ``==`` rather than ``is`` misfires when the
    default answers ``__eq__`` truthily to an unrelated object.
    """

    class BroadEq:
        def __eq__(self, other: object) -> bool:
            return True

        __hash__ = None  # type: ignore[assignment]

    default = BroadEq()
    assert QueryList([]).get(missing="x", default=default) is default
