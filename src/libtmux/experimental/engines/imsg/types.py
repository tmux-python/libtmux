"""Typed imsg frame primitives shared by protocol versions."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class ImsgHeader:
    """Decoded imsg header.

    ``length`` is the full frame length without the imsg FD marker bit.

    Attributes
    ----------
    msg_type : int
        Numeric imsg message type.
    length : int
        Full frame length without the descriptor marker bit.
    peer_id : int
        Imsg peer identifier.
    pid : int
        Sending process identifier.
    has_fd : bool
        Whether the frame carries an SCM_RIGHTS descriptor.
    """

    msg_type: int
    length: int
    peer_id: int
    pid: int
    has_fd: bool = False


@dataclasses.dataclass(frozen=True)
class ImsgFrame:
    """A framed tmux imsg message plus an optional SCM_RIGHTS descriptor.

    Attributes
    ----------
    header : ImsgHeader
        Decoded imsg header.
    payload : bytes
        Message payload bytes after the header.
    fd : int or None
        Received SCM_RIGHTS descriptor, when present.
    """

    header: ImsgHeader
    payload: bytes = b""
    fd: int | None = None
