"""The contract test that crosses the agent-state wire protocol's two ends.

The OSC 3008 agent-state protocol is specified twice, independently: the encoder
lives in :mod:`libtmux.experimental.agents.hooks.emit` and the decoder in
:mod:`libtmux.experimental.agents.signals`, with the option-key literals repeated
again in :mod:`libtmux.experimental.agents.monitor` and
:mod:`libtmux.experimental.agents.tree`.  Every other test in the suite exercises
exactly one end against a *hand-written* payload, so the two halves can drift
apart without a single test going red.

Every test in this module drives the **real** encoder and feeds its **real**
output to the **real** decoder.  Nothing here hand-writes a payload; if the magic
number, the delimiters, the option keys, or the terminator ever diverge, these
tests break.

Cases that are known to be broken *today* are pinned with
``xfail(strict=True)``.  They are not "expected behavior": they are the desyncs
this module found, held under glass so that whoever fixes the protocol gets an
``XPASS`` and is forced to retire the marker.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.agents import signals as signals_mod, tree as tree_mod
from libtmux.experimental.agents.hooks.emit import emit
from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.signals import OptionSignal, OscSignal, Reading
from libtmux.experimental.agents.state import AgentState
from libtmux.experimental.models.snapshots import PaneSnapshot

if t.TYPE_CHECKING:
    import pathlib

    from libtmux.session import Session

PANE_ID = "%7"


# ----------------------------------------------------------------------------
# Encoder drivers: the only way payloads enter this module is through emit().
# ----------------------------------------------------------------------------


def encode_osc(
    state: str,
    name: str | None,
    tty: pathlib.Path,
) -> bytes:
    """Run the real remote-path encoder and return the bytes it wrote.

    ``emit`` takes the remote branch whenever ``$TMUX`` is absent, writing the
    OSC escape to *tty_path* -- here a regular file standing in for the pane pty.

    Parameters
    ----------
    state : str
        Agent state string handed to the encoder.
    name : str or None
        Optional agent name handed to the encoder.
    tty : pathlib.Path
        File that stands in for ``/dev/tty``.

    Returns
    -------
    bytes
        The exact bytes the encoder put on the wire.
    """
    tty.write_bytes(b"")
    emit(state, name=name, tty_path=str(tty), env={})
    return tty.read_bytes()


def encode_options(state: str, name: str | None) -> dict[str, str]:
    """Run the real local-path encoder and return the tmux options it would set.

    ``emit`` takes the local branch when ``$TMUX`` / ``$TMUX_PANE`` are present,
    shelling out to ``tmux set-option -p -t <pane> <key> <value>``.  The injected
    runner captures the argv instead of executing it, so the option **keys** come
    from the encoder rather than from this test.

    Parameters
    ----------
    state : str
        Agent state string handed to the encoder.
    name : str or None
        Optional agent name handed to the encoder.

    Returns
    -------
    dict[str, str]
        ``{option_key: option_value}`` as the encoder would write it.
    """
    calls: list[list[str]] = []
    emit(
        state,
        name=name,
        runner=lambda argv, **_kwargs: calls.append(argv),
        env={"TMUX": "/tmp/tmux-1000/default,1,0", "TMUX_PANE": PANE_ID},
    )
    options: dict[str, str] = {}
    for argv in calls:
        assert argv[:5] == ["tmux", "set-option", "-p", "-t", PANE_ID]
        options[argv[5]] = argv[6]
    return options


# ----------------------------------------------------------------------------
# Decoder drivers.
# ----------------------------------------------------------------------------


def decode_osc(raw: bytes, *, chunk: int | None = None) -> list[Reading]:
    """Feed *raw* through the real OSC decoder, optionally *chunk* bytes at a time.

    Parameters
    ----------
    raw : bytes
        Encoder output.
    chunk : int or None
        Fragment size.  ``None`` feeds the buffer in one call.

    Returns
    -------
    list[Reading]
        Every reading the decoder produced.
    """
    osc = OscSignal()
    if chunk is None:
        return osc.feed(PANE_ID, raw)
    readings: list[Reading] = []
    for start in range(0, len(raw), chunk):
        readings.extend(osc.feed(PANE_ID, raw[start : start + chunk]))
    return readings


class _NullEngine:
    """The narrowest engine an :class:`AgentMonitor` will accept."""

    async def run(self, request: t.Any) -> None:
        """Accept and drop a request."""

    async def subscribe(self) -> None:
        """Accept and drop a subscribe."""

    def add_subscription(self, spec: str) -> None:
        """Accept and drop a subscription spec."""

    def set_attach_targets(self, ids: t.Any) -> None:
        """Accept and drop attach targets."""


def decode_options(options: dict[str, str]) -> tuple[AgentState, str | None]:
    """Feed encoder-written tmux options through the monitor's real option reader.

    This is the local channel end to end: the option keys come from the encoder,
    and the reader is :class:`~libtmux.experimental.agents.monitor.AgentMonitor`'s
    own reconcile path -- not a copy of it.  A key rename on either side lands
    here as a missing agent.

    Parameters
    ----------
    options : dict[str, str]
        ``{option_key: option_value}`` as :func:`encode_options` produced them.

    Returns
    -------
    tuple[AgentState, str | None]
        The state and name the monitor decoded, or ``(UNKNOWN, None)`` when the
        monitor saw no agent at all.
    """
    monitor = AgentMonitor(_NullEngine())
    pane = PaneSnapshot.from_format({"pane_id": PANE_ID, **options})
    monitor._observe_pane_options({PANE_ID: pane})
    agents = {agent.pane_id: agent for agent in monitor.agents}
    if PANE_ID not in agents:
        return AgentState.UNKNOWN, None
    return agents[PANE_ID].state, agents[PANE_ID].name


def decode_subscription(state_value: str) -> AgentState:
    """Decode the ``%subscription-changed`` line tmux emits for *state_value*.

    tmux echoes the option value verbatim in the subscription notification, so
    the value threaded through here is the one the encoder actually wrote.

    Parameters
    ----------
    state_value : str
        The ``@agent_state`` value the encoder wrote.

    Returns
    -------
    AgentState
        The state :class:`~libtmux.experimental.agents.signals.OptionSignal`
        decoded.
    """
    line = f"%subscription-changed agentstate $0 @0 1 {PANE_ID} : {state_value}"
    reading = OptionSignal.parse(line)
    assert reading is not None, "OptionSignal rejected a line tmux would send"
    assert reading.pane_id == PANE_ID
    return reading.state


# ----------------------------------------------------------------------------
# The state vocabulary survives the round trip -- every member, both channels.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("state", list(AgentState), ids=lambda s: s.value)
def test_osc_round_trips_every_state(
    state: AgentState,
    tmp_path: pathlib.Path,
) -> None:
    r"""Every ``AgentState`` the encoder emits decodes back to itself over OSC.

    This is the magic-number, delimiter and terminator contract in one assertion:
    a decoder that stopped recognizing ``3008``, ``state=``, or ``ESC \`` yields
    zero readings here.
    """
    raw = encode_osc(state.value, None, tmp_path / "tty")
    readings = decode_osc(raw)
    assert len(readings) == 1, f"decoder did not recognize encoder output: {raw!r}"
    assert readings[0].state is state
    assert readings[0].pane_id == PANE_ID
    assert readings[0].name is None
    assert readings[0].source == "osc"


@pytest.mark.parametrize("state", list(AgentState), ids=lambda s: s.value)
def test_options_round_trip_every_state(state: AgentState) -> None:
    """Every ``AgentState`` survives the local (tmux option) channel too."""
    options = encode_options(state.value, None)
    decoded_state, decoded_name = decode_options(options)
    assert decoded_state is state
    assert decoded_name is None
    assert decode_subscription(options["@agent_state"]) is state


# ----------------------------------------------------------------------------
# Names survive the round trip.
# ----------------------------------------------------------------------------


class NameCase(t.NamedTuple):
    """An agent name and the id it is reported under."""

    test_id: str
    name: str


BENIGN_NAMES = (
    NameCase("plain", "claude"),
    NameCase("with_space", "claude code"),
    NameCase("with_dash_and_dot", "gpt-5.4-high"),
    NameCase("with_equals", "model=opus"),
    NameCase("with_slash", "anthropic/claude"),
    NameCase("with_percent_sigil", "%1"),
    NameCase("unicode", "клод-über-\U0001f916"),
    NameCase("long", "a" * 512),
)


@pytest.mark.parametrize("case", BENIGN_NAMES, ids=[c.test_id for c in BENIGN_NAMES])
def test_osc_round_trips_names(case: NameCase, tmp_path: pathlib.Path) -> None:
    """A name the encoder sends comes back byte-identical from the decoder.

    Covers UTF-8 (the encoder ``.encode()``s, the decoder ``.decode()``s) and the
    ``=``-in-value case that a naive ``split("=")`` decoder would mangle.
    """
    raw = encode_osc("running", case.name, tmp_path / "tty")
    readings = decode_osc(raw)
    assert len(readings) == 1
    assert readings[0].state is AgentState.RUNNING
    assert readings[0].name == case.name


@pytest.mark.parametrize("case", BENIGN_NAMES, ids=[c.test_id for c in BENIGN_NAMES])
def test_options_round_trip_names(case: NameCase) -> None:
    """The same name survives the local (tmux option) channel."""
    decoded_state, decoded_name = decode_options(encode_options("running", case.name))
    assert decoded_state is AgentState.RUNNING
    assert decoded_name == case.name


def test_empty_name_is_absent_on_both_channels(tmp_path: pathlib.Path) -> None:
    """``name=""`` means "no name" -- and both ends agree on that."""
    raw = encode_osc("idle", "", tmp_path / "tty")
    assert decode_osc(raw)[0].name is None
    assert decode_options(encode_options("idle", "")) == (AgentState.IDLE, None)


# ----------------------------------------------------------------------------
# The wire survives tmux's byte-fragmented %output delivery.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("chunk", [1, 2, 3, 5, 7, 11])
def test_osc_round_trips_under_fragmentation(
    chunk: int,
    tmp_path: pathlib.Path,
) -> None:
    """Tmux fragments ``%output``; the decoder must reassemble the encoder's bytes."""
    raw = encode_osc("awaiting_input", "claude", tmp_path / "tty")
    readings = decode_osc(raw, chunk=chunk)
    assert len(readings) == 1
    assert readings[0].state is AgentState.AWAITING_INPUT
    assert readings[0].name == "claude"


