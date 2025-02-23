"""Test dataclasses utilities."""

from __future__ import annotations

import dataclasses

from libtmux._internal.dataclasses import SkipDefaultFieldsReprMixin


@dataclasses.dataclass(repr=False)
class TestItem(SkipDefaultFieldsReprMixin):
    """Test class for SkipDefaultFieldsReprMixin."""

    name: str
    unit_price: float = 1.00
    quantity_on_hand: int = 0


def test_skip_default_fields_repr() -> None:
    """Test SkipDefaultFieldsReprMixin repr behavior."""
    # Test with only required field
    item1 = TestItem("Test")
    assert repr(item1) == "TestItem(name=Test)"

    # Test with one default field modified
    item2 = TestItem("Test", unit_price=2.00)
    assert repr(item2) == "TestItem(name=Test, unit_price=2.0)"

    # Test with all fields modified
    item3 = TestItem("Test", unit_price=2.00, quantity_on_hand=5)
    assert repr(item3) == "TestItem(name=Test, unit_price=2.0, quantity_on_hand=5)"

    # Test modifying field after creation
    item4 = TestItem("Test")
    item4.unit_price = 2.05
    assert repr(item4) == "TestItem(name=Test, unit_price=2.05)"

    # Test with multiple fields modified after creation
    item5 = TestItem("Test")
    item5.unit_price = 2.05
    item5.quantity_on_hand = 3
    assert repr(item5) == "TestItem(name=Test, unit_price=2.05, quantity_on_hand=3)"
