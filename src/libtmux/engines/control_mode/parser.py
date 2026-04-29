r"""State machine for the ``tmux -CC`` control-mode wire protocol.

The parser is intentionally I/O-free. Callers feed bytes through
:meth:`ControlParser.feed` and drain emitted events with
:meth:`ControlParser.events`. The split makes the parser unit-testable
without a live tmux server and benchmarkable in isolation from the
selector loop that drives reads.

Wire-protocol summary (verified against tmux 3.6 ``control.c`` and
``cmd-queue.c``):

* Each line is ``\n``-delimited.
* ``%begin <time> <number> <flags>`` opens a block.
* ``%end <time> <number> <flags>`` closes a successful block;
  ``%error <time> <number> <flags>`` closes a failed one. They are
  alternatives, not both. The ``<number>`` is server-assigned and the
  sole correlation key between outbound commands and their responses.
* Lines inside a block are plain bytes — *not* octal-escaped.
* Async notifications (``%output``, ``%session-changed``, ...) all
  begin with a single ``%`` on the wire and may interleave with command
  output. Strict prefix matching keeps them out of block bodies.
* ``%output %<pane> <bytes>`` and ``%extended-output %<pane> <us> :
  <bytes>`` carry octal-escaped pane data: bytes ``< 0x20`` and ``\``
  itself are encoded as ``\NNN``; everything else (including ``0x7F``
  and high bytes) passes through verbatim.

The parser is engine-agnostic. The control-mode engine (step 3) will
own a selector loop that pumps :meth:`ControlParser.feed`; the
subscription dispatcher (step 5) will route :class:`Notification`
events to user-facing queues.
"""

from __future__ import annotations

import dataclasses
import logging
import typing as t

logger = logging.getLogger(__name__)


_BEGIN_PREFIX = b"%begin "
_END_PREFIX = b"%end "
_ERROR_PREFIX = b"%error "

# All notification line prefixes the parser recognises. Order matters
# only for the ``%extended-output`` / ``%output`` pair: the extended
# variant must be checked first because ``startswith`` would otherwise
# match the shorter ``%output`` prefix incorrectly.
_NOTIFICATION_PREFIXES: tuple[bytes, ...] = (
    b"%extended-output ",
    b"%output ",
    b"%pause ",
    b"%continue ",
    b"%session-changed ",
    b"%client-session-changed ",
    b"%session-renamed ",
    b"%sessions-changed",
    b"%session-window-changed ",
    b"%window-add ",
    b"%window-close ",
    b"%window-renamed ",
    b"%window-pane-changed ",
    b"%pane-mode-changed ",
    b"%unlinked-window-add ",
    b"%unlinked-window-close ",
    b"%unlinked-window-renamed ",
    b"%paste-buffer-changed ",
    b"%paste-buffer-deleted ",
    b"%client-detached ",
    b"%subscription-changed ",
    b"%exit",
    b"%message ",
)


@dataclasses.dataclass(frozen=True, slots=True)
class Block:
    """A matched ``%begin``/``%end`` (or ``%error``) command response.

    Parameters
    ----------
    number : int
        Server-assigned command id from the opening ``%begin``.
        Correlates this block back to the outbound command that
        produced it.
    timestamp : int
        Unix seconds taken from the opening ``%begin``.
    flags : int
        Flags from the opening ``%begin`` — currently ``1`` whenever
        the command came from a control client.
    is_error : bool
        ``True`` when the block was closed by ``%error`` rather than
        ``%end``. The body in that case is the parse-error or
        runtime-error message tmux emitted.
    body : tuple of bytes
        The raw lines between the opening and closing guards, with
        the trailing newline stripped. Bytes are passed through
        verbatim — callers decode (typically UTF-8 with
        ``errors="replace"`` to match the subprocess engine).
    end_timestamp : int
        Unix seconds taken from the closing ``%end`` / ``%error``.
    end_flags : int
        Flags from the closing line.
    """

    number: int
    timestamp: int
    flags: int
    is_error: bool
    body: tuple[bytes, ...]
    end_timestamp: int
    end_flags: int


