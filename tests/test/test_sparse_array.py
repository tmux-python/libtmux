"""Tests for libtmux sparse array utilities."""

from __future__ import annotations

import typing as t

import pytest

from libtmux._internal.sparse_array import SparseArray, is_sparse_array_list


class IsSparseArrayListTestCase(t.NamedTuple):
    """Test case for is_sparse_array_list TypeGuard function."""

    test_id: str
    input_dict: dict[str, t.Any]
    expected: bool


class SparseArrayAppendTestCase(t.NamedTuple):
    """Test case for SparseArray.append method."""

    test_id: str
    initial_adds: list[tuple[int, str]]  # [(index, value), ...] to setup
    append_values: list[str]  # values to append
    expected_keys: list[int]  # expected keys in sorted order
    expected_mapping: dict[int, str]  # specific index -> value checks


class SparseArrayValuesTestCase(t.NamedTuple):
    """Test case for iter_values and as_list methods."""

    test_id: str
    adds: list[tuple[int, str]]  # [(index, value), ...]
    expected_values: list[str]  # values in sorted index order


IS_SPARSE_ARRAY_LIST_TEST_CASES: list[IsSparseArrayListTestCase] = [
    IsSparseArrayListTestCase("empty_dict", {}, True),
    IsSparseArrayListTestCase(
        "sparse_arrays_only",
        {"hook1": SparseArray(), "hook2": SparseArray()},
        True,
    ),
    IsSparseArrayListTestCase(
        "mixed_values",
        {"hook1": SparseArray(), "opt": "string"},
        False,
    ),
    IsSparseArrayListTestCase(
        "strings_only",
        {"key1": "val1", "key2": "val2"},
        False,
    ),
    IsSparseArrayListTestCase("none_value", {"key1": None}, False),
]

SPARSE_ARRAY_APPEND_TEST_CASES: list[SparseArrayAppendTestCase] = [
    SparseArrayAppendTestCase(
        "append_to_empty",
        initial_adds=[],
        append_values=["first"],
        expected_keys=[0],
        expected_mapping={0: "first"},
    ),
    SparseArrayAppendTestCase(
        "append_after_add",
        initial_adds=[(5, "at five")],
        append_values=["appended"],
        expected_keys=[5, 6],
        expected_mapping={5: "at five", 6: "appended"},
    ),
    SparseArrayAppendTestCase(
        "multiple_appends",
        initial_adds=[],
        append_values=["100", "200", "300"],
        expected_keys=[0, 1, 2],
        expected_mapping={0: "100", 1: "200", 2: "300"},
    ),
]

SPARSE_ARRAY_VALUES_TEST_CASES: list[SparseArrayValuesTestCase] = [
    SparseArrayValuesTestCase(
        "sorted_order",
        adds=[(10, "ten"), (1, "one"), (5, "five")],
        expected_values=["one", "five", "ten"],
    ),
    SparseArrayValuesTestCase(
        "empty",
        adds=[],
        expected_values=[],
    ),
    SparseArrayValuesTestCase(
        "consecutive",
        adds=[(3, "three"), (1, "one"), (2, "two")],
        expected_values=["one", "two", "three"],
    ),
]


@pytest.mark.parametrize(
    "test_case",
    [pytest.param(tc, id=tc.test_id) for tc in IS_SPARSE_ARRAY_LIST_TEST_CASES],
)
def test_is_sparse_array_list(test_case: IsSparseArrayListTestCase) -> None:
    """Test is_sparse_array_list TypeGuard function."""
    result = is_sparse_array_list(test_case.input_dict)
    assert result is test_case.expected


@pytest.mark.parametrize(
    "test_case",
    [pytest.param(tc, id=tc.test_id) for tc in SPARSE_ARRAY_APPEND_TEST_CASES],
)
def test_sparse_array_append(test_case: SparseArrayAppendTestCase) -> None:
    """Test SparseArray.append method."""
    arr: SparseArray[str] = SparseArray()
    for index, value in test_case.initial_adds:
        arr.add(index, value)
    for value in test_case.append_values:
        arr.append(value)
    assert sorted(arr.keys()) == test_case.expected_keys
    for index, expected_value in test_case.expected_mapping.items():
        assert arr[index] == expected_value


@pytest.mark.parametrize(
    "test_case",
    [pytest.param(tc, id=tc.test_id) for tc in SPARSE_ARRAY_VALUES_TEST_CASES],
)
def test_sparse_array_iter_values(test_case: SparseArrayValuesTestCase) -> None:
    """Test SparseArray.iter_values method."""
    arr: SparseArray[str] = SparseArray()
    for index, value in test_case.adds:
        arr.add(index, value)
    assert list(arr.iter_values()) == test_case.expected_values


@pytest.mark.parametrize(
    "test_case",
    [pytest.param(tc, id=tc.test_id) for tc in SPARSE_ARRAY_VALUES_TEST_CASES],
)
def test_sparse_array_as_list(test_case: SparseArrayValuesTestCase) -> None:
    """Test SparseArray.as_list method."""
    arr: SparseArray[str] = SparseArray()
    for index, value in test_case.adds:
        arr.add(index, value)
    assert arr.as_list() == test_case.expected_values
