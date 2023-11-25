"""Tests for version comparison."""
import operator
import typing as t
from contextlib import nullcontext as does_not_raise

import pytest

from libtmux._compat import LooseVersion

if t.TYPE_CHECKING:
    from _pytest.python_api import RaisesContext
    from typing_extensions import TypeAlias

    VersionCompareOp: TypeAlias = t.Callable[
        [t.Any, t.Any],
        bool,
    ]


@pytest.mark.parametrize(
    "version",
    [
        "1",
        "1.0",
        "1.0.0",
        "1.0.0b",
        "1.0.0b1",
        "1.0.0b-openbsd",
        "1.0.0-next",
        "1.0.0-next.1",
    ],
)
def test_version(version: str) -> None:
    """Assert LooseVersion constructor against various version strings."""
    assert LooseVersion(version)


class VersionCompareFixture(t.NamedTuple):
    """Test fixture for version comparison."""

    a: object
    op: "VersionCompareOp"
    b: object
    raises: t.Union[t.Type[Exception], bool]


@pytest.mark.parametrize(
    VersionCompareFixture._fields,
    [
        VersionCompareFixture(a="1", op=operator.eq, b="1", raises=False),
        VersionCompareFixture(a="1", op=operator.eq, b="1.0", raises=False),
        VersionCompareFixture(a="1", op=operator.eq, b="1.0.0", raises=False),
        VersionCompareFixture(a="1", op=operator.gt, b="1.0.0a", raises=False),
        VersionCompareFixture(a="1", op=operator.gt, b="1.0.0b", raises=False),
        VersionCompareFixture(a="1", op=operator.lt, b="1.0.0p1", raises=False),
        VersionCompareFixture(a="1", op=operator.lt, b="1.0.0-openbsd", raises=False),
        VersionCompareFixture(a="1", op=operator.lt, b="1", raises=AssertionError),
        VersionCompareFixture(a="1", op=operator.lt, b="1", raises=AssertionError),
        VersionCompareFixture(a="1.0.0c", op=operator.gt, b="1.0.0b", raises=False),
    ],
)
def test_version_compare(
    a: str,
    op: "VersionCompareOp",
    b: str,
    raises: t.Union[t.Type[Exception], bool],
) -> None:
    """Assert version comparisons."""
    raises_ctx: "RaisesContext[Exception]" = (
        pytest.raises(t.cast(t.Type[Exception], raises))
        if raises
        else t.cast("RaisesContext[Exception]", does_not_raise())
    )
    with raises_ctx:
        assert op(LooseVersion(a), LooseVersion(b))