def test_osc_round_trips_at_every_split_point(tmp_path: pathlib.Path) -> None:
    r"""Splitting the encoder's bytes anywhere still yields exactly one reading.

    A property check over every possible fragment boundary, including inside the
    introducer, inside a multi-byte UTF-8 name, and inside the two-byte ``ESC \``
    terminator -- the three places a hand-picked chunk size would miss.
    """
    raw = encode_osc("done", "klüd-\U0001f916", tmp_path / "tty")
    for split in range(len(raw) + 1):
        osc = OscSignal()
        readings = osc.feed(PANE_ID, raw[:split])
        readings.extend(osc.feed(PANE_ID, raw[split:]))
        assert len(readings) == 1, f"lost the reading when split at byte {split}"
        assert readings[0].state is AgentState.DONE
        assert readings[0].name == "klüd-\U0001f916"


def test_back_to_back_emissions_all_decode(tmp_path: pathlib.Path) -> None:
    """Several emissions coalesced into one ``%output`` chunk all decode, in order."""
    raw = b"".join(
        encode_osc(state.value, "claude", tmp_path / "tty")
        for state in (AgentState.RUNNING, AgentState.AWAITING_INPUT, AgentState.DONE)
    )
    readings = decode_osc(raw)
    assert [r.state for r in readings] == [
        AgentState.RUNNING,
        AgentState.AWAITING_INPUT,
        AgentState.DONE,
    ]
    assert {r.name for r in readings} == {"claude"}


