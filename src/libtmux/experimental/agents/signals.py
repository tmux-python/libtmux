"""The two channels an agent uses to report state.

This is the *read* end of the protocol; it chooses a channel and hands the
bytes to the codec. ``OptionSignal`` reads tmux ``@agent_state`` user-options
surfaced as ``%subscription-changed`` (local; ~1 s debounced, re-queryable).
``OscSignal`` reads a bare ``OSC 3008`` escape out of ``%output`` (remote/SSH;
instant), with a per-pane accumulator because tmux delivers ``%output``
byte-fragmented.

Neither escape sequence nor option name is spelled here. The grammar lives in
:mod:`libtmux.experimental.agents.protocol` alongside the encoders
(:mod:`libtmux.experimental.agents.hooks.emit`) that produce it; what remains
here is *policy*: which channel a line belongs to, the per-pane buffering the
fragmented OSC stream needs, and the mapping from the wire's raw state string
to the :class:`~libtmux.experimental.agents.state.AgentState` vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.agents.protocol import (
    SUBSCRIPTION,
    decode_osc,
    decode_subscription,
)
from libtmux.experimental.agents.state import AgentState

__all__ = [
    "SUBSCRIPTION",
    "OptionSignal",
    "OscSignal",
    "Reading",
]

#: Cap the per-pane accumulator so a never-terminated OSC can't grow unbounded.
_MAX_BUFFER = 4096


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
        decoded = decode_subscription(notification_raw)
        if decoded is None:
            return None
        pane_id, payload = decoded
        return Reading(
            pane_id,
            AgentState.from_signal(payload.state),
            payload.name,
            "option",
        )


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
        payloads, tail = decode_osc(self._buffers.get(pane_id, b"") + data)
        self._buffers[pane_id] = tail[-_MAX_BUFFER:]
        return [
            Reading(
                pane_id,
                AgentState.from_signal(payload.state),
                payload.name,
                "osc",
            )
            for payload in payloads
        ]
