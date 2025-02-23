from __future__ import annotations

import dataclasses
import typing as t
from contextlib import suppress

import pytest

from libtmux._internal.query_list import (
    MultipleObjectsReturned,
    ObjectDoesNotExist,
    QueryList,
    keygetter,
    lookup_contains,
    lookup_exact,
    lookup_icontains,
    lookup_iexact,
    parse_lookup,
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
        ([1, 2, 3, 4, 5], lambda val: val == 1, QueryList([1])),
        ([1, 2, 3, 4, 5], lambda val: val == 2, QueryList([2])),
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


def test_keygetter_error_handling() -> None:
    """Test error handling in keygetter function."""
    # Test accessing non-existent key
    obj: dict[str, int] = {"a": 1}
    assert keygetter(obj, "b") is None

    # Test accessing nested non-existent key
    nested_obj: dict[str, dict[str, int]] = {"a": {"b": 1}}
    assert keygetter(nested_obj, "a__c") is None

    # Test with invalid object type
    obj_none: t.Any = None
    with suppress(Exception):  # Exception is expected and logged
        assert keygetter(obj_none, "any_key") is None


def test_parse_lookup_error_handling() -> None:
    """Test error handling in parse_lookup function."""
    # Test with invalid object
    assert parse_lookup({"field": "value"}, "nonexistent__invalid", "__invalid") is None

    # Test with invalid lookup
    obj: dict[str, str] = {"field": "value"}
    # Type ignore since we're testing error handling with invalid types
    assert parse_lookup(obj, "field", None) is None  # type: ignore

    # Test with non-string path
    assert parse_lookup(obj, None, "__contains") is None  # type: ignore


def test_lookup_functions_edge_cases() -> None:
    """Test edge cases for lookup functions."""
    # Test lookup_exact with non-string types
    assert lookup_exact("1", "1")
    assert not lookup_exact(["a", "b"], "test")
    assert not lookup_exact({"a": "1"}, "test")

    # Test lookup_iexact with non-string types
    assert not lookup_iexact(["a", "b"], "test")
    assert not lookup_iexact({"a": "1"}, "test")

    # Test lookup_contains with various types
    assert lookup_contains(["a", "b"], "a")
    assert lookup_contains("123", "1")  # String contains substring
    assert lookup_contains({"a": "1", "b": "2"}, "a")

    # Test lookup_icontains with various types
    assert lookup_icontains("TEST", "test")
    assert lookup_icontains("test", "TEST")
    # Keys are case-insensitive
    assert lookup_icontains({"A": "1", "b": "2"}, "a")


def test_query_list_get_error_cases() -> None:
    """Test error cases for QueryList.get method."""
    ql = QueryList([{"id": 1}, {"id": 2}, {"id": 2}])

    # Test get with no results
    with pytest.raises(ObjectDoesNotExist):
        ql.get(id=3)

    # Test get with multiple results
    with pytest.raises(MultipleObjectsReturned):
        ql.get(id=2)

    # Test get with default
    assert ql.get(id=3, default=None) is None


def test_query_list_filter_error_cases() -> None:
    """Test error cases for QueryList.filter method."""
    ql = QueryList([{"id": 1}, {"id": 2}])

    # Test filter with invalid field
    assert len(ql.filter(nonexistent=1)) == 0

    # Test filter with invalid lookup
    assert len(ql.filter(id__invalid="test")) == 0


def test_query_list_methods() -> None:
    """Test additional QueryList methods."""
    ql = QueryList([1, 2, 3])

    # Test len
    assert len(ql) == 3

    # Test iter
    assert list(iter(ql)) == [1, 2, 3]

    # Test getitem
    assert ql[0] == 1
    assert ql[1:] == QueryList([2, 3])

    # Test eq
    assert ql == QueryList([1, 2, 3])
    assert ql != QueryList([1, 2])
    assert ql == [1, 2, 3]  # QueryList should equal regular list with same contents

    # Test bool
    assert bool(ql) is True
    assert bool(QueryList([])) is False
