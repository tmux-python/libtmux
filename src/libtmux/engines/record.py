"""Record tmux traffic once, then replay it with no tmux server.

Simulating tmux is not practical: libtmux's listing queries ask for 136 format
fields per row, version-gated, so a hand-written fake drifts out of date the
moment tmux adds a field -- and a fake that answers everything with "success"
is worse than none, because ``has-session`` then reports that every session
exists while ``list-sessions`` reports none.

Recording sidesteps that. :class:`RecordingEngine` wraps a real engine and keeps
what tmux actually said; :class:`ReplayEngine` serves those answers back. The
rows are real, so :mod:`libtmux.neo` parses them exactly as it would live, and
they stay correct for the tmux version they were taken on.

A replay engine fails closed: a command that was never recorded raises
:exc:`~libtmux.exc.UnscriptedCommand` rather than inventing an answer.
"""

from __future__ import annotations

import typing as t

from libtmux import exc
from libtmux.engines.base import CommandResult, TmuxEngine

if t.TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from libtmux.engines.base import CommandRequest

#: A recorded exchange: the request argv, mapped to what tmux answered.
Tape = t.Mapping[tuple[str, ...], CommandResult]


class RecordingEngine(TmuxEngine):
    """Run commands through another engine, keeping what tmux answered.

    Wrap the engine a live :class:`~libtmux.Server` would use, exercise your
    code, then keep :attr:`tape` for :class:`ReplayEngine`. Doubles as a spy:
    :attr:`requests` is every argv in dispatch order, including repeats.

    Parameters
    ----------
    inner : TmuxEngine
        The engine that actually talks to tmux.

    Attributes
    ----------
    requests : list[tuple[str, ...]]
        Every request argv, in dispatch order.

    Examples
    --------
    >>> from libtmux.engines import RecordingEngine, SubprocessEngine
    >>> from libtmux.server import Server
    >>> recorder = RecordingEngine(SubprocessEngine.for_server(server))
    >>> live = Server(socket_name=server.socket_name, engine=recorder)
    >>> _ = live.cmd("display-message", "-p", "recorded")
    >>> recorder.requests
    [('display-message', '-p', 'recorded')]
    >>> recorder.tape[("display-message", "-p", "recorded")].stdout
    ('recorded',)
    """

    def __init__(self, inner: TmuxEngine) -> None:
        self._inner = inner
        self._tape: dict[tuple[str, ...], CommandResult] = {}
        self.requests: list[tuple[str, ...]] = []

    @property
    def tape(self) -> Tape:
        """Return the recorded exchanges, keyed by request argv.

        A repeated command keeps its most recent answer, so the tape describes
        the end state rather than every intermediate one.
        """
        return dict(self._tape)

    def run(self, request: CommandRequest) -> CommandResult:
        """Dispatch through the inner engine and record the answer."""
        result = self._inner.run(request)
        self.requests.append(request.args)
        # Drop the Popen: a tape outlives the process it was recorded from.
        self._tape[request.args] = CommandResult(
            cmd=result.cmd,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )
        return result

    def to_dict(self) -> list[dict[str, t.Any]]:
        """Return the tape as JSON-serializable data.

        Use it to commit a tape next to the tests that replay it, so a suite
        that needs a real tmux to *record* needs none to *run*.

        Returns
        -------
        list[dict]
            One entry per recorded command.

        Examples
        --------
        >>> from libtmux.engines import (
        ...     CommandRequest,
        ...     RecordingEngine,
        ...     SubprocessEngine,
        ... )
        >>> recorder = RecordingEngine(SubprocessEngine.for_server(server))
        >>> _ = recorder.run(CommandRequest.from_args("display-message", "-p", "x"))
        >>> entry = recorder.to_dict()[0]
        >>> entry["args"], entry["stdout"], entry["returncode"]
        (['display-message', '-p', 'x'], ['x'], 0)
        """
        return [
            {
                "args": list(args),
                "cmd": list(result.cmd),
                "stdout": list(result.stdout),
                "stderr": list(result.stderr),
                "returncode": result.returncode,
            }
            for args, result in self._tape.items()
        ]


class ReplayEngine(TmuxEngine):
    """Answer commands from a recorded tape, touching no tmux server.

    Fails closed. A command absent from the tape raises
    :exc:`~libtmux.exc.UnscriptedCommand`, because the alternative -- inventing
    a plausible answer -- is how a fake reports that every session exists and no
    sessions exist at the same time.

    Parameters
    ----------
    tape : Mapping[tuple[str, ...], CommandResult]
        Recorded exchanges, as produced by :attr:`RecordingEngine.tape`.

    Attributes
    ----------
    requests : list[tuple[str, ...]]
        Every request argv served, in order.

    Examples
    --------
    >>> from libtmux.engines import CommandResult, ReplayEngine
    >>> from libtmux.server import Server
    >>> tape = {("display-message", "-p", "hi"): CommandResult(
    ...     cmd=("tmux", "display-message", "-p", "hi"), stdout=("hi",)
    ... )}
    >>> Server(engine=ReplayEngine(tape)).cmd("display-message", "-p", "hi").stdout
    ['hi']

    An unrecorded command says so, instead of guessing:

    >>> Server(engine=ReplayEngine(tape)).cmd("kill-server")
    Traceback (most recent call last):
    ...
    libtmux.exc.UnscriptedCommand: no recorded result for 'kill-server'
    """

    def __init__(self, tape: Tape) -> None:
        self._tape = dict(tape)
        self.requests: list[tuple[str, ...]] = []

    @classmethod
    def from_dict(cls, entries: Sequence[Mapping[str, t.Any]]) -> ReplayEngine:
        """Rebuild an engine from :meth:`RecordingEngine.to_dict` output.

        Parameters
        ----------
        entries : Sequence[Mapping]
            Serialized tape entries.

        Returns
        -------
        ReplayEngine

        Examples
        --------
        >>> from libtmux.engines import ReplayEngine
        >>> from libtmux.server import Server
        >>> engine = ReplayEngine.from_dict([
        ...     {
        ...         "args": ["display-message", "-p", "hi"],
        ...         "cmd": ["tmux", "display-message", "-p", "hi"],
        ...         "stdout": ["hi"],
        ...         "stderr": [],
        ...         "returncode": 0,
        ...     }
        ... ])
        >>> Server(engine=engine).cmd("display-message", "-p", "hi").stdout
        ['hi']
        """
        return cls(
            {
                tuple(entry["args"]): CommandResult(
                    cmd=tuple(entry.get("cmd", ())),
                    stdout=tuple(entry.get("stdout", ())),
                    stderr=tuple(entry.get("stderr", ())),
                    returncode=int(entry.get("returncode", 0)),
                )
                for entry in entries
            },
        )

    def run(self, request: CommandRequest) -> CommandResult:
        """Return the recorded answer for *request*.

        Raises
        ------
        :exc:`~libtmux.exc.UnscriptedCommand`
            The tape holds no answer for this argv.
        """
        try:
            result = self._tape[request.args]
        except KeyError:
            raise exc.UnscriptedCommand(request.args) from None
        self.requests.append(request.args)
        return result

    def __contains__(self, args: object) -> bool:
        """Whether the tape can answer *args*."""
        return args in self._tape

    def __len__(self) -> int:
        """Return how many distinct commands the tape answers."""
        return len(self._tape)

    def __iter__(self) -> Iterator[tuple[str, ...]]:
        """Iterate the argvs the tape can answer."""
        return iter(self._tape)