@dataclasses.dataclass(frozen=True, slots=True)
class Notification:
    """Marker base class for asynchronous ``%`` notifications."""

    raw: bytes
    """The original wire line with the trailing newline stripped."""


@dataclasses.dataclass(frozen=True, slots=True)
class OutputNotification(Notification):
    """``%output %<pane> <bytes>`` — pane stdout/stderr from tmux."""

    pane_id: str
    data: bytes


@dataclasses.dataclass(frozen=True, slots=True)
class ExtendedOutputNotification(Notification):
    """``%extended-output %<pane> <us-since-epoch> : <bytes>`` (≥ 2.7).

    The ``age_us`` field is the age in microseconds of the oldest data
    in the pane buffer at emit time, used to drive ``%pause`` /
    ``%continue`` flow control.
    """

    pane_id: str
    age_us: int
    data: bytes


@dataclasses.dataclass(frozen=True, slots=True)
class PauseNotification(Notification):
    """``%pause %<pane>`` — pane data is older than the pause threshold."""

    pane_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class ContinueNotification(Notification):
    """``%continue %<pane>`` — pane data is fresh enough to resume."""

    pane_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class SessionChangedNotification(Notification):
    """``%session-changed $<id> <name>`` — this client's session changed."""

    session_id: str
    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class ClientSessionChangedNotification(Notification):
    """``%client-session-changed <client> $<id> <name>``."""

    client: str
    session_id: str
    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class SessionRenamedNotification(Notification):
    """``%session-renamed $<id> <name>``."""

    session_id: str
    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class SessionsChangedNotification(Notification):
    """``%sessions-changed`` — any session created or closed."""


@dataclasses.dataclass(frozen=True, slots=True)
class SessionWindowChangedNotification(Notification):
    """``%session-window-changed $<sid> @<wid>``."""

    session_id: str
    window_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class WindowAddNotification(Notification):
    """``%window-add @<id>`` (window in this client's session)."""

    window_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class WindowCloseNotification(Notification):
    """``%window-close @<id>``."""

    window_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class WindowRenamedNotification(Notification):
    """``%window-renamed @<id> <name>``."""

    window_id: str
    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class WindowPaneChangedNotification(Notification):
    """``%window-pane-changed @<wid> %<pid>`` — active pane changed."""

    window_id: str
    pane_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class PaneModeChangedNotification(Notification):
    """``%pane-mode-changed %<id>`` — pane entered/left copy or search."""

    pane_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class UnlinkedWindowAddNotification(Notification):
    """``%unlinked-window-add @<id>`` (not in this client's session)."""

    window_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class UnlinkedWindowCloseNotification(Notification):
    """``%unlinked-window-close @<id>``."""

    window_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class UnlinkedWindowRenamedNotification(Notification):
    """``%unlinked-window-renamed @<id> <name>``."""

    window_id: str
    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class PasteBufferChangedNotification(Notification):
    """``%paste-buffer-changed <name>``."""

    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class PasteBufferDeletedNotification(Notification):
    """``%paste-buffer-deleted <name>``."""

    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class ClientDetachedNotification(Notification):
    """``%client-detached <client>``."""

    client: str


@dataclasses.dataclass(frozen=True, slots=True)
class SubscriptionChangedNotification(Notification):
    """``%subscription-changed <name> $<sid> @<wid> <widx> %<pid> : <value>``.

    Window-id, window-index, and pane-id may be the literal ``-`` placeholder
    for session-scoped subscriptions; we preserve them as ``None``.
    """

    name: str
    session_id: str
    window_id: str | None
    window_index: int | None
    pane_id: str | None
    value: str


@dataclasses.dataclass(frozen=True, slots=True)
class ExitNotification(Notification):
    """``%exit`` or ``%exit <reason>`` — the control client is shutting down.

    ``reason`` is ``None`` when no reason was provided.
    """

    reason: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class MessageNotification(Notification):
    """``%message <client> <type> <text>`` — server message routed to client."""

    payload: str


