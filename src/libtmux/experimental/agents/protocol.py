r"""The agent-state wire protocol: one grammar, both directions.

An agent reports its state over one of two channels, and this module owns the
*only* definition of each:

**Option channel** (local; tmux reachable). The agent writes the per-pane user
options ``@agent_state`` / ``@agent_name``; tmux replays them to a subscribed
control client as ``%subscription-changed`` and to ``list-panes`` as format
fields. :func:`encode_option` writes them, :func:`decode_subscription` and
:func:`decode_option` read them back, and :data:`SUBSCRIPTION` -- the
``refresh-client -B`` spec that turns the write into a notification -- is
derived from the same option name.

**OSC channel** (remote; over SSH). The agent prints a bare ``OSC 3008`` escape
to its pty, which travels verbatim into tmux ``%output``. :func:`encode_osc`
writes it and :func:`decode_osc` reads it back.

Both channels carry the same payload grammar (:class:`Payload`), and every
literal in it -- the ``3008``, the option names, the ``state=``/``name=`` keys,
the ``ESC \`` / ``BEL`` terminators -- appears exactly once, here. Encoder and
decoder cannot drift apart because there is nothing to drift *from*: they are
two functions over one set of constants.
"""

from __future__ import annotations

import re
import typing as t
from dataclasses import dataclass

if t.TYPE_CHECKING:
    from collections.abc import Mapping

#: The OSC command number carrying an agent-state payload.
OSC_CODE = 3008

#: Per-pane tmux user option carrying the agent's state (option channel).
OPTION_STATE = "@agent_state"

#: Per-pane tmux user option carrying the agent's name (option channel).
OPTION_NAME = "@agent_name"

#: The tmux user options an agent-aware ``list-panes`` must request.
PANE_OPTIONS: tuple[str, ...] = (OPTION_STATE, OPTION_NAME)

#: The name of the ``refresh-client -B`` subscription the monitor installs.
SUBSCRIPTION_NAME = "agentstate"

#: The ``refresh-client -B`` spec the monitor installs for the option channel.
SUBSCRIPTION = f"{SUBSCRIPTION_NAME}:%*:#{{{OPTION_STATE}}}"

#: Payload key for the agent state, shared by both channels.
KEY_STATE = "state"

#: Payload key for the agent name, shared by both channels.
KEY_NAME = "name"

_PAIR_SEP = ";"
_KV_SEP = "="

#: OSC introducer: ``ESC ] 3008 ;``. What :func:`encode_osc` writes and
#: :func:`decode_osc` scans for.
_OSC_INTRO = f"\033]{OSC_CODE}{_PAIR_SEP}"
#: String Terminator. The terminator we emit.
_ST = "\033\\"
#: Bell. A terminator we accept but never emit (xterm's legacy OSC ending).
_BEL = "\007"

#: The escape's grammar, built from the very constants :func:`encode_osc` uses:
#: introducer, a body free of either terminator's lead byte, then a terminator.
_OSC_RE = re.compile(
    re.escape(_OSC_INTRO.encode())
    + rb"([^\033\007]*)"
    + rb"(?:"
    + re.escape(_ST.encode())
    + rb"|"
    + re.escape(_BEL.encode())
    + rb")"
)

_SUB_RE = re.compile(
    r"^%subscription-changed\s+"
    + re.escape(SUBSCRIPTION_NAME)
    + r"\s+\S+\s+\S+\s+\S+\s+(?P<pane>%\d+)\s+:\s+(?P<value>\S+)"
)


@dataclass(frozen=True)
class Payload:
    """What an agent says about itself: a raw state string and optional name.

    This is the wire vocabulary, not the semantic one -- ``state`` is whatever
    the agent wrote. Mapping it to an
    :class:`~libtmux.experimental.agents.state.AgentState` is the reader's job
    (:meth:`~libtmux.experimental.agents.state.AgentState.from_signal`), which
    keeps this module a pure grammar and keeps the emitter free of the enum.

    Parameters
    ----------
    state : str
        Raw agent state string (e.g. ``"running"``).
    name : str or None
        Optional agent name.

    Examples
    --------
    >>> Payload("running")
    Payload(state='running', name=None)
    >>> Payload("idle", "claude").name
    'claude'
    """

    state: str
    name: str | None = None


