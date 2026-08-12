"""Record tmux traffic once, then replay it with no tmux server.

Simulating tmux is not practical. A listing query asks tmux for its whole
format-field set on every row, and that set is version-gated -- it grows as tmux
gains fields -- so a hand-written fake is stale the release after it is written.
A fake that papers over the gap by answering unknown commands optimistically is
worse than none: ``has-session`` then reports that every session exists while
``list-sessions`` reports that none do.

Recording sidesteps that. :class:`RecordingEngine` wraps a real engine and keeps
what tmux actually said; :class:`ReplayEngine` serves those answers back. The
rows are real, so :mod:`libtmux.neo` parses them exactly as it would live, and
they stay correct for the tmux version they were taken on.

A replay engine fails closed: a command that was never recorded raises
:exc:`~libtmux.exc.UnscriptedCommand` rather than inventing an answer.
"""

from __future__ import annotations

import typing as t
from collections.abc import Mapping

from libtmux import exc
from libtmux.engines.base import (
    CommandResult,
    SupportsTmuxVersion,
    TmuxEngine,
)

if t.TYPE_CHECKING:
    from collections.abc import Iterator

    from libtmux.engines.base import CommandRequest


class Exchange(t.NamedTuple):
    """One recorded command and the answer tmux gave it.

    Attributes
    ----------
    args : tuple[str, ...]
        The request argv, without the binary or connection flags.
    result : CommandResult
        What tmux answered.
    """

    args: tuple[str, ...]
    result: CommandResult