@dataclasses.dataclass(frozen=True, slots=True)
class UnknownNotification(Notification):
    """A ``%``-prefixed line the parser did not recognise.

    Tmux versions newer than the parser will emit notifications we do
    not have a dataclass for. They are surfaced as
    :class:`UnknownNotification` (with the original line in
    :attr:`raw`) and DEBUG-logged so a reader thread can keep going.
    """


Event: t.TypeAlias = Block | Notification


def unescape_octal(data: bytes) -> bytes:
    r"""Decode tmux's ``\NNN`` octal escape used inside ``%output``.

    Bytes ``< 0x20`` and ``0x5C`` (``\``) are emitted by tmux as
    ``\<3-digit-octal>``; everything else is passed verbatim.

    Parameters
    ----------
    data : bytes
        Escaped pane data (the suffix of an ``%output`` line, after
        the pane id and space).

    Returns
    -------
    bytes
        The original byte sequence.

    Examples
    --------
    >>> unescape_octal(rb"hello\012world") == b"hello\nworld"
    True
    >>> unescape_octal(rb"a\134b") == b"a\\b"
    True
    """
    if b"\\" not in data:
        return data
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        byte = data[i]
        if byte == 0x5C and i + 3 < n:
            d0, d1, d2 = data[i + 1], data[i + 2], data[i + 3]
            if _is_octal_digit(d0) and _is_octal_digit(d1) and _is_octal_digit(d2):
                out.append(((d0 - 0x30) << 6) | ((d1 - 0x30) << 3) | (d2 - 0x30))
                i += 4
                continue
        out.append(byte)
        i += 1
    return bytes(out)


def _is_octal_digit(byte: int) -> bool:
    return 0x30 <= byte <= 0x37


@dataclasses.dataclass(slots=True)
class _PendingBlock:
    number: int
    timestamp: int
    flags: int
    body: list[bytes]


