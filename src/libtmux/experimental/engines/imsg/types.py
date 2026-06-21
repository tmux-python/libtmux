"""Typed imsg frame primitives shared by protocol versions."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class ImsgHeader:
    """Decoded imsg header.

    ``length`` is the full frame length without the imsg FD marker bit.
    """

    msg_type: int
    length: int
    peer_id: int
    pid: int
    has_fd: bool = False


@dataclasses.dataclass(frozen=True)
class ImsgFrame:
    """A framed tmux imsg message plus an optional SCM_RIGHTS descriptor."""

    header: ImsgHeader
    payload: bytes = b""
    fd: int | None = None
