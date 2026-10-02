"""Tests for :mod:`libtmux.engines.control.protocol`, the I/O-free wire core."""

from __future__ import annotations

import json
import pathlib
import random
import selectors
import subprocess
import typing as t

import pytest

from libtmux import exc
from libtmux.engines import CommandSeparator, SubprocessEngine
from libtmux.engines.control import protocol
from libtmux.engines.control.protocol import (
    Block,
    BlockSequenceMonitor,
    Continue,
    ControlModeParser,
    Exit,
    Notification,
    Output,
    Pause,
    Stray,
    SubscriptionChanged,
    decode_output,
    encode_command,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "control_mode"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())
TRANSCRIPTS = sorted(FIXTURES.glob("*.ctl"))
#: Command lines the recorder sent per transcript, counting the ``;`` group as two.
SOLICITED_BLOCKS = 17


def parse_all(data: bytes, cuts: t.Sequence[int] = ()) -> list[protocol.ControlEvent]:
    """Feed *data* split at *cuts* and return every event."""
    parser = ControlModeParser()
    events: list[protocol.ControlEvent] = []
    previous = 0
    for cut in (*sorted(cuts), len(data)):
        events += parser.feed(data[previous:cut])
        previous = cut
    assert not parser.in_block
    return events


def test_block_body_and_error() -> None:
    """A reply is its body; ``%error`` marks a failure."""
    events = parse_all(
        b"%begin 9 1 1\na\nb\n%end 9 1 1\n%begin 9 2 1\nbad\n%error 9 2 1\n",
    )

    assert events == [
        Block(9, 1, 1, False, (b"a", b"b")),
        Block(9, 2, 1, True, (b"bad",)),
    ]


@pytest.mark.parametrize(
    "forged",
    [
        b"%end 9 99 1",
        b"%end 8 1 1",
        b"%end 9 1 0",
        b"%error 9 1 0",
        b"%end 9 1 1 ",
    ],
)
def test_output_resembling_a_closing_guard_stays_body(forged: bytes) -> None:
    """Only the exact opening guard closes a block."""
    events = parse_all(b"%begin 9 1 1\n" + forged + b"\n%end 9 1 1\n")

    assert events == [Block(9, 1, 1, False, (forged,))]


def test_notifications_keep_wire_position() -> None:
    """A notification between blocks is an event of its own, in order."""
    events = parse_all(
        b"%begin 1 1 1\n%end 1 1 1\n%window-add @3\n%begin 1 2 1\n%end 1 2 1\n",
    )

    assert [type(event) for event in events] == [Block, Notification, Block]
    assert events[1] == Notification("window-add", "@3")


def test_notification_args_keep_spaces() -> None:
    """Window names may contain spaces; the parser does not split them."""
    (event,) = parse_all(b"%window-renamed @1 my long name\n")

    assert event == Notification("window-renamed", "@1 my long name")


def test_typed_events() -> None:
    """Known notifications become typed events."""
    events = parse_all(
        b"%pause %2\n%continue %2\n%exit\n%exit server exited\n"
        b"%subscription-changed sub $0 @1 3 %4 : a : b\n"
        b"%subscription-changed bare $0 - - - : x\n",
    )

    assert events == [
        Pause("%2"),
        Continue("%2"),
        Exit(None),
        Exit("server exited"),
        SubscriptionChanged("sub", "$0", "@1", "3", "%4", "a : b"),
        SubscriptionChanged("bare", "$0", "-", "-", "-", "x"),
    ]


def test_unknown_subscription_shape_degrades_to_notification() -> None:
    """A shape the parser does not know is kept, not fatal."""
    (event,) = parse_all(b"%subscription-changed only-two fields\n")

    assert event == Notification("subscription-changed", "only-two fields")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (b"%output %0 plain\n", Output("%0", b"plain")),
        (b"%output %0 \\015\\012\\134\\011\n", Output("%0", b"\r\n\\\t")),
        (b"%output %0 \n", Output("%0", b"")),
        (b"%extended-output %0 12 : tail \\134\n", Output("%0", b"tail \\")),
        (b"%extended-output %3 0 : \n", Output("%3", b"")),
        (b"%extended-output %3 0 :\n", Output("%3", b"")),
        (b"%output %0 \xc3\xa9\n", Output("%0", "\u00e9".encode())),
    ],
)
def test_output_forms_normalise(line: bytes, expected: Output) -> None:
    """``%output`` and ``%extended-output`` yield one ``Output`` type."""
    assert parse_all(line) == [expected]