class ControlParser:
    r"""Push-based parser for the ``tmux -CC`` wire protocol.

    Examples
    --------
    >>> parser = ControlParser()
    >>> parser.feed(b"%begin 1700000000 7 1\nhello\n%end 1700000000 7 1\n")
    >>> events = parser.events()
    >>> len(events)
    1
    >>> events[0].number, events[0].is_error
    (7, False)
    >>> events[0].body
    (b'hello',)

    Notifications interleaved with a block do not corrupt the body:

    >>> parser = ControlParser()
    >>> parser.feed(
    ...     b"%begin 1700000000 8 1\n"
    ...     b"%output %1 hi\n"
    ...     b"line one\n"
    ...     b"%end 1700000000 8 1\n"
    ... )
    >>> events = parser.events()
    >>> sum(isinstance(e, Block) for e in events)
    1
    >>> sum(isinstance(e, Notification) for e in events)
    1
    """

    __slots__ = ("_buffer", "_events", "_pending", "_unknown_count")

    def __init__(self) -> None:
        self._buffer: bytearray = bytearray()
        self._pending: _PendingBlock | None = None
        self._events: list[Event] = []
        self._unknown_count: int = 0

    @property
    def unknown_count(self) -> int:
        """Lines whose shape did not match any known guard or notification.

        Useful as an assertion target in tests: a healthy run should
        always end with ``unknown_count == 0``.
        """
        return self._unknown_count

    @property
    def in_block(self) -> bool:
        """Whether the parser is currently between ``%begin`` and ``%end``."""
        return self._pending is not None

    def feed(self, data: bytes) -> None:
        """Consume bytes from the wire, emitting events as lines complete.

        Partial lines remain in the internal buffer until a newline
        arrives. Calling :meth:`feed` is safe at any byte boundary.
        """
        if not data:
            return
        self._buffer.extend(data)
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                return
            line = bytes(self._buffer[:newline])
            del self._buffer[: newline + 1]
            self._handle_line(line)

    def feed_eof(self) -> None:
        r"""Signal that the wire was closed.

        Any partial line still buffered is dropped. Tmux always
        terminates lines with ``\n``, so a residual partial line
        means truncation.
        """
        if self._buffer:
            self._unknown_count += 1
            logger.debug(
                "control parser dropped partial line at EOF",
                extra={"tmux_cm_bytes": len(self._buffer)},
            )
            self._buffer.clear()

    def events(self) -> list[Event]:
        """Drain and return all pending events.

        After this call the internal queue is empty; subsequent
        :meth:`feed` calls accumulate fresh events.
        """
        out, self._events = self._events, []
        return out

    def _handle_line(self, line: bytes) -> None:
        if self._pending is not None:
            if line.startswith(_END_PREFIX) or line.startswith(_ERROR_PREFIX):
                self._close_block(line)
                return
            for prefix in _NOTIFICATION_PREFIXES:
                if line.startswith(prefix):
                    self._dispatch_notification(line)
                    return
            self._pending.body.append(line)
            return

        if line.startswith(_BEGIN_PREFIX):
            self._open_block(line)
            return
        if line.startswith(_END_PREFIX) or line.startswith(_ERROR_PREFIX):
            # Stray close guard with no open block — protocol confusion;
            # bump the counter so tests catch it and move on.
            self._unknown_count += 1
            logger.debug(
                "control parser saw close guard with no open block",
                extra={"tmux_cm_line": line[:200]},
            )
            return
        for prefix in _NOTIFICATION_PREFIXES:
            if line.startswith(prefix):
                self._dispatch_notification(line)
                return
        if line.startswith(b"%"):
            # Unknown ``%``-prefixed line — surface as a typed event so
            # the reader thread can DEBUG-log without dropping evidence.
            self._dispatch_notification(line)
            return
        if line:
            self._unknown_count += 1
            logger.debug(
                "control parser ignored stray line",
                extra={"tmux_cm_line": line[:200]},
            )

    def _open_block(self, line: bytes) -> None:
        ts, num, flags = _parse_guard(line, _BEGIN_PREFIX)
        if num is None:
            self._unknown_count += 1
            logger.debug(
                "control parser saw malformed %begin",
                extra={"tmux_cm_line": line[:200]},
            )
            return
        self._pending = _PendingBlock(
            number=num,
            timestamp=ts or 0,
            flags=flags or 0,
            body=[],
        )

    def _close_block(self, line: bytes) -> None:
        is_error = line.startswith(_ERROR_PREFIX)
        prefix = _ERROR_PREFIX if is_error else _END_PREFIX
        ts, num, flags = _parse_guard(line, prefix)
        pending = self._pending
        self._pending = None
        if pending is None:
            self._unknown_count += 1
            logger.debug(
                "control parser saw close guard with no open block",
                extra={"tmux_cm_line": line[:200]},
            )
            return
        if num is not None and num != pending.number:
            logger.warning(
                "control parser closing guard number mismatch",
                extra={
                    "tmux_cm_block_id": pending.number,
                    "tmux_cm_close_id": num,
                },
            )
        self._events.append(
            Block(
                number=pending.number,
                timestamp=pending.timestamp,
                flags=pending.flags,
                is_error=is_error,
                body=tuple(pending.body),
                end_timestamp=ts or 0,
                end_flags=flags or 0,
            ),
        )

    def _dispatch_notification(self, line: bytes) -> None:
        notification = _parse_notification(line)
        if isinstance(notification, UnknownNotification):
            self._unknown_count += 1
            logger.debug(
                "control parser unknown notification",
                extra={"tmux_cm_line": line[:200]},
            )
        self._events.append(notification)


def _parse_guard(
    line: bytes,
    prefix: bytes,
) -> tuple[int | None, int | None, int | None]:
    """Return ``(timestamp, number, flags)`` from a ``%begin``/``%end``/``%error``."""
    rest = line[len(prefix) :]
    parts = rest.split()
    if len(parts) < 3:
        return (None, None, None)
    try:
        ts = int(parts[0])
        num = int(parts[1])
        flags = int(parts[2])
    except ValueError:
        return (None, None, None)
    return (ts, num, flags)


