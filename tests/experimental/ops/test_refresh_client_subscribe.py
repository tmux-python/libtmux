"""Tests for refresh-client -B/-C support."""

from __future__ import annotations

from libtmux.experimental.ops._ops.refresh_client import RefreshClient
from libtmux.experimental.ops._types import ClientName


def test_subscribe_emits_dash_b() -> None:
    """subscribe= field emits -B <spec> after the target."""
    op = RefreshClient(
        target=ClientName("/dev/pts/3"), subscribe="agentstate:%*:#{@agent_state}"
    )
    assert op.render() == (
        "refresh-client",
        "-t",
        "/dev/pts/3",
        "-B",
        "agentstate:%*:#{@agent_state}",
    )


def test_size_emits_dash_c() -> None:
    """size= field emits -C <size> after the target."""
    op = RefreshClient(target=ClientName("/dev/pts/3"), size="200x50")
    assert op.render() == ("refresh-client", "-t", "/dev/pts/3", "-C", "200x50")


def test_no_extra_args_by_default() -> None:
    """Default (no subscribe/size) renders only the target flag."""
    op = RefreshClient(target=ClientName("/dev/pts/3"))
    assert op.render() == ("refresh-client", "-t", "/dev/pts/3")


def test_subscribe_and_size_order() -> None:
    """Both set yields -B before -C."""
    op = RefreshClient(
        target=ClientName("/dev/pts/3"), subscribe="s:%*:#{@x}", size="200x50"
    )
    assert op.render() == (
        "refresh-client",
        "-t",
        "/dev/pts/3",
        "-B",
        "s:%*:#{@x}",
        "-C",
        "200x50",
    )
