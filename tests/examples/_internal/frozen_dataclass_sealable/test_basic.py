#!/usr/bin/env python3
"""Basic examples of frozen_dataclass_sealable usage.

This file contains examples extracted from the docstring of the
frozen_dataclass_sealable decorator, to demonstrate its functionality with
working code examples.
"""

from __future__ import annotations

from dataclasses import field

import pytest

from libtmux._internal.frozen_dataclass_sealable import (
    frozen_dataclass_sealable,
    is_sealable,
)


def test_basic_usage():
    """Test basic usage of frozen_dataclass_sealable."""

    @frozen_dataclass_sealable
    class Config:
        name: str

        values: dict[str, int] = field(
            default_factory=dict, metadata={"mutable_during_init": True}
        )

    # Create an instance
    config = Config(name="test-config")
    assert config.name == "test-config"

    # Cannot modify immutable fields
    with pytest.raises(AttributeError):
        config.name = "modified"

    # Can modify mutable fields
    config.values["key1"] = 100
    assert config.values["key1"] == 100

    # Check sealable property
    assert is_sealable(config)

    # Seal the object
    config.seal()
    assert hasattr(config, "_sealed") and config._sealed

    # Can still modify contents of mutable containers after sealing
    config.values["key2"] = 200
    assert config.values["key2"] == 200


def test_deferred_sealing():
    """Test deferred sealing with linked nodes."""

    @frozen_dataclass_sealable
    class Node:
        value: int

        next_node: Node | None = field(
            default=None, metadata={"mutable_during_init": True}
        )

    # Create a linked list (not circular to avoid recursion issues)
    node1 = Node(value=1)
    node2 = Node(value=2)
    node1.next_node = node2

    # Verify structure
    assert node1.value == 1
    assert node2.value == 2
    assert node1.next_node is node2

    # Verify sealable property
    assert is_sealable(node1)
    assert is_sealable(node2)

    # Seal nodes individually
    node1.seal()
    node2.seal()

    # Verify both nodes are sealed
    assert hasattr(node1, "_sealed") and node1._sealed
    assert hasattr(node2, "_sealed") and node2._sealed

    # Verify immutability after sealing
    with pytest.raises(AttributeError):
        node1.value = 10


if __name__ == "__main__":
    pytest.main(["-xvs", __file__])