def _parse_notification(line: bytes) -> Notification:
    """Decode a single ``%``-prefixed notification line into a dataclass."""
    text = line.decode("utf-8", errors="replace")
    if text.startswith("%extended-output "):
        return _parse_extended_output(line, text)
    if text.startswith("%output "):
        return _parse_output(line, text)
    if text.startswith("%pause ") or text.startswith("%continue "):
        return _parse_pause_continue(line, text)
    if text.startswith("%subscription-changed "):
        return _parse_subscription_changed(line, text)
    if text == "%sessions-changed" or text.startswith("%sessions-changed"):
        return SessionsChangedNotification(raw=line)
    if text.startswith("%session-changed "):
        return _parse_two_field(
            line,
            text,
            "%session-changed ",
            SessionChangedNotification,
            "session_id",
        )
    if text.startswith("%client-session-changed "):
        return _parse_client_session_changed(line, text)
    if text.startswith("%session-renamed "):
        return _parse_two_field(
            line,
            text,
            "%session-renamed ",
            SessionRenamedNotification,
            "session_id",
        )
    if text.startswith("%session-window-changed "):
        return _parse_session_window_changed(line, text)
    if text.startswith("%window-pane-changed "):
        return _parse_window_pane_changed(line, text)
    if text.startswith("%pane-mode-changed "):
        return _parse_id_only(
            line,
            text,
            "%pane-mode-changed ",
            PaneModeChangedNotification,
            "pane_id",
        )
    if text.startswith("%window-add "):
        return _parse_id_only(
            line,
            text,
            "%window-add ",
            WindowAddNotification,
            "window_id",
        )
    if text.startswith("%window-close "):
        return _parse_id_only(
            line,
            text,
            "%window-close ",
            WindowCloseNotification,
            "window_id",
        )
    if text.startswith("%unlinked-window-add "):
        return _parse_id_only(
            line,
            text,
            "%unlinked-window-add ",
            UnlinkedWindowAddNotification,
            "window_id",
        )
    if text.startswith("%unlinked-window-close "):
        return _parse_id_only(
            line,
            text,
            "%unlinked-window-close ",
            UnlinkedWindowCloseNotification,
            "window_id",
        )
    if text.startswith("%window-renamed "):
        return _parse_two_field(
            line,
            text,
            "%window-renamed ",
            WindowRenamedNotification,
            "window_id",
        )
    if text.startswith("%unlinked-window-renamed "):
        return _parse_two_field(
            line,
            text,
            "%unlinked-window-renamed ",
            UnlinkedWindowRenamedNotification,
            "window_id",
        )
    if text.startswith("%paste-buffer-changed "):
        return PasteBufferChangedNotification(
            raw=line,
            name=text[len("%paste-buffer-changed ") :],
        )
    if text.startswith("%paste-buffer-deleted "):
        return PasteBufferDeletedNotification(
            raw=line,
            name=text[len("%paste-buffer-deleted ") :],
        )
    if text.startswith("%client-detached "):
        return ClientDetachedNotification(
            raw=line,
            client=text[len("%client-detached ") :],
        )
    if text.startswith("%message "):
        return MessageNotification(raw=line, payload=text[len("%message ") :])
    if text == "%exit":
        return ExitNotification(raw=line, reason=None)
    if text.startswith("%exit "):
        return ExitNotification(raw=line, reason=text[len("%exit ") :])
    return UnknownNotification(raw=line)


def _parse_output(line: bytes, text: str) -> OutputNotification:
    body = text[len("%output ") :]
    pane_id, _, payload = body.partition(" ")
    return OutputNotification(
        raw=line,
        pane_id=pane_id,
        data=unescape_octal(payload.encode("utf-8", errors="replace")),
    )


def _parse_extended_output(line: bytes, text: str) -> ExtendedOutputNotification:
    body = text[len("%extended-output ") :]
    pane_id, _, rest = body.partition(" ")
    age_str, _, payload = rest.partition(" : ")
    try:
        age_us = int(age_str)
    except ValueError:
        age_us = 0
    return ExtendedOutputNotification(
        raw=line,
        pane_id=pane_id,
        age_us=age_us,
        data=unescape_octal(payload.encode("utf-8", errors="replace")),
    )