def test_octal_is_decoded_once() -> None:
    """A decoded backslash is not decoded again."""
    assert decode_output(b"\\134015") == b"\\015"
    assert decode_output(b"\\12") == b"\\12"
    assert decode_output(b"no escapes") == b"no escapes"


def test_stray_line_is_surfaced() -> None:
    """A bare line outside a block is kept, never dropped."""
    assert parse_all(b"hi\n%exit\n") == [Stray(b"hi"), Exit(None)]


@pytest.mark.parametrize(
    "stream",
    [
        b"%begin 1 2\n",
        b"%begin 1 two 3\n",
        b"%begin 1 2 3 4\n",
        b"%extended-output %0 3 no separator\n",
    ],
)
def test_malformed_framing_raises(stream: bytes) -> None:
    """Malformed framing is an error, never resynchronised by guessing."""
    with pytest.raises(exc.ControlProtocolError):
        ControlModeParser().feed(stream)


def test_in_block_reports_a_truncated_reply() -> None:
    """EOF while ``in_block`` means a reply was cut short."""
    parser = ControlModeParser()
    parser.feed(b"%begin 1 2 3\npartial\n")

    assert parser.in_block


def test_sequence_monitor_rejects_a_stale_block() -> None:
    """A number that does not advance means a desynchronised reader."""
    monitor = BlockSequenceMonitor()
    monitor.check(Block(1, 5, 1, False, ()))

    with pytest.raises(exc.ControlProtocolError):
        monitor.check(Block(1, 5, 1, False, ()))
    monitor.reset()
    monitor.check(Block(1, 1, 1, False, ()))
    assert monitor.last == 1


def test_encode_refuses_before_producing_a_line() -> None:
    """A refused argument raises, so a caller never queues a slot for it."""
    with pytest.raises(ValueError, match="NUL"):
        encode_command(("display-message", "a\0b"))
    with pytest.raises(ValueError, match="at least one"):
        encode_command(())


def test_encode_separator_is_the_only_bare_token() -> None:
    """Data ``;`` stays quoted; a ``CommandSeparator`` is bare."""
    assert encode_command(("a", ";", CommandSeparator(";"), "b")) == (
        b"'a' ';' ; 'b'\n"
    )


@pytest.mark.parametrize("name", [path.stem for path in TRANSCRIPTS])
def test_recorded_transcript_invariants(name: str) -> None:
    """Every recorded transcript parses cleanly and keeps its shape."""
    data = (FIXTURES / f"{name}.ctl").read_bytes()
    events = parse_all(data)
    blocks = [event for event in events if isinstance(event, Block)]
    monitor = BlockSequenceMonitor()
    for block in blocks:
        monitor.check(block)

    assert isinstance(events[-1], Exit)
    assert blocks[0].flags == 0  # the attach acknowledgement is not a reply
    if name.endswith("-kill"):
        assert sum(block.solicited for block in blocks) == 1
        return
    assert sum(block.solicited for block in blocks) == SOLICITED_BLOCKS
    assert sum(block.is_error for block in blocks) == 1  # the deliberate `bogus`
    assert sum(isinstance(event, Pause) for event in events) == 1
    # Before 3.8 tmux writes %continue inside the reply of the command that
    # caused it, so position decides: it is body there and an event after.
    continues = sum(isinstance(event, Continue) for event in events) + sum(
        line == b"%continue %0" for block in blocks for line in block.body
    )
    assert continues == 1
    assert any(isinstance(event, SubscriptionChanged) for event in events)
    assert any(isinstance(event, Notification) for event in events)
    output = b"".join(event.data for event in events if isinstance(event, Output))
    assert MANIFEST[name]["marker"].encode() + b"\t" in output