def test_emissions_interleaved_with_pane_noise_decode(tmp_path: pathlib.Path) -> None:
    """Ordinary pane output around the escape does not hide it from the decoder."""
    raw = encode_osc("running", "claude", tmp_path / "tty")
    noisy = b"$ npm test\r\n\033[1;32mPASS\033[0m\r\n" + raw + b"\r\n$ \033[K"
    readings = decode_osc(noisy)
    assert len(readings) == 1
    assert readings[0].state is AgentState.RUNNING
    assert readings[0].name == "claude"


# ----------------------------------------------------------------------------
# The two channels agree with each other, and the option-key literals agree
# across all four modules that repeat them.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("state", list(AgentState), ids=lambda s: s.value)
def test_both_channels_decode_identically(
    state: AgentState,
    tmp_path: pathlib.Path,
) -> None:
    """One ``emit`` call, two transports, one answer.

    ``emit`` silently picks the local (option) or the remote (OSC) channel from
    ``$TMUX``.  A caller cannot control which one runs, so the two must decode to
    the same ``(state, name)`` -- otherwise an agent means different things over
    SSH than it does at home.
    """
    name = "claude code"
    osc = decode_osc(encode_osc(state.value, name, tmp_path / "tty"))[0]
    option_state, option_name = decode_options(encode_options(state.value, name))
    assert (osc.state, osc.name) == (option_state, option_name)


