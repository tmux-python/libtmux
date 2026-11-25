"""The executable version helpers warn, and say what replaces them."""

from __future__ import annotations

import typing as t

import pytest

import libtmux.common

HELPERS: list[tuple[str, tuple[t.Any, ...]]] = [
    ("get_version", ()),
    ("get_version_str", ()),
    ("has_version", ("3.3a",)),
    ("has_gt_version", ("3.3a",)),
    ("has_gte_version", ("3.3a",)),
    ("has_lte_version", ("3.3a",)),
    ("has_lt_version", ("3.3a",)),
    ("has_minimum_version", ()),
]


@pytest.mark.parametrize(
    ("name", "args"),
    HELPERS,
    ids=[name for name, _ in HELPERS],
)
def test_helper_warns_and_names_replacement(name: str, args: tuple[t.Any, ...]) -> None:
    """Each helper warns about the client executable and names the support API."""
    helper = getattr(libtmux.common, name)
    with pytest.warns(DeprecationWarning, match="client executable") as record:
        helper(*args)

    message = str(record[0].message)
    assert f"libtmux.common.{name}()" in message
    assert "libtmux._internal.support" in message
    assert "server_version(server)" in message
    assert record[0].filename == __file__, "warning points at the caller"


@pytest.mark.parametrize("name", ["TMUX_MIN_VERSION", "TMUX_MAX_VERSION"])
def test_constants_warn_and_keep_their_values(name: str) -> None:
    """The legacy constants stay importable through libtmux.common."""
    with pytest.warns(DeprecationWarning, match=name) as record:
        value = getattr(libtmux.common, name)

    assert isinstance(value, str)
    assert record[0].filename == __file__


def test_unknown_attribute_still_raises() -> None:
    """The module __getattr__ only serves the two legacy constants."""
    with pytest.raises(AttributeError, match="no attribute 'TMUX_NOPE'"):
        libtmux.common.TMUX_NOPE  # noqa: B018


def test_cache_clear_is_still_offered() -> None:
    """Callers that flush the executable caches keep a hook."""
    libtmux.common.get_version.cache_clear()
    libtmux.common.get_version_str.cache_clear()
