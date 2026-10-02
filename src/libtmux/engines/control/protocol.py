r"""The control-mode wire protocol, with no I/O.

``tmux -C`` speaks a line protocol on stdout. A command's reply is a block
framed by ``%begin`` and ``%end`` (or ``%error``), and everything else is a
``%``-prefixed notification delivered between blocks. This module parses that
stream into typed events and encodes commands for stdin. It never reads a pipe
or starts a process, so a driver (selector, asyncio, a test) feeds it bytes and
reads events.

>>> parser = ControlModeParser()
>>> parser.feed(b"%begin 1700000000 12 1\nhello\n%end 1700000000 12 1\n")
[Block(time=1700000000, number=12, flags=1, is_error=False, body=(b'hello',))]

Notifications keep their position relative to blocks:

>>> events = parser.feed(b"%output %0 hi\\015\\012\n%window-add @3\n")
>>> events[0]
Output(pane='%0', data=b'hi\r\n')
>>> events[1]
Notification(name='window-add', args='@3')

Commands are encoded one line each, every argument quoted:

>>> encode_command(("display-message", "-p", "it's;"))
b"'display-message' '-p' 'it'\\''s;'\n"
"""

from __future__ import annotations

import re
import typing as t
from dataclasses import dataclass

from libtmux import exc
from libtmux.engines.base import CommandResult, is_command_separator

if t.TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import TypeAlias

_BEGIN = b"%begin "
_OCTAL = re.compile(rb"\\([0-7]{3})")
_SOLICITED = 1
_GUARD_FIELDS = 3
_SUBSCRIPTION_FIELDS = 5


@dataclass(frozen=True)
class Block:
    """One command reply: the lines between a ``%begin`` and its closing guard.

    Attributes
    ----------
    time : int
        Epoch seconds from the guard.
    number : int
        tmux's command number. It is server-wide and increases with every
        command, so it is unique per reply but not contiguous for one client.
    flags : int
        The guard's flags field. ``1`` marks a reply to a command this client
        sent; ``0`` marks a block tmux wrote for work it started itself, such
        as the ``attach-session`` that opens the connection or a hook's
        command.
    is_error : bool
        Whether the block closed with ``%error``.
    body : tuple[bytes, ...]
        Raw lines, without the newline. On an error this is tmux's message.

    Notes
    -----
    Before tmux 3.8, a notification the command caused can arrive between the
    guards, so ``%continue %0`` is body in the reply to ``refresh-client -A
    %0:continue``. Position decides meaning; the parser never reclassifies a
    body line by its shape.
    """

    time: int
    number: int
    flags: int
    is_error: bool
    body: tuple[bytes, ...]

    @property
    def solicited(self) -> bool:
        """Whether this block answers a command the client sent.

        Examples
        --------
        >>> Block(1, 2, 1, False, ()).solicited
        True
        >>> Block(1, 2, 0, False, ()).solicited
        False
        """
        return bool(self.flags & _SOLICITED)


@dataclass(frozen=True)
class Output:
    r"""Pane output from ``%output`` or ``%extended-output``.

    The two notifications carry the same payload; ``%extended-output`` appears
    once a client enables ``pause-after``. Consumers see one type.

    Attributes
    ----------
    pane : str
        Pane id, such as ``%0``.
    data : bytes
        Raw pane bytes with tmux's ``\ooo`` escapes decoded once. Decoding
        them as UTF-8 is the consumer's job, per pane and incrementally,
        because a multi-byte character can straddle two notifications.
    """

    pane: str
    data: bytes


@dataclass(frozen=True)
class SubscriptionChanged:
    """A ``%subscription-changed`` notification.

    Attributes
    ----------
    name : str
        The subscription name given to ``refresh-client -B``.
    session : str
        Session id, or ``-`` when the subscription is not session-scoped.
    window : str
        Window id, or ``-``.
    window_index : str
        Window index, or ``-``.
    pane : str
        Pane id, or ``-``.
    value : str
        The format's expansion.
    """

    name: str
    session: str
    window: str
    window_index: str
    pane: str
    value: str


