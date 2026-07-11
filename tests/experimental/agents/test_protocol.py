"""Round-trip tests: what the emitter writes is what the signals read back.

The encoder (``hooks.emit``) and the decoders (``signals``, ``monitor``,
``tree``) used to re-specify the OSC 3008 grammar independently, and no test
crossed the two. These tests cross it: every case drives the *real* emitter and
asserts the *real* decoder recovers the payload -- so a change to one end that
the other doesn't follow fails here.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.agents import protocol
from libtmux.experimental.agents.hooks.emit import emit
from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.signals import OptionSignal, OscSignal
from libtmux.experimental.agents.state import AgentState
from libtmux.experimental.agents.tree import PANE_FORMAT

if t.TYPE_CHECKING:
    import pathlib


class SignalCase(t.NamedTuple):
    """One agent signal, as the emitter's CLI-level arguments."""

    test_id: str
    state: str
    name: str | None
    expected_state: AgentState


SIGNAL_CASES = (
    SignalCase("running", "running", None, AgentState.RUNNING),
    SignalCase("idle_named", "idle", "claude", AgentState.IDLE),
    SignalCase("awaiting_named", "awaiting_input", "codex", AgentState.AWAITING_INPUT),
    SignalCase("done", "done", None, AgentState.DONE),
    SignalCase("exited_named", "exited", "aider", AgentState.EXITED),
    SignalCase("garbage_is_unknown", "nonsense", None, AgentState.UNKNOWN),
)

IDS = [c.test_id for c in SIGNAL_CASES]


class _FakeEngine:
    """The minimum surface :class:`AgentMonitor` touches when only ingesting."""

    async def run(self, request: object) -> None:
        """Never called: these tests only drive the synchronous reducer."""

    async def subscribe(self) -> None:
        """Never called: these tests only drive the synchronous reducer."""

    def add_subscription(self, spec: str) -> None:
        """Record nothing; the monitor installs this on ``start()`` only."""

    def set_attach_targets(self, ids: list[str]) -> None:
        """Record nothing; the monitor attaches on ``start()`` only."""


def _emit_osc(case: SignalCase, tty: pathlib.Path) -> bytes:
    """Drive the real remote-path emitter and return the bytes it wrote."""
    tty.write_bytes(b"")
    emit(case.state, name=case.name, tty_path=str(tty), env={})
    return tty.read_bytes()


def _emit_option(case: SignalCase, pane_id: str) -> list[list[str]]:
    """Drive the real local-path emitter and return the tmux argv it ran."""
    calls: list[list[str]] = []
    emit(
        case.state,
        name=case.name,
        runner=lambda argv, **kw: calls.append(argv),
        env={"TMUX": "/tmp/sock,1,0", "TMUX_PANE": pane_id},
    )
    return calls


@pytest.mark.parametrize("case", SIGNAL_CASES, ids=IDS)
def test_osc_round_trip(case: SignalCase, tmp_path: pathlib.Path) -> None:
    """emit() → OSC bytes → OscSignal recovers the same state and name."""
    data = _emit_osc(case, tmp_path / "tty")

    readings = OscSignal().feed("%7", data)

    assert len(readings) == 1
    assert readings[0].pane_id == "%7"
    assert readings[0].state is case.expected_state
    assert readings[0].name == case.name
    assert readings[0].source == "osc"


@pytest.mark.parametrize("case", SIGNAL_CASES, ids=IDS)
def test_osc_round_trip_byte_fragmented(
    case: SignalCase,
    tmp_path: pathlib.Path,
) -> None:
    """The round trip survives tmux's byte-fragmented ``%output`` delivery."""
    data = _emit_osc(case, tmp_path / "tty")

    osc = OscSignal()
    readings = [r for i in range(len(data)) for r in osc.feed("%2", data[i : i + 1])]

    assert len(readings) == 1
    assert readings[0].state is case.expected_state
    assert readings[0].name == case.name


