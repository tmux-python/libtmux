"""Control-mode client context manager and I/O-free wire parser."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import typing as t
from dataclasses import dataclass

if t.TYPE_CHECKING:
    import types

    from libtmux.server import Server
    from libtmux.session import Session

_GUARD_RE: t.Final[re.Pattern[bytes]] = re.compile(
    rb"^%(begin|end|error) (\d+) (\d+) (\d+)$"
)
_CONTROL_OCTAL_RE: t.Final[re.Pattern[bytes]] = re.compile(rb"\\([0-7]{3})")
_SUBSCRIPTION_RE: t.Final[re.Pattern[bytes]] = re.compile(
    rb"^%subscription-changed (\S+) (\S+) (\S+) (\S+) (\S+) : (.*)$"
)
_OUTPUT_RE: t.Final[re.Pattern[bytes]] = re.compile(rb"^%output (%\d+) (.*)$")
_EXTENDED_OUTPUT_RE: t.Final[re.Pattern[bytes]] = re.compile(
    rb"^%extended-output (%\d+) (\d+)(?: [^:]*)? : (.*)$"
)


def unescape_control_output(payload: bytes | str) -> bytes:
    r"""Decode octal escapes (``\NNN``) in a ``%output`` payload into raw bytes.

    Examples
    --------
    >>> from libtmux._internal.control_mode import unescape_control_output
    >>> unescape_control_output(b"hello\\012world\\134")
    b'hello\nworld\\'
    """
    raw = (
        payload.encode("utf-8", errors="surrogateescape")
        if isinstance(payload, str)
        else payload
    )
    return _CONTROL_OCTAL_RE.sub(lambda m: bytes((int(m.group(1), 8),)), raw)


def _quote_control_token(token: str) -> str:
    if "\x00" in token:
        msg = "tmux control-mode arguments cannot contain NUL"
        raise ValueError(msg)
    if "\n" in token or "\r" in token:
        return "".join(f"\\{byte:03o}" for byte in token.encode("utf-8"))
    if token == "":
        return "''"
    return shlex.quote(token)


def render_control_command(commands: tuple[tuple[str, ...], ...]) -> bytes:
    r"""Render structured command tuples into a single ``tmux -C`` input line.

    Rejects empty commands so callers can never send a bare newline that
    detaches the control client.

    Examples
    --------
    >>> from libtmux._internal.control_mode import render_control_command
    >>> render_control_command((("display-message", "-p", "a b"),))
    b"display-message -p 'a b'\n"
    """
    if not commands or any(not cmd for cmd in commands):
        msg = "control-mode command cannot be empty"
        raise ValueError(msg)
    parts: list[str] = []
    for index, cmd in enumerate(commands):
        if index > 0:
            parts.append(";")
        for token in cmd:
            if token == ";":
                parts.append(r"\;")
            elif token.endswith(";") and not token.endswith(r"\;"):
                parts.append(_quote_control_token(token))
            else:
                parts.append(_quote_control_token(token))
    line = " ".join(parts)
    if not line.strip():
        msg = "control-mode command rendered empty line"
        raise ValueError(msg)
    return line.encode("utf-8") + b"\n"


@dataclass(frozen=True, slots=True)
class ControlFrame:
    """Completed ``%begin`` / ``%end`` or ``%error`` block from ``tmux -C``.

    Attributes
    ----------
    timestamp : int
        Server epoch timestamp on the guard header.
    number : int
        Command item number assigned by ``cmdq_append``.
    flags : int
        ``1`` for commands submitted on control ``stdin``; ``0`` for
        unsolicited blocks such as initial attach or ``after-*`` hooks.
    ok : bool
        ``True`` for ``%end``, ``False`` for ``%error``.
    lines : tuple[bytes, ...]
        Raw lines emitted inside the guard block.
    """

    timestamp: int
    number: int
    flags: int
    ok: bool
    lines: tuple[bytes, ...]

    @property
    def is_command_reply(self) -> bool:
        """Return ``True`` when ``flags != 0`` (originated from control stdin)."""
        return self.flags != 0

    @property
    def payload(self) -> bytes:
        r"""Join ``lines`` with ``\n`` (trailing ``\n`` when non-empty)."""
        if not self.lines:
            return b""
        return b"\n".join(self.lines) + b"\n"


@dataclass(frozen=True, slots=True)
class SubscriptionChanged:
    """Parsed ``%subscription-changed`` notification from ``refresh-client -B``.

    Attributes
    ----------
    name : str
        Subscription identifier passed to ``refresh-client -B``.
    session_id : str
        Session ID (e.g. ``"$0"``).
    window_id : str or None
        Window ID (e.g. ``"@0"``), or ``None`` for session-scoped subscriptions.
    window_index : int or None
        Window index, or ``None`` when ``"-"``.
    pane_id : str or None
        Pane ID (e.g. ``"%0"``), or ``None`` for session/window subscriptions.
    value : bytes
        Raw evaluated format bytes after `` : ``.
    """

    name: str
    session_id: str
    window_id: str | None
    window_index: int | None
    pane_id: str | None
    value: bytes


@dataclass(frozen=True, slots=True)
class PaneOutput:
    """Decoded ``%output`` or ``%extended-output`` notification.

    Attributes
    ----------
    pane_id : str
        Source pane identifier (e.g. ``"%0"``).
    data : bytes
        Octal-unescaped raw pane output bytes.
    age_ms : int or None
        Output age in milliseconds for ``%extended-output``, else ``None``.
    """

    pane_id: str
    data: bytes
    age_ms: int | None = None


@dataclass(frozen=True, slots=True)
class ControlNotification:
    """Generic ``%...`` control notification line outside a guard block.

    Attributes
    ----------
    kind : str
        Notification name without leading ``%`` (e.g. ``"pause"``, ``"exit"``).
    raw : bytes
        Full raw notification line without trailing newline.
    """

    kind: str
    raw: bytes


ControlEvent: t.TypeAlias = (
    ControlFrame | SubscriptionChanged | PaneOutput | ControlNotification
)


class ControlModeParser:
    r"""Incremental, I/O-free state machine for tmux control-mode byte streams.

    Tracks ``in_guard`` state so literal ``%begin`` lines printed inside a
    command's output cannot start a nested guard block, and separates
    ``flags == 1`` command replies from ``flags == 0`` unsolicited hook blocks.

    Examples
    --------
    >>> from libtmux._internal.control_mode import ControlFrame, ControlModeParser
    >>> parser = ControlModeParser()
    >>> events = parser.feed(
    ...     b"%begin 100 1 0\n%end 100 1 0\n"
    ...     b"%begin 100 2 1\n%begin fake 9 1\nok\n%end 100 2 1\n"
    ... )
    >>> [(e.flags, e.lines) for e in events if isinstance(e, ControlFrame)]
    [(0, ()), (1, (b'%begin fake 9 1', b'ok'))]
    """

    __slots__ = ("_active_guard", "_buffer", "_guard_lines")

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._active_guard: tuple[int, int, int] | None = None
        self._guard_lines: list[bytes] = []

    def feed(self, chunk: bytes) -> list[ControlEvent]:
        """Consume *chunk* and return completed frames and notifications."""
        if not chunk:
            return []
        self._buffer.extend(chunk)
        events: list[ControlEvent] = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                break
            line = bytes(self._buffer[:newline])
            if line.endswith(b"\r"):
                line = line[:-1]
            del self._buffer[: newline + 1]
            event = self._consume_line(line)
            if event is not None:
                events.append(event)
        return events

    def _consume_line(self, line: bytes) -> ControlEvent | None:
        if self._active_guard is not None:
            match = _GUARD_RE.match(line)
            if match is not None:
                kind, ts_b, num_b, flags_b = match.groups()
                header = (int(ts_b), int(num_b), int(flags_b))
                if kind in (b"end", b"error") and header == self._active_guard:
                    lines = tuple(self._guard_lines)
                    self._guard_lines.clear()
                    self._active_guard = None
                    return ControlFrame(
                        timestamp=header[0],
                        number=header[1],
                        flags=header[2],
                        ok=kind == b"end",
                        lines=lines,
                    )
            self._guard_lines.append(line)
            return None

        match = _GUARD_RE.match(line)
        if match is not None and match.group(1) == b"begin":
            _, ts_b, num_b, flags_b = match.groups()
            self._active_guard = (int(ts_b), int(num_b), int(flags_b))
            self._guard_lines.clear()
            return None

        sub_match = _SUBSCRIPTION_RE.match(line)
        if sub_match is not None:
            name_b, sid_b, wid_b, widx_b, pid_b, val_b = sub_match.groups()
            return SubscriptionChanged(
                name=name_b.decode("utf-8", errors="replace"),
                session_id=sid_b.decode("ascii", errors="replace"),
                window_id=None
                if wid_b == b"-"
                else wid_b.decode("ascii", errors="replace"),
                window_index=None if widx_b == b"-" else int(widx_b),
                pane_id=None
                if pid_b == b"-"
                else pid_b.decode("ascii", errors="replace"),
                value=val_b,
            )

        out_match = _OUTPUT_RE.match(line)
        if out_match is not None:
            pane_b, payload_b = out_match.groups()
            return PaneOutput(
                pane_id=pane_b.decode("ascii"),
                data=unescape_control_output(payload_b),
            )

        ext_match = _EXTENDED_OUTPUT_RE.match(line)
        if ext_match is not None:
            pane_b, age_b, payload_b = ext_match.groups()
            return PaneOutput(
                pane_id=pane_b.decode("ascii"),
                data=unescape_control_output(payload_b),
                age_ms=int(age_b),
            )

        if line.startswith(b"%"):
            head, _, _ = line[1:].partition(b" ")
            return ControlNotification(
                kind=head.decode("ascii", errors="replace"),
                raw=line,
            )
        return None


class ControlMode:
    """Context manager that spawns an attached ``tmux -u -C`` client.

    Parameters
    ----------
    server : Server
        Target tmux server instance.
    session : Session
        Session to attach the control client to.

    Examples
    --------
    >>> with ControlMode(server=server, session=session) as ctl:
    ...     clients = server.list_clients()
    ...     assert len(clients) > 0
    ...     assert ctl.client_name != ''
    """

    server: Server
    session: Session
    client_name: str
    stdout: t.IO[str]

    _proc: subprocess.Popen[str]
    _write_fd: int

    def __init__(self, server: Server, session: Session) -> None:
        self.server = server
        self.session = session

    def __enter__(self) -> t.Self:
        """Spawn control-mode client and wait for registration."""
        read_fd, self._write_fd = os.pipe()

        tmux_bin = self.server.tmux_bin or "tmux"

        cmd = [
            tmux_bin,
            *self.server._socket_args(),
            "-u",
            "-C",
            "attach-session",
            "-t",
            str(self.session.session_id),
        ]

        try:
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdin=read_fd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
            finally:
                os.close(read_fd)
        except BaseException:
            os.close(self._write_fd)
            raise

        self.stdout = self._proc.stdout  # type: ignore[assignment]
        client_pid = str(self._proc.pid)

        def client_registered() -> bool:
            result = self.server.cmd(
                "list-clients",
                "-F",
                "#{client_pid}\t#{client_name}",
            )
            for line in result.stdout:
                pid, _, client_name = line.partition("\t")
                if pid == client_pid and client_name:
                    self.client_name = client_name.strip()
                    return True
            return False

        from libtmux.test.retry import retry_until

        try:
            retry_until(client_registered, 3, raises=True)
        except Exception:
            os.close(self._write_fd)
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            raise

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Terminate control-mode client."""
        os.close(self._write_fd)

        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