def encode_payload(payload: Payload) -> str:
    """Render *payload* as the ``key=value;key=value`` body both channels carry.

    Parameters
    ----------
    payload : Payload
        The payload to render.

    Returns
    -------
    str
        The payload body, e.g. ``"state=running;name=claude"``.

    Examples
    --------
    >>> encode_payload(Payload("running"))
    'state=running'
    >>> encode_payload(Payload("idle", "claude"))
    'state=idle;name=claude'
    """
    body = f"{KEY_STATE}{_KV_SEP}{payload.state}"
    if payload.name:
        body += f"{_PAIR_SEP}{KEY_NAME}{_KV_SEP}{payload.name}"
    return body


def decode_payload(body: str) -> Payload:
    """Parse a ``key=value;key=value`` body back into a :class:`Payload`.

    Unknown keys are ignored and a missing ``state=`` yields an empty state, so
    a malformed signal degrades rather than raising.

    Parameters
    ----------
    body : str
        The payload body, e.g. ``"state=running;name=claude"``.

    Returns
    -------
    Payload
        The decoded payload.

    Examples
    --------
    >>> decode_payload("state=running")
    Payload(state='running', name=None)
    >>> decode_payload("state=idle;name=claude")
    Payload(state='idle', name='claude')
    >>> decode_payload("garbage")
    Payload(state='', name=None)
    """
    state = ""
    name: str | None = None
    for part in body.split(_PAIR_SEP):
        key, _, value = part.partition(_KV_SEP)
        if key == KEY_STATE:
            state = value
        elif key == KEY_NAME:
            name = value or None
    return Payload(state, name)


def encode_osc(payload: Payload) -> bytes:
    r"""Render *payload* as an ``OSC 3008`` escape (ST-terminated).

    Printed to a pane's pty this survives SSH and arrives verbatim in tmux
    ``%output``, where :func:`decode_osc` reads it back.

    Parameters
    ----------
    payload : Payload
        The payload to encode.

    Returns
    -------
    bytes
        The complete escape sequence, ready to write to a tty.

    Examples
    --------
    >>> encode_osc(Payload("running"))
    b'\x1b]3008;state=running\x1b\\'
    >>> decode_osc(encode_osc(Payload("idle", "claude")))[0]
    [Payload(state='idle', name='claude')]
    """
    return f"{_OSC_INTRO}{encode_payload(payload)}{_ST}".encode()


def decode_osc(buffer: bytes) -> tuple[list[Payload], bytes]:
    r"""Drain every *complete* ``OSC 3008`` escape out of *buffer*.

    Fragment-aware by construction: tmux delivers ``%output`` byte-fragmented,
    so this returns the unconsumed tail alongside the payloads it found. The
    caller re-feeds that tail with the next chunk. Buffering *policy* (per-pane
    dicts, size caps) stays with the caller; the *grammar* stays here.

    Both terminators tmux may deliver are accepted -- ``ESC \`` (ST) and
    ``BEL`` -- even though :func:`encode_osc` only ever writes ST.

    Parameters
    ----------
    buffer : bytes
        Accumulated bytes, possibly containing partial escapes at either end.

    Returns
    -------
    tuple[list[Payload], bytes]
        Every complete payload found, in order, plus the unconsumed tail.

    Examples
    --------
    A complete escape decodes and leaves nothing behind:

    >>> decode_osc(b"\x1b]3008;state=idle\x1b\\")
    ([Payload(state='idle', name=None)], b'')

    A BEL-terminated escape decodes too:

    >>> decode_osc(b"\x1b]3008;state=done\x07")
    ([Payload(state='done', name=None)], b'')

    A truncated escape yields nothing and is handed back for the next chunk:

    >>> payloads, tail = decode_osc(b"\x1b]3008;state=run")
    >>> payloads, tail
    ([], b'\x1b]3008;state=run')
    >>> decode_osc(tail + b"ning\x1b\\")[0]
    [Payload(state='running', name=None)]
    """
    payloads: list[Payload] = []
    while True:
        match = _OSC_RE.search(buffer)
        if match is None:
            break
        payloads.append(decode_payload(match.group(1).decode(errors="replace")))
        buffer = buffer[match.end() :]
    return payloads, buffer


