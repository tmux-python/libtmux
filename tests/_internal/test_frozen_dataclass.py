"""Tests for the custom frozen_dataclass implementation."""

from __future__ import annotations

import dataclasses
import typing as t
from datetime import datetime

import pytest

from libtmux._internal.frozen_dataclass import frozen_dataclass


# 1. Create a base class that is a normal (mutable) dataclass
@dataclasses.dataclass
class BasePane:
    """Test base class to simulate tmux Pane."""

    pane_id: str
    width: int
    height: int

    def resize(self, width: int, height: int) -> None:
        """Resize the pane (mutable operation)."""
        self.width = width
        self.height = height


# Silence specific mypy errors with a global disable
# mypy: disable-error-code="misc"


# 2. Subclass the mutable BasePane, but freeze it with our custom decorator
@frozen_dataclass
class PaneSnapshot(BasePane):
    """Test snapshot class with additional fields."""

    # Add snapshot-specific fields
    captured_content: list[str] = dataclasses.field(default_factory=list)
    created_at: datetime = dataclasses.field(default_factory=datetime.now)
    parent_window: WindowSnapshot | None = None

    def resize(self, width: int, height: int) -> None:
        """Override to prevent resizing."""
        error_msg = "Snapshot is immutable. resize() not allowed."
        raise NotImplementedError(error_msg)


# Another test class for nested reference handling
@frozen_dataclass
class WindowSnapshot:
    """Test window snapshot class."""

    window_id: str
    name: str
    panes: list[PaneSnapshot] = dataclasses.field(default_factory=list)


# Core behavior tests
# ------------------


def test_snapshot_initialization() -> None:
    """Test proper initialization of fields in a frozen dataclass."""
    pane = PaneSnapshot(
        pane_id="pane123", width=80, height=24, captured_content=["Line1", "Line2"]
    )

    # Values should be correctly assigned
    assert pane.pane_id == "pane123"
    assert pane.width == 80
    assert pane.height == 24
    assert pane.captured_content == ["Line1", "Line2"]
    assert isinstance(pane.created_at, datetime)


def test_immutability() -> None:
    """Test that the snapshot is immutable."""
    snapshot = PaneSnapshot(
        pane_id="pane123", width=80, height=24, captured_content=["Line1"]
    )

    # Attempting to modify a field should raise AttributeError
    # with precise error message
    with pytest.raises(
        AttributeError, match=r"PaneSnapshot is immutable: cannot modify field 'width'"
    ):
        snapshot.width = 200  # type: ignore

    # Attempting to add a new field should raise AttributeError
    # with precise error message
    with pytest.raises(
        AttributeError,
        match=r"PaneSnapshot is immutable: cannot modify field 'new_field'",
    ):
        snapshot.new_field = "value"  # type: ignore

    # Attempting to delete a field should raise AttributeError
    # with precise error message
    with pytest.raises(
        AttributeError, match=r"PaneSnapshot is immutable: cannot delete field 'width'"
    ):
        del snapshot.width

    # Calling a method that tries to modify state should fail
    with pytest.raises(
        NotImplementedError, match=r"Snapshot is immutable. resize\(\) not allowed."
    ):
        snapshot.resize(200, 50)


def test_inheritance() -> None:
    """Test that frozen classes correctly inherit from mutable base classes."""
    # Create instances of both classes
    base_pane = BasePane(pane_id="base1", width=80, height=24)
    snapshot = PaneSnapshot(pane_id="snap1", width=80, height=24)

    # Verify inheritance relationship
    assert isinstance(snapshot, BasePane)
    assert isinstance(snapshot, PaneSnapshot)

    # Base class remains mutable
    base_pane.width = 100
    assert base_pane.width == 100

    # Derived class is immutable
    with pytest.raises(AttributeError, match="immutable"):
        snapshot.width = 100


# Edge case tests
# --------------


def test_internal_attributes() -> None:
    """Test that internal attributes (starting with _) can be modified."""
    snapshot = PaneSnapshot(
        pane_id="pane123",
        width=80,
        height=24,
    )

    # Should be able to set internal attributes
    snapshot._internal_cache = {"test": "value"}  # type: ignore
    assert snapshot._internal_cache == {"test": "value"}  # type: ignore


