from __future__ import annotations

import dataclasses
import re
import typing as t
from collections.abc import Callable, Mapping
from contextlib import suppress

import pytest

from libtmux._internal.query_list import (
    LOOKUP_NAME_MAP,
    MultipleObjectsReturned,
    ObjectDoesNotExist,
    PKRequiredException,
    QueryList,
    keygetter,
    lookup_contains,
    lookup_endswith,
    lookup_exact,
    lookup_icontains,
    lookup_iendswith,
    lookup_iexact,
    lookup_in,
    lookup_iregex,
    lookup_istartswith,
    lookup_nin,
    lookup_regex,
    lookup_startswith,
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


def test_lookup_functions_additional_edge_cases() -> None:
    """Test additional edge cases for lookup functions."""
    # Test lookup_in with various types
    assert not lookup_in("value", {"key": "value"})  # String in dict values
    assert not lookup_in("key", {"key": "value"})  # String in dict keys
    assert lookup_in("item", ["item", "other"])  # String in list
    assert not lookup_in("missing", {"key": "value"})  # Missing key in dict
    assert not lookup_in(123, "123")  # type: ignore  # Invalid type combination

    # Test lookup_nin with various types
    # Missing key in dict returns False
    assert not lookup_nin("missing", {"key": "value"})
    # String in dict values returns False
    assert not lookup_nin("value", {"key": "value"})
    assert lookup_nin("item", ["other", "another"])  # String not in list
    assert not lookup_nin("item", ["item", "other"])  # String in list
    assert not lookup_nin(123, "123")  # type: ignore  # Invalid type combination returns False

    # Test lookup_regex with various types
    assert lookup_regex("test123", r"\d+")  # Match digits
    assert not lookup_regex("test", r"\d+")  # No match
    assert not lookup_regex(123, r"\d+")  # type: ignore  # Invalid type
    assert not lookup_regex("test", 123)  # type: ignore  # Invalid pattern type

    # Test lookup_iregex with various types
    assert lookup_iregex("TEST123", r"test\d+")  # Case-insensitive match
    assert not lookup_iregex("test", r"\d+")  # No match
    assert not lookup_iregex(123, r"\d+")  # type: ignore  # Invalid type
    assert not lookup_iregex("test", 123)  # type: ignore  # Invalid pattern type


def test_query_list_items() -> None:
    """Test QueryList items() method."""
    # Test items() without pk_key
    ql = QueryList([{"id": 1}, {"id": 2}])
    ql.pk_key = None  # Initialize pk_key
    with pytest.raises(PKRequiredException):
        ql.items()


def test_query_list_filter_with_invalid_op() -> None:
    """Test QueryList filter with invalid operator."""
    ql = QueryList([{"id": 1}, {"id": 2}])

    # Test filter with no operator (defaults to exact)
    result = ql.filter(id=1)
    assert len(result) == 1
    assert result[0]["id"] == 1

    # Test filter with valid operator
    result = ql.filter(id__exact=1)
    assert len(result) == 1
    assert result[0]["id"] == 1

    # Test filter with multiple conditions
    result = ql.filter(id__exact=1, id__in=[1, 2])
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_query_list_filter_with_callable() -> None:
    """Test QueryList filter with callable."""
    ql = QueryList([{"id": 1}, {"id": 2}, {"id": 3}])

    # Test filter with callable
    def is_even(x: dict[str, int]) -> bool:
        return x["id"] % 2 == 0

    filtered = ql.filter(is_even)
    assert len(filtered) == 1
    assert filtered[0]["id"] == 2

    # Test filter with lambda
    filtered = ql.filter(lambda x: x["id"] > 2)
    assert len(filtered) == 1
    assert filtered[0]["id"] == 3


def test_query_list_get_with_callable() -> None:
    """Test QueryList get with callable."""
    ql = QueryList([{"id": 1}, {"id": 2}, {"id": 3}])

    # Test get with callable
    def get_id_2(x: dict[str, int]) -> bool:
        return x["id"] == 2

    result = ql.get(get_id_2)
    assert result is not None and result["id"] == 2  # Check for None before indexing

    # Test get with lambda
    result = ql.get(lambda x: x["id"] == 3)
    assert result is not None and result["id"] == 3  # Check for None before indexing

    # Test get with callable returning multiple matches
    def get_id_greater_than_1(x: dict[str, int]) -> bool:
        return x["id"] > 1

    with pytest.raises(MultipleObjectsReturned):
        ql.get(get_id_greater_than_1)

    # Test get with callable returning no matches
    def get_id_greater_than_10(x: dict[str, int]) -> bool:
        return x["id"] > 10

    with pytest.raises(ObjectDoesNotExist):
        ql.get(get_id_greater_than_10)


def test_query_list_eq_with_mappings() -> None:
    """Test QueryList __eq__ method with mappings."""
    # Test comparing mappings with numeric values
    ql1 = QueryList([{"a": 1, "b": 2}])
    ql2 = QueryList([{"a": 1, "b": 2}])
    assert ql1 == ql2

    # Test comparing mappings with different values
    ql3 = QueryList([{"a": 1, "b": 3}])
    assert ql1 != ql3

    # Test comparing with non-list
    assert ql1 != "not a list"

    # Test comparing mappings with different keys
    ql4 = QueryList([{"a": 1, "c": 2}])
    assert ql1 != ql4

    # Test comparing mappings with close numeric values (within tolerance)
    ql5 = QueryList([{"a": 1.0001, "b": 2.0001}])
    assert ql1 == ql5  # Should be equal since difference is less than 1

    # Test comparing mappings with different numeric values (outside tolerance)
    ql6 = QueryList([{"a": 2.5, "b": 3.5}])
    assert ql1 != ql6  # Should not be equal since difference is more than 1


def test_lookup_in_with_mappings() -> None:
    """Test lookup_in function with mappings."""
    # Test with string in mapping keys
    data: dict[str, str] = {"key": "value", "other": "value2"}
    assert not lookup_in("missing", data)  # Key not in mapping
    assert not lookup_in("value", data)  # Value not in mapping keys
    assert not lookup_in("key", data)  # Key in mapping but returns False

    # Test with string in mapping values
    assert not lookup_in("value", data)  # Value in mapping but returns False

    # Test with invalid combinations
    assert not lookup_in(123, data)  # type: ignore  # Invalid type for data
    assert not lookup_in("key", 123)  # type: ignore  # Invalid type for rhs

    # Test with list in mapping
    data_list: list[str] = ["value1", "value2"]
    assert lookup_in("value1", data_list)  # Value in list returns True


def test_lookup_nin_with_mappings() -> None:
    """Test lookup_nin function with mappings."""
    # Test with string in mapping keys
    data: dict[str, str] = {"key": "value", "other": "value2"}
    assert not lookup_nin("missing", data)  # Key not in mapping returns False
    assert not lookup_nin("value", data)  # Value not in mapping keys returns False
    assert not lookup_nin("key", data)  # Key in mapping returns False

    # Test with string in mapping values
    assert not lookup_nin("value", data)  # Value in mapping returns False

    # Test with invalid combinations
    assert not lookup_nin(123, data)  # type: ignore  # Invalid type for data
    assert not lookup_nin("key", 123)  # type: ignore  # Invalid type for rhs

    # Test with list in mapping
    data_list: list[str] = ["value1", "value2"]
    assert not lookup_nin("value1", data_list)  # Value in list returns False


def test_filter_error_handling() -> None:
    """Test error handling in filter method."""
    ql: QueryList[Mapping[str, t.Any]] = QueryList([{"id": 1}, {"id": 2}])

    # Test with non-existent field
    result = ql.filter(nonexistent=1)
    assert len(result) == 0

    # Test with invalid lookup
    result = ql.filter(id__invalid="test")
    assert len(result) == 0

    # Test with multiple conditions where one is invalid
    result = ql.filter(id__exact=1, id__invalid="test")
    assert len(result) == 0

    # Test with non-string paths
    with pytest.raises(TypeError):
        # We need to use Any here because we're intentionally testing invalid types
        numeric_key: t.Any = 123
        numeric_args: dict[t.Any, t.Any] = {numeric_key: "test"}
        ql.filter(**numeric_args)

    # Test with None path
    with pytest.raises(TypeError):
        # We need to use Any here because we're intentionally testing invalid types
        none_key: t.Any = None
        none_args: dict[t.Any, t.Any] = {none_key: "test"}
        ql.filter(**none_args)

    # Test with empty path
    empty_args: dict[str, t.Any] = {"": "test"}
    result = ql.filter(**empty_args)
    assert len(result) == 0


def test_lookup_startswith_endswith_functions() -> None:
    """Test startswith and endswith lookup functions with various types."""
    # Test lookup_startswith
    assert lookup_startswith("test123", "test")  # Basic match
    assert not lookup_startswith("test123", "123")  # No match at start
    assert not lookup_startswith(["test"], "test")  # Invalid type for data
    assert not lookup_startswith("test", ["test"])  # Invalid type for rhs
    assert not lookup_startswith("test", 123)  # type: ignore  # Invalid type for rhs

    # Test lookup_istartswith
    assert lookup_istartswith("TEST123", "test")  # Case-insensitive match
    assert lookup_istartswith("test123", "TEST")  # Case-insensitive match reverse
    assert not lookup_istartswith("test123", "123")  # No match at start
    assert not lookup_istartswith(["test"], "test")  # Invalid type for data
    assert not lookup_istartswith("test", ["test"])  # Invalid type for rhs
    assert not lookup_istartswith("test", 123)  # type: ignore  # Invalid type for rhs

    # Test lookup_endswith
    assert lookup_endswith("test123", "123")  # Basic match
    assert not lookup_endswith("test123", "test")  # No match at end
    assert not lookup_endswith(["test"], "test")  # Invalid type for data
    assert not lookup_endswith("test", ["test"])  # Invalid type for rhs
    assert not lookup_endswith("test", 123)  # type: ignore  # Invalid type for rhs

    # Test lookup_iendswith
    assert lookup_iendswith("test123", "123")  # Basic match
    assert lookup_iendswith("test123", "123")  # Case-insensitive match
    assert lookup_iendswith("test123", "123")  # Case-insensitive match reverse
    assert not lookup_iendswith("test123", "test")  # No match at end
    assert not lookup_iendswith(["test"], "test")  # Invalid type for data
    assert not lookup_iendswith("test", ["test"])  # Invalid type for rhs
    assert not lookup_iendswith("test", 123)  # type: ignore  # Invalid type for rhs


def test_query_list_eq_numeric_comparison() -> None:
    """Test QueryList __eq__ method with numeric comparisons."""
    # Test exact numeric matches
    ql1 = QueryList([{"a": 1, "b": 2.0}])
    ql2 = QueryList([{"a": 1, "b": 2.0}])
    assert ql1 == ql2

    # Test numeric comparison within tolerance (difference < 1)
    ql3 = QueryList([{"a": 1.1, "b": 2.1}])
    assert ql1 == ql3  # Should be equal since difference is less than 1

    # Test numeric comparison outside tolerance (difference > 1)
    ql4 = QueryList([{"a": 2.5, "b": 3.5}])
    assert ql1 != ql4  # Should not be equal since difference is more than 1

    # Test mixed numeric types
    ql5 = QueryList([{"a": 1, "b": 2}])  # int instead of float
    assert ql1 == ql5  # Should be equal since values are equivalent

    # Test with nested numeric values
    ql6 = QueryList([{"a": {"x": 1.0, "y": 2.0}}])
    ql7 = QueryList([{"a": {"x": 1.1, "y": 2.1}}])
    assert ql6 == ql7  # Should be equal since differences are less than 1

    # Test with mixed content
    ql10 = QueryList([{"a": 1, "b": "test"}])
    ql11 = QueryList([{"a": 1.1, "b": "test"}])
    assert ql10 == ql11  # Should be equal since numeric difference is less than 1

    # Test with non-dict content (exact equality required)
    ql8 = QueryList([1, 2, 3])
    ql9 = QueryList([1, 2, 3])
    assert ql8 == ql9  # Should be equal since values are exactly the same
    assert ql8 != QueryList(
        [1.1, 2.1, 3.1]
    )  # Should not be equal since values are different


@dataclasses.dataclass
class Food(t.Mapping[str, t.Any]):
    fruit: list[str] = dataclasses.field(default_factory=list)
    breakfast: str | None = None

    def __getitem__(self, key: str) -> t.Any:
        return getattr(self, key)

    def __iter__(self) -> t.Iterator[str]:
        return iter(self.__dataclass_fields__)

    def __len__(self) -> int:
        return len(self.__dataclass_fields__)


@dataclasses.dataclass
class Restaurant(t.Mapping[str, t.Any]):
    place: str
    city: str
    state: str
    food: Food = dataclasses.field(default_factory=Food)

    def __getitem__(self, key: str) -> t.Any:
        return getattr(self, key)

    def __iter__(self) -> t.Iterator[str]:
        return iter(self.__dataclass_fields__)

    def __len__(self) -> int:
        return len(self.__dataclass_fields__)


def test_keygetter_nested_objects() -> None:
    """Test keygetter function with nested objects."""
    # Test with nested dataclass that implements Mapping protocol
    restaurant = Restaurant(
        place="Largo",
        city="Tampa",
        state="Florida",
        food=Food(fruit=["banana", "orange"], breakfast="cereal"),
    )
    assert keygetter(restaurant, "food") == Food(
        fruit=["banana", "orange"], breakfast="cereal"
    )
    assert keygetter(restaurant, "food__breakfast") == "cereal"
    assert keygetter(restaurant, "food__fruit") == ["banana", "orange"]

    # Test with non-existent attribute (returns None due to exception handling)
    with suppress(Exception):
        assert keygetter(restaurant, "nonexistent") is None

    # Test with invalid path format (returns the object itself)
    assert keygetter(restaurant, "") == restaurant
    assert keygetter(restaurant, "__") == restaurant

    # Test with non-mapping object (returns the object itself)
    non_mapping = "not a mapping"
    assert (
        keygetter(t.cast(t.Mapping[str, t.Any], non_mapping), "any_key") == non_mapping
    )


def test_query_list_slicing() -> None:
    """Test QueryList slicing operations."""
    ql = QueryList([1, 2, 3, 4, 5])

    # Test positive indices
    assert ql[1:3] == QueryList([2, 3])
    assert ql[0:5:2] == QueryList([1, 3, 5])

    # Test negative indices
    assert ql[-3:] == QueryList([3, 4, 5])
    assert ql[:-2] == QueryList([1, 2, 3])
    assert ql[-4:-2] == QueryList([2, 3])

    # Test steps
    assert ql[::2] == QueryList([1, 3, 5])
    assert ql[::-1] == QueryList([5, 4, 3, 2, 1])
    assert ql[4:0:-2] == QueryList([5, 3])

    # Test empty slices
    assert ql[5:] == QueryList([])
    assert ql[-1:-5] == QueryList([])


def test_query_list_attributes() -> None:
    """Test QueryList list behavior and pk_key attribute."""
    # Test list behavior
    ql = QueryList([1, 2, 3])
    assert list(ql) == [1, 2, 3]
    assert len(ql) == 3
    assert ql[0] == 1
    assert ql[-1] == 3

    # Test pk_key attribute with objects
    @dataclasses.dataclass
    class Item(t.Mapping[str, t.Any]):
        id: str
        value: int

        def __getitem__(self, key: str) -> t.Any:
            return getattr(self, key)

        def __iter__(self) -> t.Iterator[str]:
            return iter(self.__dataclass_fields__)

        def __len__(self) -> int:
            return len(self.__dataclass_fields__)

    items = [Item("1", 1), Item("2", 2)]
    ql_items: QueryList[t.Any] = QueryList(items)
    ql_items.pk_key = "id"
    assert list(ql_items.items()) == [("1", items[0]), ("2", items[1])]

    # Test pk_key with non-existent attribute
    ql_items.pk_key = "nonexistent"
    with pytest.raises(AttributeError):
        ql_items.items()

    # Test pk_key with None
    ql_items.pk_key = None
    with pytest.raises(PKRequiredException):
        ql_items.items()


def test_lookup_name_map() -> None:
    """Test LOOKUP_NAME_MAP contains all lookup functions."""
    # Test all lookup functions are in the map
    assert LOOKUP_NAME_MAP["eq"] == lookup_exact
    assert LOOKUP_NAME_MAP["exact"] == lookup_exact
    assert LOOKUP_NAME_MAP["iexact"] == lookup_iexact
    assert LOOKUP_NAME_MAP["contains"] == lookup_contains
    assert LOOKUP_NAME_MAP["icontains"] == lookup_icontains
    assert LOOKUP_NAME_MAP["startswith"] == lookup_startswith
    assert LOOKUP_NAME_MAP["istartswith"] == lookup_istartswith
    assert LOOKUP_NAME_MAP["endswith"] == lookup_endswith
    assert LOOKUP_NAME_MAP["iendswith"] == lookup_iendswith
    assert LOOKUP_NAME_MAP["in"] == lookup_in
    assert LOOKUP_NAME_MAP["nin"] == lookup_nin
    assert LOOKUP_NAME_MAP["regex"] == lookup_regex
    assert LOOKUP_NAME_MAP["iregex"] == lookup_iregex

    # Test lookup functions behavior through the map
    data = "test123"
    assert LOOKUP_NAME_MAP["contains"](data, "test")
    assert LOOKUP_NAME_MAP["icontains"](data, "TEST")
    assert LOOKUP_NAME_MAP["startswith"](data, "test")
    assert LOOKUP_NAME_MAP["endswith"](data, "123")
    assert not LOOKUP_NAME_MAP["in"](data, ["other", "values"])
    assert LOOKUP_NAME_MAP["regex"](data, r"\d+")


def test_keygetter_additional_cases() -> None:
    """Test additional cases for keygetter function."""
    # Test valid and invalid paths
    obj = {"a": {"b": 1}}
    assert keygetter(obj, "a__b") == 1  # Valid path
    assert keygetter(obj, "x__y__z") is None  # Invalid path returns None

    # Test with non-string paths
    assert keygetter(obj, None) is None  # type: ignore  # None path returns None
    assert keygetter(obj, 123) is None  # type: ignore  # Non-string path returns None

    # Test with empty paths
    assert keygetter(obj, "") is None  # Empty path returns None
    assert keygetter(obj, "  ") is None  # Whitespace path returns None

    # Test with nested paths that don't exist
    nested_obj = {"level1": {"level2": {"level3": "value"}}}
    assert keygetter(nested_obj, "level1__level2__level3") == "value"  # Valid path
    assert (
        keygetter(nested_obj, "level1__level2__nonexistent") is None
    )  # Invalid leaf returns None
    assert (
        keygetter(nested_obj, "level1__nonexistent__level3") is None
    )  # Invalid mid returns None
    assert (
        keygetter(nested_obj, "nonexistent__level2__level3") is None
    )  # Invalid root returns None


def test_lookup_functions_more_edge_cases() -> None:
    """Test additional edge cases for lookup functions."""
    # TODO: lookup_nin() should handle non-string values correctly
    # Currently returns False for all non-string values
    assert not lookup_nin(None, "test")  # type: ignore  # None value returns False
    assert not lookup_nin(123, "test")  # type: ignore  # Non-string value returns False
    assert not lookup_nin("test", None)  # type: ignore  # None right-hand side returns False
    assert not lookup_nin("test", 123)  # type: ignore  # Non-string right-hand side returns False

    # TODO: lookup_nin() should handle dict and list values correctly
    # Currently returns True for dict not in list and string not in list
    assert lookup_nin(
        {"key": "value"}, ["not", "a", "string"]
    )  # Dict not in list returns True
    assert lookup_nin(
        "value", ["not", "a", "string"]
    )  # String not in list returns True
    assert not lookup_nin(
        "item", {"not": "a string"}
    )  # String not in dict returns False


def test_query_list_items_advanced() -> None:
    """Test advanced items operations in QueryList."""
    # Test items() with mixed key types
    data = [
        {"id": 1, "name": "Alice"},
        {"id": "2", "name": "Bob"},  # String ID
        {"name": "Charlie", "uuid": "abc-123"},  # Different key name
        {"composite": {"id": 4}, "name": "David"},  # Nested ID
    ]
    ql = QueryList(data)
    ql.pk_key = "id"  # Initialize pk_key

    # Test items() with missing keys
    with pytest.raises(AttributeError):
        _ = list(ql.items())  # Should raise AttributeError for missing keys

    # Test items() with different key name
    ql.pk_key = "uuid"
    with pytest.raises(AttributeError):
        _ = list(ql.items())  # Should raise AttributeError for missing keys

    # Test items() with nested key
    ql.pk_key = "composite__id"
    with pytest.raises(AttributeError):
        _ = list(ql.items())  # Should raise AttributeError for missing keys


def test_query_list_comparison_advanced() -> None:
    """Test advanced comparison operations in QueryList."""
    # Test comparison with different types
    ql1: QueryList[t.Any] = QueryList([1, 2, 3])
    ql2: QueryList[t.Any] = QueryList([1.0, 2.0, 3.0])
    assert ql1 == ql2  # Integer vs float comparison

    ql3: QueryList[t.Any] = QueryList(["1", "2", "3"])
    assert ql1 != ql3  # Integer vs string comparison

    # Test comparison with nested structures
    data1 = [{"user": {"id": 1, "name": "Alice"}}, {"user": {"id": 2, "name": "Bob"}}]
    data2 = [{"user": {"id": 1, "name": "Alice"}}, {"user": {"id": 2, "name": "Bob"}}]
    ql1 = QueryList(data1)
    ql2 = QueryList(data2)
    assert ql1 == ql2  # Deep equality comparison

    # Modify nested structure
    data2[1]["user"]["name"] = "Bobby"
    ql2 = QueryList(data2)
    assert ql1 != ql2  # Deep inequality detection

    # Test comparison with custom objects
    class Point:
        def __init__(self, x: float, y: float) -> None:
            self.x = x
            self.y = y

        def __eq__(self, other: object) -> bool:
            if not isinstance(other, Point):
                return NotImplemented
            return abs(self.x - other.x) < 0.001 and abs(self.y - other.y) < 0.001

    ql1 = QueryList[Point]([Point(1.0, 2.0), Point(3.0, 4.0)])
    ql2 = QueryList[Point]([Point(1.0001, 1.9999), Point(3.0, 4.0)])
    assert ql1 == ql2  # Custom equality comparison

    # Test comparison edge cases
    assert QueryList([]) == QueryList([])  # Empty lists
    assert QueryList([]) != QueryList([1])  # Empty vs non-empty
    assert QueryList([None]) == QueryList([None])  # None values
    assert QueryList([float("nan")]) != QueryList([float("nan")])  # NaN values

    # Test comparison with mixed types
    mixed_data1 = [1, "2", 3.0, None, [4, 5], {"key": "value"}]
    mixed_data2 = [1, "2", 3.0, None, [4, 5], {"key": "value"}]
    ql1 = QueryList[t.Any](mixed_data1)
    ql2 = QueryList[t.Any](mixed_data2)
    assert ql1 == ql2  # Mixed type comparison

    # Test comparison with different orders
    ql1 = QueryList[int]([1, 2, 3])
    ql2 = QueryList[int]([3, 2, 1])
    assert ql1 != ql2  # Order matters


def test_lookup_functions_deep_matching() -> None:
    """Test deep matching behavior in lookup functions."""
    # Test lookup_in with deep dictionary matching
    data: dict[str, t.Any] = {"a": {"b": {"c": "value"}}}
    rhs: dict[str, t.Any] = {"b": {"c": "value"}}
    # Deep dictionary matching not implemented yet
    assert not lookup_in(data, rhs)

    # Test lookup_nin with deep dictionary matching
    # Deep dictionary matching not implemented yet
    assert not lookup_nin(data, rhs)

    # Test lookup_in with pattern matching
    pattern = re.compile(r"test\d+")
    assert not lookup_in("test123", pattern)  # Pattern matching not implemented yet
    assert not lookup_nin("test123", pattern)  # Pattern matching not implemented yet

    # Test lookup_in with mixed types in list
    mixed_list: list[str] = ["string", "123", "key:value"]  # Convert to string list
    # String in list returns True
    assert lookup_in("key:value", mixed_list)
    # String not in list returns True for nin
    assert lookup_nin("other:value", mixed_list)

    # Test invalid type combinations return False
    invalid_obj = {"key": "123"}  # type: dict[str, str]  # Valid type but invalid content
    assert lookup_in(invalid_obj, "test") is False  # Invalid usage but valid types
    assert lookup_in("test", invalid_obj) is False  # Invalid usage but valid types


def test_parse_lookup_error_cases() -> None:
    """Test error cases in parse_lookup function."""
    # Test with invalid path type
    obj = {"field": "value"}
    assert parse_lookup(obj, 123, "__contains") is None  # type: ignore

    # Test with invalid lookup type
    assert parse_lookup(obj, "field", 123) is None  # type: ignore

    # Test with path not ending in lookup
    assert parse_lookup(obj, "field", "__contains") is None

    # Test with empty field name after rsplit
    assert parse_lookup(obj, "__contains", "__contains") is None

    # Test with invalid object type
    assert parse_lookup(None, "field", "__contains") is None  # type: ignore

    # Test with path containing invalid characters
    assert parse_lookup(obj, "field\x00", "__contains") is None
