import dataclasses
import typing as t

import pytest

from libtmux._internal.query_list import (
    MultipleObjectsReturned,
    ObjectDoesNotExist,
    QueryList,
)


@dataclasses.dataclass
class Obj:
    test: int
    fruit: t.List[str] = dataclasses.field(default_factory=list)


@pytest.mark.parametrize(
    "items,filter_expr,expected_result",
    [
        [[Obj(test=1)], None, [Obj(test=1)]],
        [[Obj(test=1)], {"test": 1}, [Obj(test=1)]],
        [[Obj(test=1)], {"test": 2}, []],
        [
            [Obj(test=2, fruit=["apple"])],
            {"fruit__in": "apple"},
            QueryList([Obj(test=2, fruit=["apple"])]),
        ],
        [[{"test": 1}], None, [{"test": 1}]],
        [[{"test": 1}], None, QueryList([{"test": 1}])],
        [[{"fruit": "apple"}], None, QueryList([{"fruit": "apple"}])],
        [
            [{"fruit": "apple", "banana": object()}],
            None,
            QueryList([{"fruit": "apple", "banana": object()}]),
        ],
        [
            [{"fruit": "apple", "banana": object()}],
            {"fruit__eq": "apple"},
            QueryList([{"fruit": "apple", "banana": object()}]),
        ],
        [
            [{"fruit": "apple", "banana": object()}],
            {"fruit__eq": "notmatch"},
            QueryList([]),
        ],
        [
            [{"fruit": "apple", "banana": object()}],
            {"fruit__exact": "apple"},
            QueryList([{"fruit": "apple", "banana": object()}]),
        ],
        [
            [{"fruit": "apple", "banana": object()}],
            {"fruit__exact": "notmatch"},
            QueryList([]),
        ],
        [
            [{"fruit": "apple", "banana": object()}],
            {"fruit__iexact": "Apple"},
            QueryList([{"fruit": "apple", "banana": object()}]),
        ],
        [
            [{"fruit": "apple", "banana": object()}],
            {"fruit__iexact": "Notmatch"},
            QueryList([]),
        ],
        [
            [{"fruit": "apple", "banana": object()}],
            {"fruit": "notmatch"},
            QueryList([]),
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit": "apple"},
            [{"fruit": "apple"}],
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__in": "app"},
            [{"fruit": "apple"}],
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__icontains": "App"},
            [{"fruit": "apple"}],
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__contains": "app"},
            [{"fruit": "apple"}],
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__regex": r"app.*"},
            [{"fruit": "apple"}],
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__iregex": r"App.*"},
            [{"fruit": "apple"}],
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__startswith": "a"},
            [{"fruit": "apple"}],
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__istartswith": "AP"},
            [{"fruit": "apple"}],
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__startswith": "z"},
            [],
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__endswith": "le"},
            [{"fruit": "apple"}],
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__iendswith": "LE"},
            [{"fruit": "apple"}],
        ],
        [
            [{"fruit": "apple"}, {"fruit": "mango"}],
            {"fruit__endswith": "z"},
            [],
        ],
        [
            [
                {"fruit": "apple"},
                {"fruit": "mango"},
                {"fruit": "banana"},
                {"fruit": "kiwi"},
            ],
            {"fruit__in": ["apple", "mango"]},
            [{"fruit": "apple"}, {"fruit": "mango"}],
        ],
        [
            [
                {"fruit": "apple"},
                {"fruit": "mango"},
                {"fruit": "banana"},
                {"fruit": "kiwi"},
            ],
            {"fruit__nin": ["apple", "mango"]},
            [{"fruit": "banana"}, {"fruit": "kiwi"}],
        ],
        [
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
        ],
        [
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
        ],
        [
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
        ],
        [
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
        ],
        [[1, 2, 3, 4, 5], None, QueryList([1, 2, 3, 4, 5])],
        [[1, 2, 3, 4, 5], [1], QueryList([1])],
        [[1, 2, 3, 4, 5], [1, 4], QueryList([1, 4])],
        [[1, 2, 3, 4, 5], lambda val: val == 1, QueryList([1])],
        [[1, 2, 3, 4, 5], lambda val: val == 2, QueryList([2])],
    ],
)
def test_filter(
    items: t.List[t.Dict[str, t.Any]],
    filter_expr: t.Optional[t.Union[t.Callable[[t.Any], bool], t.Any]],
    expected_result: t.Union[QueryList[t.Any], t.List[t.Dict[str, t.Any]]],
) -> None:
    qs = QueryList(items)
    if filter_expr is not None:
        if isinstance(filter_expr, dict):
            assert qs.filter(**filter_expr) == expected_result
        else:
            assert qs.filter(filter_expr) == expected_result
    else:
        assert qs.filter() == expected_result

    if (
        isinstance(expected_result, list)
        and len(expected_result) > 0
        and not isinstance(expected_result[0], dict)
    ):
        if len(expected_result) == 1:
            if isinstance(filter_expr, dict):
                assert qs.get(**filter_expr) == expected_result[0]
            else:
                assert qs.get(filter_expr) == expected_result[0]
        elif len(expected_result) > 1:
            with pytest.raises(MultipleObjectsReturned) as e:
                if isinstance(filter_expr, dict):
                    assert qs.get(**filter_expr) == expected_result
                else:
                    assert qs.get(filter_expr) == expected_result
                assert e.match("Multiple objects returned")
        elif len(expected_result) == 0:
            with pytest.raises(ObjectDoesNotExist) as exc:
                if isinstance(filter_expr, dict):
                    assert qs.get(**filter_expr) == expected_result
                else:
                    assert qs.get(filter_expr) == expected_result
            assert exc.match("No objects found")