def test_nested_mutability_leak() -> None:
    """Test the known limitation that nested mutable fields can still be modified."""
    # Create a frozen dataclass with a mutable field
    snapshot = PaneSnapshot(
        pane_id="pane123", width=80, height=24, captured_content=["initial"]
    )

    # Can't reassign the field itself
    with pytest.raises(AttributeError, match="immutable"):
        snapshot.captured_content = ["new"]  # type: ignore

    # But we can modify its contents (limitation of Python immutability)
    snapshot.captured_content.append("mutated")
    assert "mutated" in snapshot.captured_content
    assert snapshot.captured_content == ["initial", "mutated"]


def test_bidirectional_references() -> None:
    """Test that nested structures with bidirectional references work properly."""
    # Create temporary panes (will be re-created with the window)
    temp_panes: list[PaneSnapshot] = []

    # First, create a window with an empty panes list
    window = WindowSnapshot(window_id="win1", name="Test Window", panes=temp_panes)

    # Now create panes with references to the window
    pane1 = PaneSnapshot(pane_id="pane1", width=80, height=24, parent_window=window)
    pane2 = PaneSnapshot(pane_id="pane2", width=80, height=24, parent_window=window)

    # Update the panes list before it gets frozen
    temp_panes.append(pane1)
    temp_panes.append(pane2)

    # Test relationships
    assert pane1.parent_window is window
    assert pane2.parent_window is window
    assert pane1 in window.panes
    assert pane2 in window.panes

    # Can still modify the contents of mutable collections
    pane3 = PaneSnapshot(pane_id="pane3", width=100, height=30)
    window.panes.append(pane3)
    assert len(window.panes) == 3  # Successfully modified

    # This is a "leaky abstraction" in Python's immutability model
    # In real code, consider using immutable collections (tuple, frozenset)
    # or deep freezing containers


# NamedTuple-based parametrized tests
# ----------------------------------


class DimensionTestCase(t.NamedTuple):
    """Test fixture for validating dimensions in PaneSnapshot.

    Note: This implementation intentionally allows any dimension values, including
    negative or extremely large values. In a real-world application, you might want
    to add validation to the class constructor if certain dimension ranges are required.
    """

    test_id: str
    width: int
    height: int
    expected_error: bool
    error_match: str | None = None


DIMENSION_TEST_CASES: list[DimensionTestCase] = [
    DimensionTestCase(
        test_id="standard_dimensions",
        width=80,
        height=24,
        expected_error=False,
    ),
    DimensionTestCase(
        test_id="zero_dimensions",
        width=0,
        height=0,
        expected_error=False,
    ),
    DimensionTestCase(
        test_id="negative_dimensions",
        width=-10,
        height=-5,
        expected_error=False,
    ),
    DimensionTestCase(
        test_id="extreme_dimensions",
        width=9999,
        height=9999,
        expected_error=False,
    ),
]


@pytest.mark.parametrize(
    list(DimensionTestCase._fields),
    DIMENSION_TEST_CASES,
    ids=[test.test_id for test in DIMENSION_TEST_CASES],
)
def test_snapshot_dimensions(
    test_id: str, width: int, height: int, expected_error: bool, error_match: str | None
) -> None:
    """Test PaneSnapshot initialization with various dimensions."""
    # Initialize the PaneSnapshot
    pane = PaneSnapshot(pane_id="test", width=width, height=height)

    # Verify dimensions were set correctly
    assert pane.width == width
    assert pane.height == height

    # Verify immutability
    with pytest.raises(AttributeError, match="immutable"):
        pane.width = 100  # type: ignore


class FrozenFlagTestCase(t.NamedTuple):
    """Test fixture for testing _frozen flag behavior."""

    test_id: str
    unfreeze_attempt: bool
    expect_mutation_error: bool
    error_match: str | None = None


FROZEN_FLAG_TEST_CASES: list[FrozenFlagTestCase] = [
    FrozenFlagTestCase(
        test_id="attempt_unfreeze",
        unfreeze_attempt=True,
        expect_mutation_error=False,
        error_match=None,
    ),
    FrozenFlagTestCase(
        test_id="no_unfreeze_attempt",
        unfreeze_attempt=False,
        expect_mutation_error=True,
        error_match="immutable.*cannot modify field",
    ),
]