def test_encoder_option_keys_are_the_keys_every_reader_looks_for() -> None:
    """The option keys the encoder writes are the ones all three readers read.

    Four modules repeat these literals -- ``emit`` writes them, ``signals``
    subscribes to them, ``tree`` requests them in its pane format, and ``monitor``
    reads them off the snapshot.  Renaming ``@agent_state`` in one place and not
    the others produces a monitor that observes nothing, silently.  The keys here
    come from the encoder's own argv, so this test cannot drift with it.
    """
    options = encode_options("running", "claude")
    state_key, name_key = "@agent_state", "@agent_name"
    assert set(options) == {state_key, name_key}, (
        f"encoder changed its option keys: {sorted(options)}"
    )

    # signals.py: the subscription spec must ask tmux for the key emit writes.
    assert f"#{{{state_key}}}" in signals_mod.SUBSCRIPTION

    # tree.py: the reconcile pane format must request both keys.
    assert state_key in tree_mod.PANE_FORMAT
    assert name_key in tree_mod.PANE_FORMAT

    # monitor.py: the reconcile reader must find an agent using only these keys.
    assert decode_options(options) == (AgentState.RUNNING, "claude")

    # ...and must find nothing when the keys are absent.
    assert decode_options({}) == (AgentState.UNKNOWN, None)


def test_osc_magic_number_agrees(tmp_path: pathlib.Path) -> None:
    """Encoder and decoder agree on OSC 3008 -- the number, and only that number."""
    raw = encode_osc("running", None, tmp_path / "tty")
    assert raw.startswith(b"\033]3008;"), f"encoder changed its introducer: {raw!r}"
    assert len(decode_osc(raw)) == 1

    # A neighbouring OSC number must not be mistaken for ours.
    assert decode_osc(raw.replace(b"]3008;", b"]3009;")) == []


# ----------------------------------------------------------------------------
# HOSTILE NAMES -- every delimiter of the grammar, carried inside a value.
# ----------------------------------------------------------------------------

HOSTILE_NAMES = (
    pytest.param("claude;code", id="semicolon"),
    pytest.param("claude\007code", id="bel"),
    pytest.param("claude\033code", id="esc"),
    pytest.param("claude=code", id="equals"),
    pytest.param("claude%3Bcode", id="literal_percent_escape"),
)


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_osc_round_trips_hostile_names(name: str, tmp_path: pathlib.Path) -> None:
    """A name carrying a wire delimiter round-trips instead of corrupting the read.

    Every delimiter of the grammar (``;``, ``=``, ``ESC``, ``BEL``) used to be a
    hole: ``;`` truncated the name, ``BEL`` cut the escape short, and ``ESC``
    dropped the reading entirely because the payload class excludes it. The
    values are percent-encoded on the wire now, so none of them can be
    structural.
    """
    readings = decode_osc(encode_osc("running", name, tmp_path / "tty"))
    assert len(readings) == 1, "the encoder produced bytes the decoder cannot read"
    assert readings[0].state is AgentState.RUNNING
    assert readings[0].name == name


def test_name_cannot_forge_state(tmp_path: pathlib.Path) -> None:
    """The name field must not be able to overwrite the state field.

    The payload is a ``;``-delimited, ``=``-paired body and the decoder takes the
    last value for a repeated key, so an unescaped name could inject a second
    ``state=`` pair: any agent able to influence its own name could forge its own
    state. Percent-encoding the value closes it.
    """
    raw = encode_osc("running", "x;state=idle", tmp_path / "tty")
    readings = decode_osc(raw)
    assert len(readings) == 1
    assert readings[0].state is AgentState.RUNNING, (
        "the name field overwrote the state field"
    )
    assert readings[0].name == "x;state=idle"


def test_osc_survives_the_real_tmux_output_transport(
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """emit()'s bytes, printed in a real pane, reach the monitor as a real state.

    The end-to-end path no unit test covers: encoder -> pane pty -> tmux ->
    control-mode ``%output`` -> ``AgentMonitor.ingest`` -> decoder.  The escape
    bytes are written by the real :func:`emit` into a file which the pane then
    ``cat``s, so tmux transports exactly what an agent hook would have emitted
    over SSH.
    """
    from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine

    payload = tmp_path / "osc.bin"
    encode_osc("running", "claude", payload)

    async def main() -> str:
        engine = AsyncControlModeEngine.for_server(session.server)
        monitor = AgentMonitor(engine)
        await monitor.start()
        active_pane = session.active_window.active_pane
        assert active_pane is not None
        pane_id = active_pane.pane_id
        assert pane_id is not None

        # The agent hook's effect, for real: the escape bytes hit the pane pty.
        session.cmd("send-keys", "-t", pane_id, f"cat {payload}", "Enter")

        seen = "missing"
        for _ in range(40):
            await asyncio.sleep(0.1)
            match = {a.pane_id: a for a in monitor.agents}.get(pane_id)
            if match is not None:
                seen = match.state.value
                if seen == "running":
                    break
        await monitor.stop()
        await engine.aclose()
        return seen

    assert asyncio.run(main()) == "running"
