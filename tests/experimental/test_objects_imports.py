"""Tests for the experimental domain-object import surface."""

from __future__ import annotations


def test_objects_package_exports_navigation_roots() -> None:
    """The public experimental object surface exports navigation roots."""
    from libtmux.experimental.objects import AsyncServer, EagerServer, LazyServer

    assert EagerServer.__name__ == "EagerServer"
    assert LazyServer.__name__ == "LazyServer"
    assert AsyncServer.__name__ == "AsyncServer"