@dataclass(frozen=True)
class Pause:
    """``%pause``: tmux stopped sending output for *pane*."""

    pane: str


@dataclass(frozen=True)
class Continue:
    """``%continue``: tmux resumed sending output for *pane*."""

    pane: str


@dataclass(frozen=True)
class Exit:
    """``%exit``: the server ended this client.

    Attributes
    ----------
    reason : str or None
        tmux's reason text, when it gave one.
    """

    reason: str | None = None


@dataclass(frozen=True)
class Notification:
    """Any other ``%`` notification, such as ``%window-add @3``.

    Attributes
    ----------
    name : str
        The name without ``%``.
    args : str
        The rest of the line, undecoded apart from UTF-8 with replacement.
        Window and session names can contain spaces, so splitting is the
        consumer's call.
    """

    name: str
    args: str


@dataclass(frozen=True)
class Stray:
    """A line outside any block that does not start with ``%``.

    tmux writes some messages, such as ``run-shell`` output, to a control
    client as bare lines between blocks. They are surfaced, never dropped.
    """

    line: bytes


ControlEvent: TypeAlias = (
    Block
    | Output
    | SubscriptionChanged
    | Pause
    | Continue
    | Exit
    | Notification
    | Stray
)


def decode_output(raw: bytes) -> bytes:
    r"""Decode tmux's ``\ooo`` escapes in pane output.

    tmux escapes bytes below 0x20 and the backslash as three octal digits.
    A backslash that is not followed by three octal digits stays literal.

    Parameters
    ----------
    raw : bytes
        The payload after ``%output %pane ``.

    Returns
    -------
    bytes
        The original pane bytes.

    Examples
    --------
    >>> decode_output(b"a\\015\\012b\\134")
    b'a\r\nb\\'
    >>> decode_output(b"\\134015")
    b'\\015'
    """
    if b"\\" not in raw:
        return raw
    return _OCTAL.sub(lambda match: bytes([int(match.group(1), 8) & 0xFF]), raw)


