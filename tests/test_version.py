"""Tests for version comparison."""

from __future__ import annotations

import operator
import typing as t
from contextlib import nullcontext as does_not_raise

import pytest

from libtmux._compat import LooseVersion

if t.TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TypeAlias

    try:
        from _pytest.raises import RaisesExc
    except ImportError:
        from _pytest.python_api import RaisesContext  # type: ignore[attr-defined]

        RaisesExc: TypeAlias = RaisesContext[Exception]  # type: ignore[no-redef]

    VersionCompareOp: TypeAlias = Callable[
        [t.Any, t.Any],
        bool,
    ]


class VersionTestFixture(t.NamedTuple):
    """Test fixture for version string validation."""

    test_id: str
    version: str


VERSION_TEST_FIXTURES: list[VersionTestFixture] = [
    VersionTestFixture(test_id="simple_version", version="1"),
    VersionTestFixture(test_id="minor_version", version="1.0"),
    VersionTestFixture(test_id="patch_version", version="1.0.0"),
    VersionTestFixture(test_id="beta_version", version="1.0.0b"),
    VersionTestFixture(test_id="beta_with_number", version="1.0.0b1"),
    VersionTestFixture(test_id="beta_with_os", version="1.0.0b-openbsd"),
    VersionTestFixture(test_id="next_version", version="1.0.0-next"),
    VersionTestFixture(test_id="next_with_number", version="1.0.0-next.1"),
]


@pytest.mark.parametrize(
    list(VersionTestFixture._fields),
    VERSION_TEST_FIXTURES,
    ids=[test.test_id for test in VERSION_TEST_FIXTURES],
)
def test_version(test_id: str, version: str) -> None:
    """Assert LooseVersion constructor against various version strings."""
    assert LooseVersion(version)


class VersionCompareFixture(t.NamedTuple):
    """Test fixture for version comparison."""

    test_id: str
    a: object
    op: VersionCompareOp
    b: object
    raises: type[Exception] | bool


VERSION_COMPARE_FIXTURES: list[VersionCompareFixture] = [
    VersionCompareFixture(
        test_id="equal_simple",
        a="1",
        op=operator.eq,
        b="1",
        raises=False,
    ),
    VersionCompareFixture(
        test_id="equal_with_minor",
        a="1",
        op=operator.eq,
        b="1.0",
        raises=False,
    ),
    VersionCompareFixture(
        test_id="equal_with_patch",
        a="1",
        op=operator.eq,
        b="1.0.0",
        raises=False,
    ),
    VersionCompareFixture(
        test_id="greater_than_alpha",
        a="1",
        op=operator.gt,
        b="1.0.0a",
        raises=False,
    ),
    VersionCompareFixture(
        test_id="greater_than_beta",
        a="1",
        op=operator.gt,
        b="1.0.0b",
        raises=False,
    ),
    VersionCompareFixture(
        test_id="less_than_patch",
        a="1",
        op=operator.lt,
        b="1.0.0p1",
        raises=False,
    ),
    VersionCompareFixture(
        test_id="less_than_openbsd",
        a="1",
        op=operator.lt,
        b="1.0.0-openbsd",
        raises=False,
    ),
    VersionCompareFixture(
        test_id="less_than_equal_raises",
        a="1",
        op=operator.lt,
        b="1",
        raises=AssertionError,
    ),
    VersionCompareFixture(
        test_id="beta_to_rc_compare",
        a="1.0.0c",
        op=operator.gt,
        b="1.0.0b",
        raises=False,
    ),
]


@pytest.mark.parametrize(
    list(VersionCompareFixture._fields),
    VERSION_COMPARE_FIXTURES,
    ids=[test.test_id for test in VERSION_COMPARE_FIXTURES],
)
def test_version_compare(
    test_id: str,
    a: str,
    op: VersionCompareOp,
    b: str,
    raises: type[Exception] | bool,
) -> None:
    """Assert version comparisons."""
    raises_ctx: RaisesExc = (
        pytest.raises(t.cast("type[Exception]", raises))
        if raises
        else t.cast("RaisesExc", does_not_raise())
    )
    with raises_ctx:
        assert op(LooseVersion(a), LooseVersion(b))