def encode_option(pane_id: str, payload: Payload) -> list[list[str]]:
    """Render *payload* as the tmux commands that publish it on *pane_id*.

    One ``set-option`` per populated field. Written this way the option channel
    is durable (``list-panes`` can re-read it -- see :func:`decode_option`) and
    live (a client subscribed to :data:`SUBSCRIPTION` is notified -- see
    :func:`decode_subscription`).

    Parameters
    ----------
    pane_id : str
        The target pane (e.g. ``"%1"``, or ``$TMUX_PANE``).
    payload : Payload
        The payload to publish.

    Returns
    -------
    list[list[str]]
        Zero or more ``tmux`` argv lists, to run in order.

    Examples
    --------
    >>> encode_option("%1", Payload("running"))
    [['tmux', 'set-option', '-p', '-t', '%1', '@agent_state', 'running']]

    >>> for argv in encode_option("%1", Payload("idle", "claude")):
    ...     print(argv[5:])
    ['@agent_state', 'idle']
    ['@agent_name', 'claude']
    """
    argvs = [["tmux", "set-option", "-p", "-t", pane_id, OPTION_STATE, payload.state]]
    if payload.name:
        argvs.append(
            ["tmux", "set-option", "-p", "-t", pane_id, OPTION_NAME, payload.name]
        )
    return argvs


def decode_option(fields: Mapping[str, str]) -> Payload | None:
    """Read a payload back out of ``list-panes`` format fields.

    The durable half of the option channel: what :func:`encode_option` wrote is
    still readable on reconnect, so a monitor that missed the live notification
    can reconcile from a pane listing.

    Parameters
    ----------
    fields : Mapping[str, str]
        A pane's format fields, as requested via :data:`PANE_OPTIONS`.

    Returns
    -------
    Payload or None
        The payload, or ``None`` when the pane carries no agent state.

    Examples
    --------
    >>> decode_option({"@agent_state": "running", "@agent_name": "claude"})
    Payload(state='running', name='claude')
    >>> decode_option({"@agent_state": "", "@agent_name": ""}) is None
    True
    """
    state = fields.get(OPTION_STATE, "").strip()
    if not state:
        return None
    return Payload(state, fields.get(OPTION_NAME) or None)


def decode_subscription(line: str) -> tuple[str, Payload] | None:
    """Read a payload out of a ``%subscription-changed`` notification line.

    The live half of the option channel. Non-matching lines yield ``None``, so
    this doubles as the classifier for the notification stream.

    Note the asymmetry with :func:`encode_option`: tmux's subscription format
    carries one option per notification, so only :data:`OPTION_STATE` arrives
    here. The name is filled in from :func:`decode_option` on reconcile.

    Parameters
    ----------
    line : str
        A raw tmux control-mode notification line.

    Returns
    -------
    tuple[str, Payload] or None
        The pane id and payload, or ``None`` when *line* is not an agent-state
        subscription notification.

    Examples
    --------
    >>> decode_subscription("%subscription-changed agentstate $0 @0 1 %3 : running")
    ('%3', Payload(state='running', name=None))
    >>> decode_subscription("%output %1 hi") is None
    True
    """
    match = _SUB_RE.match(line)
    if match is None:
        return None
    return match.group("pane"), Payload(match.group("value"))