@pytest.mark.parametrize("name", [path.stem for path in TRANSCRIPTS])
def test_recorded_transcript_is_independent_of_chunking(name: str) -> None:
    """Random cut points never change what a transcript parses to."""
    data = (FIXTURES / f"{name}.ctl").read_bytes()
    whole = parse_all(data)
    rng = random.Random(name)
    for _ in range(12):
        cuts = [rng.randrange(len(data) + 1) for _ in range(rng.randrange(1, 40))]
        assert parse_all(data, cuts) == whole
    if len(data) < 1000:
        assert parse_all(data, range(len(data))) == whole


def test_fuzz_never_raises_anything_but_a_protocol_error() -> None:
    """Arbitrary bytes either parse or raise ``ControlProtocolError``."""
    rng = random.Random(20261002)
    alphabet = [
        b"%begin ",
        b"%end ",
        b"%error ",
        b"%output ",
        b"%extended-output ",
        b"%subscription-changed ",
        b"%exit",
        b" : ",
        b"\n",
        b"\\",
        b"\\015",
        b"1",
        b"9 9 9",
        b"x",
        b"\xff",
    ]
    for _ in range(400):
        stream = b"".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 60)))
        parser = ControlModeParser()
        try:
            parser.feed(stream)
        except exc.ControlProtocolError:
            continue


AWKWARD_VALUES = [
    "plain",
    "with space",
    "semi;colon",
    "trailing;",
    ";",
    "it's",
    'say "hi"',
    "dollar $HOME $(x)",
    "fmt #{pane_id} #S",
    "tab\there",
    "line1\nline2",
    "back\\slash",
    "caf\u00e9 \u2603",
    "percent %0 %*",
    "x" * 5000,
]


class ControlClient:
    """Test-only driver: one ``tmux -C attach-session`` and a parser.

    It encodes before it writes and reads until the next solicited block, which
    is all the round-trip tests need from a transport.
    """

    def __init__(self, server: Server, session_id: str) -> None:
        engine = SubprocessEngine.for_server(server)
        argv = engine.connection.argv("-C", "attach-session", "-E", "-t", session_id)
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.parser = ControlModeParser()
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        self.read(solicited=False)  # the attach acknowledgement

    def read(self, *, solicited: bool = True) -> Block:
        """Return the next block, skipping notifications."""
        assert self.proc.stdout is not None
        while True:
            if not self.selector.select(timeout=10):
                msg = "no control-mode reply within 10 s"
                raise TimeoutError(msg)
            chunk = self.proc.stdout.read(65536)
            assert chunk, "control client closed"
            for event in self.parser.feed(chunk):
                if isinstance(event, Block) and event.solicited == solicited:
                    return event

    def run(self, *args: str) -> Block:
        """Send one command and return its reply block."""
        assert self.proc.stdin is not None
        self.proc.stdin.write(encode_command(args))
        return self.read()

    def close(self) -> None:
        """Detach and reap the client."""
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.proc.stdin.close()
        self.proc.wait(timeout=5)
        self.selector.close()
        self.proc.stdout.close()


@pytest.mark.parametrize("value", AWKWARD_VALUES, ids=range(len(AWKWARD_VALUES)))
def test_quoting_round_trip_on_real_tmux(server: Server, value: str) -> None:
    """A value stored over control mode reads back as the argv path stores it.

    tmux itself mangles a few values on either path (a trailing ``;`` on argv,
    ``$`` on 3.4), so the control path is compared with argv where tmux agrees
    with itself and with the original value where argv cannot be trusted.
    """
    session = server.new_session("ctl_rt")
    client = ControlClient(server, session.session_id or "")
    try:
        stored = client.run("set-option", "-g", "@rt_ctl", value)
        assert not stored.is_error, stored.body
        shown = client.run("show-options", "-gqv", "@rt_ctl")
        over_control = b"\n".join(shown.body).decode()
    finally:
        client.close()

    server.cmd("set-option", "-g", "@rt_argv", value)
    over_argv = "\n".join(server.cmd("show-options", "-gqv", "@rt_argv").stdout)

    if value.endswith(";"):
        assert over_control == value
    else:
        assert over_control == over_argv