@pytest.mark.parametrize(
    list(FrozenFlagTestCase._fields),
    FROZEN_FLAG_TEST_CASES,
    ids=[test.test_id for test in FROZEN_FLAG_TEST_CASES],
)
def test_frozen_flag(
    test_id: str,
    unfreeze_attempt: bool,
    expect_mutation_error: bool,
    error_match: str | None,
) -> None:
    """Test behavior when attempting to manipulate the _frozen flag.

    Note: We discovered that setting _frozen=False actually allows mutation,
    which could be a potential security issue if users know about this behavior.
    In a more secure implementation, the _frozen attribute might need additional
    protection to prevent this bypass mechanism, such as making it a property with
    a setter that raises an exception.
    """
    # Create a frozen dataclass
    pane = PaneSnapshot(pane_id="test_frozen", width=80, height=24)

    # Attempt to unfreeze if requested
    if unfreeze_attempt:
        pane._frozen = False  # type: ignore

    # Attempt mutation and check if it fails as expected
    if expect_mutation_error:
        with pytest.raises(AttributeError, match=error_match):
            pane.width = 200  # type: ignore
    else:
        pane.width = 200  # type: ignore
        assert pane.width == 200


class MutationMethodTestCase(t.NamedTuple):
    """Test fixture for testing mutation methods."""

    test_id: str
    method_name: str
    args: tuple[t.Any, ...]
    error_type: type[Exception]
    error_match: str


MUTATION_METHOD_TEST_CASES: list[MutationMethodTestCase] = [
    MutationMethodTestCase(
        test_id="resize_method",
        method_name="resize",
        args=(100, 50),
        error_type=NotImplementedError,
        error_match="immutable.*resize.*not allowed",
    ),
]


@pytest.mark.parametrize(
    list(MutationMethodTestCase._fields),
    MUTATION_METHOD_TEST_CASES,
    ids=[test.test_id for test in MUTATION_METHOD_TEST_CASES],
)
def test_mutation_methods(
    test_id: str,
    method_name: str,
    args: tuple[t.Any, ...],
    error_type: type[Exception],
    error_match: str,
) -> None:
    """Test that methods attempting to modify state raise appropriate exceptions."""
    # Create a frozen dataclass
    pane = PaneSnapshot(pane_id="test_methods", width=80, height=24)

    # Get the method and attempt to call it
    method = getattr(pane, method_name)
    with pytest.raises(error_type, match=error_match):
        method(*args)


class InheritanceTestCase(t.NamedTuple):
    """Test fixture for testing inheritance behavior."""

    test_id: str
    create_base: bool
    mutate_base: bool
    mutate_derived: bool
    expect_base_error: bool
    expect_derived_error: bool


INHERITANCE_TEST_CASES: list[InheritanceTestCase] = [
    InheritanceTestCase(
        test_id="mutable_base_immutable_derived",
        create_base=True,
        mutate_base=True,
        mutate_derived=True,
        expect_base_error=False,
        expect_derived_error=True,
    ),
]


@pytest.mark.parametrize(
    list(InheritanceTestCase._fields),
    INHERITANCE_TEST_CASES,
    ids=[test.test_id for test in INHERITANCE_TEST_CASES],
)
def test_inheritance_behavior(
    test_id: str,
    create_base: bool,
    mutate_base: bool,
    mutate_derived: bool,
    expect_base_error: bool,
    expect_derived_error: bool,
) -> None:
    """Test inheritance behavior with mutable base class and immutable derived class."""
    # Create base class if requested
    if create_base:
        base = BasePane(pane_id="base", width=80, height=24)

    # Create derived class
    derived = PaneSnapshot(pane_id="derived", width=80, height=24)

    # Attempt to mutate base class if requested
    if create_base and mutate_base:
        if expect_base_error:
            with pytest.raises(AttributeError):
                base.width = 100
        else:
            base.width = 100
            assert base.width == 100

    # Attempt to mutate derived class if requested
    if mutate_derived:
        if expect_derived_error:
            with pytest.raises(AttributeError):
                derived.width = 100  # type: ignore
        else:
            derived.width = 100  # type: ignore
            assert derived.width == 100