#: A recorded conversation. A sequence preserves order, which matters when the
#: same command is asked twice and answered differently. A mapping is accepted
#: too, for a hand-written tape where each command has one fixed answer.
Tape: t.TypeAlias = "t.Sequence[Exchange] | t.Mapping[tuple[str, ...], CommandResult]"


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
    >>> recorder.tape[0].args
    ('display-message', '-p', 'recorded')
    >>> recorder.tape[0].result.stdout
    ('recorded',)
    """

    def __init__(self, inner: TmuxEngine) -> None:
        self._inner = inner
        self._exchanges: list[Exchange] = []
        self.requests: list[tuple[str, ...]] = []

    def tmux_version(self) -> str | None:
        """Report the version of the tmux being recorded, if the inner engine knows.

        Recorded alongside the tape so a :class:`ReplayEngine` can answer with
        it later. The ``-F`` template libtmux sends is version-gated, so a tape
        replayed against a different version would miss every listing query.
        """
        inner = self._inner
        if isinstance(inner, SupportsTmuxVersion):
            return inner.tmux_version()
        return None

    @property
    def tape(self) -> tuple[Exchange, ...]:
        """Return every recorded exchange, in the order it happened.

        Order is kept rather than collapsed per command, because the same
        command asked twice is often answered differently -- ``list-sessions``
        before and after a session is created -- and a tape that remembered only
        the last answer would replay the end state for both.
        """
        return tuple(self._exchanges)

    def run(self, request: CommandRequest) -> CommandResult:
        """Dispatch through the inner engine and record the answer."""
        result = self._inner.run(request)
        self.requests.append(request.args)
        # Drop the Popen: a tape outlives the process it was recorded from.
        self._exchanges.append(
            Exchange(
                args=request.args,
                result=CommandResult(
                    cmd=result.cmd,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    returncode=result.returncode,
                ),
            ),
        )
        return result

    def to_dict(self) -> dict[str, t.Any]:
        """Return the tape as JSON-serializable data.

        Use it to commit a tape next to the tests that replay it, so a suite
        that needs a real tmux to *record* needs none to *run*.

        The tmux version rides along with the commands, because the ``-F``
        template libtmux sends is version-gated: replaying a tape against a
        different tmux would miss every listing query, and a bare
        "no recorded result" would not explain why.

        Returns
        -------
        dict
            ``{"tmux_version": str | None, "commands": [...]}``.

        Examples
        --------
        >>> from libtmux.engines import (
        ...     CommandRequest,
        ...     RecordingEngine,
        ...     SubprocessEngine,
        ... )
        >>> recorder = RecordingEngine(SubprocessEngine.for_server(server))
        >>> _ = recorder.run(CommandRequest.from_args("display-message", "-p", "x"))
        >>> tape = recorder.to_dict()
        >>> sorted(tape)
        ['commands', 'tmux_version']
        >>> entry = tape["commands"][0]
        >>> entry["args"], entry["stdout"], entry["returncode"]
        (['display-message', '-p', 'x'], ['x'], 0)
        """
        return {
            "tmux_version": self.tmux_version(),
            "commands": [
                {
                    "args": list(args),
                    "cmd": list(result.cmd),
                    "stdout": list(result.stdout),
                    "stderr": list(result.stderr),
                    "returncode": result.returncode,
                }
                for args, result in self._exchanges
            ],
        }


class ReplayEngine(TmuxEngine):
    """Answer commands from a recorded tape, touching no tmux server.

    Fails closed. A command absent from the tape raises
    :exc:`~libtmux.exc.UnscriptedCommand`, because the alternative -- inventing
    a plausible answer -- is how a fake reports that every session exists and no
    sessions exist at the same time.

    Parameters
    ----------
    tape : Sequence[Exchange] or Mapping[tuple[str, ...], CommandResult]
        Recorded exchanges, as produced by :attr:`RecordingEngine.tape`. A
        sequence replays in order; a mapping gives each command one fixed
        answer, which is convenient for a hand-written tape.

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

    def __init__(self, tape: Tape, *, tmux_version: str | None = None) -> None:
        exchanges = (
            [Exchange(args, result) for args, result in tape.items()]
            if isinstance(tape, Mapping)
            else list(tape)
        )
        self._answers: dict[tuple[str, ...], list[CommandResult]] = {}
        for args, result in exchanges:
            self._answers.setdefault(args, []).append(result)
        self._served: dict[tuple[str, ...], int] = {}
        self._tmux_version = tmux_version
        self.requests: list[tuple[str, ...]] = []

    def tmux_version(self) -> str | None:
        """Report the tmux version the tape was recorded against.

        Satisfies :class:`~libtmux.engines.base.SupportsTmuxVersion`, which is
        what lets a replay serve listing queries with no tmux installed: the
        version-gated ``-F`` template is otherwise resolved by running
        ``tmux -V``, and a machine replaying a tape may have no tmux at all.

        Examples
        --------
        >>> from libtmux.engines import ReplayEngine
        >>> ReplayEngine({}, tmux_version="3.7").tmux_version()
        '3.7'
        """
        return self._tmux_version

    @classmethod
    def from_dict(cls, tape: Mapping[str, t.Any]) -> ReplayEngine:
        """Rebuild an engine from :meth:`RecordingEngine.to_dict` output.

        Parameters
        ----------
        tape : Mapping
            A serialized tape: ``{"tmux_version": ..., "commands": [...]}``.

        Returns
        -------
        ReplayEngine

        Examples
        --------
        >>> from libtmux.engines import ReplayEngine
        >>> from libtmux.server import Server
        >>> engine = ReplayEngine.from_dict({
        ...     "tmux_version": "3.7",
        ...     "commands": [
        ...         {
        ...             "args": ["display-message", "-p", "hi"],
        ...             "cmd": ["tmux", "display-message", "-p", "hi"],
        ...             "stdout": ["hi"],
        ...             "stderr": [],
        ...             "returncode": 0,
        ...         }
        ...     ],
        ... })
        >>> Server(engine=engine).cmd("display-message", "-p", "hi").stdout
        ['hi']
        """
        # A list, not a dict comprehension: the same command recorded twice
        # with different answers must stay two exchanges, or the tape replays
        # the end state for the earlier step.
        return cls(
            [
                Exchange(
                    args=tuple(entry["args"]),
                    result=CommandResult(
                        cmd=tuple(entry.get("cmd", ())),
                        stdout=tuple(entry.get("stdout", ())),
                        stderr=tuple(entry.get("stderr", ())),
                        returncode=int(entry.get("returncode", 0)),
                    ),
                )
                for entry in tape.get("commands", ())
            ],
            tmux_version=tape.get("tmux_version"),
        )

    def run(self, request: CommandRequest) -> CommandResult:
        """Return the recorded answer for *request*.

        Raises
        ------
        :exc:`~libtmux.exc.UnscriptedCommand`
            The tape holds no answer for this argv.
        """
        answers = self._answers.get(request.args)
        if not answers:
            # A listing query's -F template is version-gated, so the commonest
            # cause of a miss on a tape that "should" have it is replaying
            # against a different tmux than the one recorded.
            hint = (
                f"tape recorded on tmux {self._tmux_version}"
                if self._tmux_version
                else None
            )
            raise exc.UnscriptedCommand(request.args, hint) from None

        served = self._served.get(request.args, 0)
        if served < len(answers):
            self._served[request.args] = served + 1
            self.requests.append(request.args)
            return answers[served]

        if len(answers) == 1:
            # The answer never varied while recording, so repeating it cannot
            # misreport a state change. This keeps a read-only query usable more
            # often than it was recorded.
            self.requests.append(request.args)
            return answers[0]

        # It *did* vary, so there is no defensible answer for the extra call:
        # replaying the last one would report the end state for a step that
        # happened earlier.
        hint = (
            f"answered {len(answers)} times while recording, "
            f"asked {served + 1} times now"
        )
        raise exc.UnscriptedCommand(request.args, hint) from None

    def __contains__(self, args: object) -> bool:
        """Whether the tape can answer *args*."""
        return args in self._answers

    def __len__(self) -> int:
        """Return how many distinct commands the tape answers."""
        return len(self._answers)

    def __iter__(self) -> Iterator[tuple[str, ...]]:
        """Iterate the argvs the tape can answer."""
        return iter(self._answers)