def quote(arg: str) -> str:
    r"""Quote one argument for tmux's command parser.

    Single quotes expand nothing, so the only escape is the quote itself. A
    single-quoted string cannot hold a newline, because the line would end, so
    an argument with CR or LF goes in double quotes with ``\\``, ``\"``,
    ``\$``, ``\n`` and ``\r`` escaped.

    Parameters
    ----------
    arg : str
        The argument.

    Returns
    -------
    str
        A quoted token.

    Raises
    ------
    ValueError
        *arg* contains NUL, which no tmux transport carries.

    Examples
    --------
    >>> quote("a b")
    "'a b'"
    >>> quote("it's;")
    "'it'\\''s;'"
    >>> quote("a\nb$x")
    '"a\\nb\\$x"'
    >>> quote("a\0b")
    Traceback (most recent call last):
    ...
    ValueError: tmux command arguments cannot contain NUL
    """
    if "\0" in arg:
        msg = "tmux command arguments cannot contain NUL"
        raise ValueError(msg)
    if "\n" not in arg and "\r" not in arg:
        return "'" + arg.replace("'", "'\\''") + "'"
    escaped = (
        arg.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return '"' + escaped + '"'


def encode_command(args: Sequence[str]) -> bytes:
    r"""Encode one command line, newline included, for control-mode stdin.

    Every argument is quoted, so ``;`` inside data stays data. A
    :class:`~libtmux.engines.base.CommandSeparator` is the one token written
    bare, which makes the line several commands.

    Encoding finishes before the caller queues a reply slot, so an argument
    that cannot be encoded never leaves a slot behind.

    Parameters
    ----------
    args : sequence of str
        The command and its arguments.

    Returns
    -------
    bytes
        UTF-8 line ending in ``\n``.

    Raises
    ------
    ValueError
        *args* is empty, or an argument contains NUL.

    Examples
    --------
    >>> from libtmux.engines.base import CommandSeparator
    >>> encode_command(("kill-window", CommandSeparator(";"), "list-windows"))
    b"'kill-window' ; 'list-windows'\n"
    >>> encode_command(())
    Traceback (most recent call last):
    ...
    ValueError: a tmux command needs at least one argument
    """
    if not args:
        msg = "a tmux command needs at least one argument"
        raise ValueError(msg)
    tokens = [";" if is_command_separator(arg) else quote(arg) for arg in args]
    return (" ".join(tokens) + "\n").encode()


def _parse_guard(line: bytes, prefix: bytes) -> tuple[int, int, int]:
    parts = line[len(prefix) :].split(b" ")
    if len(parts) == _GUARD_FIELDS and all(part.isdigit() for part in parts):
        time, number, flags = (int(part) for part in parts)
        return time, number, flags
    msg = f"malformed control-mode guard: {line!r}"
    raise exc.ControlProtocolError(msg)


class ControlModeParser:
    r"""Incremental parser for the control-mode byte stream.

    Feed it whatever the transport delivered, in chunks of any size; it returns
    the events completed so far, in wire order. Position decides meaning: a
    line inside a block is body, whatever it looks like, and a block closes
    only on the exact guard that opened it, so command output that resembles
    ``%end`` stays body.

    Examples
    --------
    Chunk boundaries do not matter:

    >>> parser = ControlModeParser()
    >>> parser.feed(b"%begin 5 9 1\nre")
    []
    >>> parser.feed(b"ply\n%end 5 9 1\n")
    [Block(time=5, number=9, flags=1, is_error=False, body=(b'reply',))]

    Output that looks like a closing guard stays body:

    >>> events = parser.feed(b"%begin 5 10 1\n%end 5 99 1\n%end 5 10 1\n")
    >>> events[0].body
    (b'%end 5 99 1',)

    A guard that will not parse is an error, never a guess:

    >>> parser.feed(b"%begin nonsense\n")
    Traceback (most recent call last):
    ...
    libtmux.exc.ControlProtocolError: malformed control-mode guard: b'%begin nonsense'
    """

    __slots__ = ("_body", "_close_end", "_close_error", "_guard", "_partial")

    def __init__(self) -> None:
        self._partial = b""
        self._guard: tuple[int, int, int] | None = None
        self._close_end = b""
        self._close_error = b""
        self._body: list[bytes] = []

    @property
    def in_block(self) -> bool:
        """Whether a ``%begin`` is open and its closing guard has not arrived.

        A driver that sees EOF while this is true lost part of a reply.
        """
        return self._guard is not None

    def feed(self, data: bytes) -> list[ControlEvent]:
        """Consume *data* and return the events it completed.

        Parameters
        ----------
        data : bytes
            Any chunk of tmux's stdout.

        Returns
        -------
        list of ControlEvent
            Completed events in wire order. A trailing partial line is held.

        Raises
        ------
        ~libtmux.exc.ControlProtocolError
            A ``%begin`` guard is malformed, or a notification of a known
            shape is truncated. The parser state is undefined afterwards; a
            driver rebuilds the connection and a new parser.
        """
        if not data:
            return []
        lines = (self._partial + data).split(b"\n")
        self._partial = lines.pop()
        events: list[ControlEvent] = []
        for line in lines:
            event = self._line(line)
            if event is not None:
                events.append(event)
        return events

    def _line(self, line: bytes) -> ControlEvent | None:
        if self._guard is not None:
            if line == self._close_end or line == self._close_error:
                time, number, flags = self._guard
                block = Block(
                    time,
                    number,
                    flags,
                    line == self._close_error,
                    tuple(self._body),
                )
                self._guard = None
                self._body = []
                return block
            self._body.append(line)
            return None
        if line.startswith(_BEGIN):
            self._guard = _parse_guard(line, _BEGIN)
            tail = line[len(_BEGIN) :]
            self._close_end = b"%end " + tail
            self._close_error = b"%error " + tail
            return None
        if not line.startswith(b"%"):
            return Stray(line)
        return _notification(line)


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


def _notification(line: bytes) -> ControlEvent:
    name, _, rest = line[1:].partition(b" ")
    if name == b"output":
        pane, _, data = rest.partition(b" ")
        return Output(_text(pane), decode_output(data))
    if name == b"extended-output":
        head, sep, data = rest.partition(b" : ")
        if not sep and not rest.endswith(b" :"):
            msg = f"malformed %extended-output: {line!r}"
            raise exc.ControlProtocolError(msg)
        pane = head.partition(b" ")[0]
        return Output(_text(pane), decode_output(data))
    if name == b"exit":
        return Exit(_text(rest) if rest else None)
    if name == b"pause":
        return Pause(_text(rest))
    if name == b"continue":
        return Continue(_text(rest))
    if name == b"subscription-changed":
        head, sep, value = rest.partition(b" : ")
        fields = _text(head).split(" ")
        if sep and len(fields) == _SUBSCRIPTION_FIELDS:
            name_, session, window, index, pane_id = fields
            return SubscriptionChanged(
                name_, session, window, index, pane_id, _text(value)
            )
    return Notification(_text(name), _text(rest))


class BlockSequenceMonitor:
    """Check that command numbers only increase.

    tmux stamps every command with a server-wide counter and echoes it in the
    guard, so blocks reach a client in strictly increasing number order. A
    block at or below the last one seen means the reader is pairing a stale
    block with a newer request, which shows up downstream as another command's
    output. One integer comparison turns that into an error.

    Examples
    --------
    >>> monitor = BlockSequenceMonitor()
    >>> monitor.check(Block(1, 4, 1, False, ()))
    >>> monitor.check(Block(1, 9, 1, False, ()))
    >>> monitor.check(Block(1, 7, 1, False, ()))
    Traceback (most recent call last):
    ...
    libtmux.exc.ControlProtocolError: control-mode block number 7 after 9
    """

    __slots__ = ("_last",)

    def __init__(self) -> None:
        self._last: int | None = None

    @property
    def last(self) -> int | None:
        """The highest command number seen, or ``None`` before any block."""
        return self._last

    def check(self, block: Block) -> None:
        """Record *block*; raise if its number did not advance.

        Raises
        ------
        ~libtmux.exc.ControlProtocolError
            ``block.number`` is not greater than the last one seen.
        """
        if self._last is not None and block.number <= self._last:
            msg = f"control-mode block number {block.number} after {self._last}"
            raise exc.ControlProtocolError(msg)
        self._last = block.number

    def reset(self) -> None:
        """Forget the sequence, as a new connection does."""
        self._last = None


def result_from_blocks(
    cmd: tuple[str, ...],
    blocks: Sequence[Block],
) -> CommandResult:
    r"""Merge the reply blocks one request produced into a :class:`CommandResult`.

    A command group answers with one block per command, and tmux stops at the
    first error, so the blocks are the commands that ran. Output lines are
    decoded as UTF-8 with ``backslashreplace``, trailing blanks come off stdout,
    and tmux's ``parse error: `` prefix, which only a control client sees, is
    removed so the message matches what the tmux CLI and every other engine
    report.

    Parameters
    ----------
    cmd : tuple of str
        The argv to report as :attr:`CommandResult.cmd`.
    blocks : sequence of Block
        The replies, in order.

    Returns
    -------
    CommandResult
        ``returncode`` is 1 when any block was an error, else 0.

    Examples
    --------
    >>> ok = Block(1, 2, 1, False, (b"a", b"b", b""))
    >>> result_from_blocks(("tmux", "x"), [ok])
    CommandResult(cmd=('tmux', 'x'), stdout=('a', 'b'), stderr=(), returncode=0)

    >>> bad = Block(1, 3, 1, True, (b"parse error: unknown command: nope",))
    >>> result_from_blocks(("tmux", "nope"), [bad]).stderr
    ('unknown command: nope',)
    """
    stdout: list[str] = []
    stderr: list[str] = []
    failed = False
    for block in blocks:
        lines = [line.decode("utf-8", "backslashreplace") for line in block.body]
        if block.is_error:
            failed = True
            lines[:1] = [lines[0].removeprefix("parse error: ")] if lines else []
            stderr += [line for line in lines if line]
        else:
            stdout += lines
    while stdout and stdout[-1] == "":
        stdout.pop()
    return CommandResult(
        cmd=cmd,
        stdout=tuple(stdout),
        stderr=tuple(stderr),
        returncode=1 if failed else 0,
    )
