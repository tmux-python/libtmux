import operator
from contextlib import nullcontext as does_not_raise

import pytest

from libtmux._compat import LooseVersion


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
def test_version(version):
    assert LooseVersion(version)


@pytest.mark.parametrize(
    "version,op,versionb,raises",
    [
        ["1", operator.eq, "1", False],
        ["1", operator.eq, "1.0", False],
        ["1", operator.eq, "1.0.0", False],
        ["1", operator.gt, "1.0.0a", False],
        ["1", operator.gt, "1.0.0b", False],
        ["1", operator.lt, "1.0.0p1", False],
        ["1", operator.lt, "1.0.0-openbsd", False],
        ["1", operator.lt, "1", AssertionError],
        ["1", operator.lt, "1", AssertionError],
    ],
)
def test_version_compare(version, op, versionb, raises):
    raises_ctx = pytest.raises(raises) if raises else does_not_raise()
    with raises_ctx:
        assert op(LooseVersion(version), LooseVersion(versionb))