def _parse_pause_continue(
    line: bytes,
    text: str,
) -> PauseNotification | ContinueNotification:
    if text.startswith("%pause "):
        return PauseNotification(raw=line, pane_id=text[len("%pause ") :])
    return ContinueNotification(raw=line, pane_id=text[len("%continue ") :])


def _parse_two_field(
    line: bytes,
    text: str,
    prefix: str,
    cls: type[Notification],
    id_field: str,
) -> Notification:
    body = text[len(prefix) :]
    head, _, name = body.partition(" ")
    return cls(raw=line, **{id_field: head, "name": name})


def _parse_id_only(
    line: bytes,
    text: str,
    prefix: str,
    cls: type[Notification],
    id_field: str,
) -> Notification:
    return cls(raw=line, **{id_field: text[len(prefix) :]})


def _parse_client_session_changed(
    line: bytes,
    text: str,
) -> ClientSessionChangedNotification:
    body = text[len("%client-session-changed ") :]
    parts = body.split(" ", 2)
    if len(parts) != 3:
        return ClientSessionChangedNotification(
            raw=line,
            client="",
            session_id="",
            name=body,
        )
    client, session_id, name = parts
    return ClientSessionChangedNotification(
        raw=line,
        client=client,
        session_id=session_id,
        name=name,
    )


def _parse_session_window_changed(
    line: bytes,
    text: str,
) -> SessionWindowChangedNotification:
    body = text[len("%session-window-changed ") :]
    session_id, _, window_id = body.partition(" ")
    return SessionWindowChangedNotification(
        raw=line,
        session_id=session_id,
        window_id=window_id,
    )


def _parse_window_pane_changed(
    line: bytes,
    text: str,
) -> WindowPaneChangedNotification:
    body = text[len("%window-pane-changed ") :]
    window_id, _, pane_id = body.partition(" ")
    return WindowPaneChangedNotification(
        raw=line,
        window_id=window_id,
        pane_id=pane_id,
    )


def _parse_subscription_changed(
    line: bytes,
    text: str,
) -> SubscriptionChangedNotification:
    body = text[len("%subscription-changed ") :]
    head, separator, value = body.partition(" : ")
    if separator == "":
        # Malformed; treat the whole thing as the value.
        return SubscriptionChangedNotification(
            raw=line,
            name="",
            session_id="",
            window_id=None,
            window_index=None,
            pane_id=None,
            value=body,
        )
    parts = head.split(" ")
    name = parts[0] if parts else ""
    session_id = parts[1] if len(parts) > 1 else ""
    window_id = _none_if_dash(parts[2]) if len(parts) > 2 else None
    window_index = _int_or_none(parts[3]) if len(parts) > 3 else None
    pane_id = _none_if_dash(parts[4]) if len(parts) > 4 else None
    return SubscriptionChangedNotification(
        raw=line,
        name=name,
        session_id=session_id,
        window_id=window_id,
        window_index=window_index,
        pane_id=pane_id,
        value=value,
    )


def _none_if_dash(value: str) -> str | None:
    return None if value in {"", "-"} else value


def _int_or_none(value: str) -> int | None:
    if value in {"", "-"}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


__all__ = (
    "Block",
    "ClientDetachedNotification",
    "ClientSessionChangedNotification",
    "ContinueNotification",
    "ControlParser",
    "Event",
    "ExitNotification",
    "ExtendedOutputNotification",
    "MessageNotification",
    "Notification",
    "OutputNotification",
    "PaneModeChangedNotification",
    "PasteBufferChangedNotification",
    "PasteBufferDeletedNotification",
    "PauseNotification",
    "SessionChangedNotification",
    "SessionRenamedNotification",
    "SessionWindowChangedNotification",
    "SessionsChangedNotification",
    "SubscriptionChangedNotification",
    "UnknownNotification",
    "UnlinkedWindowAddNotification",
    "UnlinkedWindowCloseNotification",
    "UnlinkedWindowRenamedNotification",
    "WindowAddNotification",
    "WindowCloseNotification",
    "WindowPaneChangedNotification",
    "WindowRenamedNotification",
    "unescape_octal",
)