@pytest.mark.parametrize("case", SIGNAL_CASES, ids=IDS)
def test_osc_round_trip_through_monitor(
    case: SignalCase,
    tmp_path: pathlib.Path,
) -> None:
    """emit() → OSC bytes → ``%output`` notification → the monitor's agent tree."""
    data = _emit_osc(case, tmp_path / "tty")

    mon = AgentMonitor(_FakeEngine())
    mon.ingest(f"%output %5 {data.decode()}")

    (agent,) = mon.agents
    assert agent.pane_id == "%5"
    assert agent.state is case.expected_state
    assert agent.name == case.name


@pytest.mark.parametrize("case", SIGNAL_CASES, ids=IDS)
def test_option_round_trip_via_reconcile(case: SignalCase) -> None:
    """emit() → tmux set-option → the durable fields the monitor reconciles from.

    The reconcile path re-reads the options with ``list-panes``; model that by
    replaying the emitted ``set-option`` argv into a field mapping and decoding
    it with the same reader the monitor uses.
    """
    fields = dict.fromkeys(protocol.PANE_OPTIONS, "")
    for argv in _emit_option(case, "%1"):
        key, value = argv[-2], argv[-1]
        fields[key] = value

    payload = protocol.decode_option(fields)

    assert payload is not None
    assert AgentState.from_signal(payload.state) is case.expected_state
    assert payload.name == case.name


@pytest.mark.parametrize("case", SIGNAL_CASES, ids=IDS)
def test_option_round_trip_via_subscription(case: SignalCase) -> None:
    """emit() → tmux set-option → the ``%subscription-changed`` line it triggers.

    tmux echoes the *value* of the subscribed option back on the notification
    stream. Build that line from the protocol's own subscription name and the
    value the emitter actually set -- no literal from either end is retyped.
    """
    argv = _emit_option(case, "%3")[0]
    assert argv[-2] == protocol.OPTION_STATE
    value = argv[-1]

    line = f"%subscription-changed {protocol.SUBSCRIPTION_NAME} $0 @0 1 %3 : {value}"
    reading = OptionSignal.parse(line)

    assert reading is not None
    assert reading.pane_id == "%3"
    assert reading.state is case.expected_state
    assert reading.source == "option"


def test_subscription_spec_watches_the_option_the_emitter_writes() -> None:
    """The option the emitter sets is the one the subscription spec asks tmux for.

    This is the desync the codec exists to prevent: renaming the option on the
    write side while the ``refresh-client -B`` spec still watches the old name
    would silence the local channel with no other test noticing.
    """
    argv = _emit_option(SIGNAL_CASES[0], "%1")[0]
    written_option = argv[-2]

    assert f"#{{{written_option}}}" in protocol.SUBSCRIPTION
    assert written_option in PANE_FORMAT


def test_osc_round_trip_is_pure_at_the_codec_level() -> None:
    """decode_osc(encode_osc(p)) == p for every payload the emitter can build."""
    for case in SIGNAL_CASES:
        payload = protocol.Payload(case.state, case.name)
        decoded, tail = protocol.decode_osc(protocol.encode_osc(payload))
        assert decoded == [payload]
        assert tail == b""


def test_decode_osc_hands_back_a_partial_escape() -> None:
    """A truncated escape yields no payload and is returned for the next chunk."""
    complete = protocol.encode_osc(protocol.Payload("running"))
    head, rest = complete[:10], complete[10:]

    payloads, tail = protocol.decode_osc(head)
    assert payloads == []
    assert tail == head

    payloads, tail = protocol.decode_osc(tail + rest)
    assert payloads == [protocol.Payload("running")]
    assert tail == b""


def test_decode_osc_drains_several_escapes_from_one_chunk() -> None:
    """Back-to-back escapes in one ``%output`` frame all decode, in order."""
    chunk = protocol.encode_osc(protocol.Payload("running")) + protocol.encode_osc(
        protocol.Payload("idle", "claude")
    )

    payloads, tail = protocol.decode_osc(b"noise" + chunk + b"trailing")

    assert payloads == [
        protocol.Payload("running"),
        protocol.Payload("idle", "claude"),
    ]
    assert tail == b"trailing"
