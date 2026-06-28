"""The two channels an agent uses to report state.

``OptionSignal`` reads tmux ``@agent_state`` user-options surfaced as
``%subscription-changed`` (local; ~1 s debounced, re-queryable). ``OscSignal``
reads a bare ``OSC 3008`` escape out of ``%output`` (remote/SSH; instant), with a
per-pane accumulator because tmux delivers ``%output`` byte-fragmented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from libtmux.experimental.agents.state import AgentState

#: The ``refresh-client -B`` spec the monitor installs for the local channel.
SUBSCRIPTION = "agentstate:%*:#{@agent_state}"

_SUB_RE = re.compile(
    r"^%subscription-changed\s+agentstate\s+\S+\s+\S+\s+\S+\s+(?P<pane>%\d+)\s+:\s+(?P<value>\S+)"
)
_OSC_RE = re.compile(rb"\033\]3008;([^\033\007]*)(?:\033\\|\007)")


@dataclass(frozen=True)
class Reading:
    """One observed agent-state reading from a signal channel.

    Parameters
    ----------
    pane_id : str
        The pane identifier (e.g., ``%1``).
    state : AgentState
        The agent state observed.
    name : str | None
        The agent name, if present in the signal.
    source : str
        The signal source: ``"option"`` or ``"osc"``.

    Examples
    --------
    >>> r = Reading(pane_id="%1", state=AgentState.RUNNING, name=None,
    ...             source="option")
    >>> r.pane_id, r.state.value, r.source
    ('%1', 'running', 'option')
    """

    pane_id: str
    state: AgentState
    name: str | None
    source: str


def _parse_payload(payload: str) -> tuple[AgentState, str | None]:
    """Parse an OSC/option payload like ``state=running`` (``name=`` optional).

    Parameters
    ----------
    payload : str
        The payload string, e.g., ``"state=running;name=claude"``.

    Returns
    -------
    tuple[AgentState, str | None]
        The agent state and optional name.

    Examples
    --------
    >>> _parse_payload("state=running")
    (<AgentState.RUNNING: 'running'>, None)
    >>> _parse_payload("state=idle;name=test")
    (<AgentState.IDLE: 'idle'>, 'test')
    """
    state = AgentState.UNKNOWN
    name: str | None = None
    for part in payload.split(";"):
        key, _, value = part.partition("=")
        if key == "state":
            state = AgentState.from_signal(value)
        elif key == "name":
            name = value or None
    return state, name


class OptionSignal:
    """Parse the local ``@agent_state`` subscription channel.

    Matches ``%subscription-changed`` notifications for the ``agentstate``
    subscription and extracts the pane and state. Non-matching lines are
    silently dropped (``parse`` returns ``None``).
    """

    @staticmethod
    def parse(notification_raw: str) -> Reading | None:
        """Parse a ``%subscription-changed`` line; ``None`` if it isn't one.

        Parameters
        ----------
        notification_raw : str
            A raw tmux ``%subscription-changed`` notification line.

        Returns
        -------
        Reading | None
            A Reading if the line matches a subscription-changed pattern,
            else ``None``.

        Examples
        --------
        >>> r = OptionSignal.parse(
        ...     "%subscription-changed agentstate $0 @0 1 %3 : running")
        >>> r.pane_id, r.state.value
        ('%3', 'running')
        >>> OptionSignal.parse("%output %1 hi") is None
        True
        """
        match = _SUB_RE.match(notification_raw)
        if match is None:
            return None
        state = AgentState.from_signal(match.group("value"))
        return Reading(match.group("pane"), state, None, "option")


class OscSignal:
    r"""Reassemble ``OSC 3008`` agent-state escapes out of fragmented ``%output``.

    The class maintains per-pane byte buffers to handle tmux's byte-fragmented
    ``%output`` delivery. Buffers are bounded to 4KB to prevent unbounded growth
    from never-terminated escapes.

    Examples
    --------
    >>> osc = OscSignal()
    >>> osc.feed("%1", b"\033]3008;state=idle\033\\")[0].state.value
    'idle'
    """

    def __init__(self) -> None:
        """Initialize the OSC signal parser with empty per-pane buffers."""
        self._buffers: dict[str, bytes] = {}

    def feed(self, pane_id: str, data: bytes) -> list[Reading]:
        r"""Append *data* for *pane_id*; return a Reading per complete escape.

        This method accumulates bytes for a pane and scans for complete
        ``OSC 3008`` escape sequences. Partial sequences are buffered for
        the next call.

        Parameters
        ----------
        pane_id : str
            The pane identifier.
        data : bytes
            Bytes to append to the pane's buffer.

        Returns
        -------
        list[Reading]
            A list of Reading objects, one per complete escape found.

        Examples
        --------
        ST-terminated (``ESC \``) path:

        >>> osc = OscSignal()
        >>> readings = osc.feed("%1", b"\033]3008;state=awaiting_input\033\\")
        >>> len(readings)
        1
        >>> readings[0].state.value
        'awaiting_input'

        BEL-terminated (``\\007``) path:

        >>> osc2 = OscSignal()
        >>> readings2 = osc2.feed("%2", b"\033]3008;state=idle\007")
        >>> readings2[0].state.value
        'idle'
        """
        buffer = self._buffers.get(pane_id, b"") + data
        readings: list[Reading] = []
        while True:
            match = _OSC_RE.search(buffer)
            if match is None:
                break
            payload = match.group(1).decode(errors="replace")
            state, name = _parse_payload(payload)
            readings.append(Reading(pane_id, state, name, "osc"))
            buffer = buffer[match.end() :]
        # keep only a bounded tail so a never-terminated OSC can't grow unbounded
        self._buffers[pane_id] = buffer[-4096:]
        return readings
