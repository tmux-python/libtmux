"""Deterministic fail-closed tape recording and replay for :mod:`libtmux.test`."""

from __future__ import annotations

import typing as t
from collections.abc import Mapping

from libtmux import exc
from libtmux.engine import TmuxRequest, TmuxResult

if t.TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = ("Exchange", "ReplayEngine", "Tape")


class Exchange(t.NamedTuple):
    """A recorded command tuple and its raw-byte :class:`~libtmux.engine.TmuxResult`.

    Attributes
    ----------
    commands : tuple[tuple[str, ...], ...]
        Recorded command tuples from :attr:`~libtmux.engine.TmuxRequest.commands`.
    result : TmuxResult
        Recorded raw-byte outcome.
    """

    commands: tuple[tuple[str, ...], ...]
    result: TmuxResult


Tape: t.TypeAlias = (
    "Sequence[Exchange] | Mapping[tuple[tuple[str, ...], ...], TmuxResult]"
)


class ReplayEngine:
    r"""Replay recorded tmux exchanges offline, failing closed on unscripted calls.

    Parameters
    ----------
    tape : Tape
        Sequence of :class:`Exchange` entries or mapping from command tuples to
        :class:`~libtmux.engine.TmuxResult`.
    tmux_version : str, optional
        Tmux version reported to version-gated format builders.
    endpoint : str, optional
        Simulated transport endpoint.

    Examples
    --------
    >>> from libtmux.engine import TmuxResult
    >>> from libtmux.server import Server as TmuxServer
    >>> from libtmux.test import Exchange, ReplayEngine
    >>> tape = [
    ...     Exchange(
    ...         commands=(("display-message", "-p", "hi"),),
    ...         result=TmuxResult(
    ...             argv=("tmux", "display-message", "-p", "hi"),
    ...             stdout=b"hi\n",
    ...         ),
    ...     )
    ... ]
    >>> replay = ReplayEngine(tape, tmux_version="3.8")
    >>> srv = TmuxServer(socket_name="replay", engine=replay)
    >>> srv.cmd("display-message", "-p", "hi").stdout
    ['hi']
    """

    def __init__(
        self,
        tape: Tape,
        *,
        tmux_version: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        exchanges: t.Iterable[Exchange] = (
            (Exchange(cmds, res) for cmds, res in tape.items())
            if isinstance(tape, Mapping)
            else tape
        )
        self._answers: dict[tuple[tuple[str, ...], ...], list[TmuxResult]] = {}
        for cmds, res in exchanges:
            self._answers.setdefault(cmds, []).append(res)
        self._served: dict[tuple[tuple[str, ...], ...], int] = {}
        self._tmux_version = tmux_version
        self._endpoint = endpoint
        self.requests: list[TmuxRequest] = []

    @property
    def endpoint(self) -> str | None:
        """Simulated transport endpoint."""
        return self._endpoint

    def tmux_version(self) -> str | None:
        """Return the tmux version the tape was recorded against."""
        return self._tmux_version

    @classmethod
    def from_dict(cls, data: Mapping[str, t.Any]) -> ReplayEngine:
        """Rebuild a :class:`ReplayEngine` from a JSON-compatible dictionary."""
        entries: list[Exchange] = []
        for entry in data.get("exchanges", ()):
            raw_cmds = entry["commands"]
            cmds = tuple(tuple(str(tok) for tok in cmd) for cmd in raw_cmds)
            stdout_raw = entry.get("stdout", "")
            stderr_raw = entry.get("stderr", "")
            stdout_b = (
                stdout_raw.encode("utf-8")
                if isinstance(stdout_raw, str)
                else bytes(stdout_raw)
            )
            stderr_b = (
                stderr_raw.encode("utf-8")
                if isinstance(stderr_raw, str)
                else bytes(stderr_raw)
            )
            entries.append(
                Exchange(
                    commands=cmds,
                    result=TmuxResult(
                        argv=tuple(str(x) for x in entry.get("argv", ("tmux",))),
                        stdout=stdout_b,
                        stderr=stderr_b,
                        returncode=int(entry.get("returncode", 0)),
                    ),
                )
            )
        return cls(entries, tmux_version=data.get("tmux_version"))

    def execute(self, request: TmuxRequest) -> TmuxResult:
        """Return the recorded answer or raise :exc:`~libtmux.exc.UnscriptedCommand`."""
        answers = self._answers.get(request.commands)
        if not answers:
            hint = (
                f"tape recorded on tmux {self._tmux_version}"
                if self._tmux_version
                else None
            )
            raise exc.UnscriptedCommand(request.commands, hint)

        served = self._served.get(request.commands, 0)
        if served < len(answers):
            self._served[request.commands] = served + 1
            self.requests.append(request)
            return answers[served]

        if len(answers) == 1:
            self.requests.append(request)
            return answers[0]

        hint = (
            f"answered {len(answers)} times while recording, "
            f"asked {served + 1} times now"
        )
        raise exc.UnscriptedCommand(request.commands, hint)

    def execute_batch(self, requests: Sequence[TmuxRequest]) -> list[TmuxResult]:
        """Execute *requests* in order against the recorded tape."""
        return [self.execute(req) for req in requests]

    def __contains__(self, commands: object) -> bool:
        """Return ``True`` when *commands* has at least one recorded answer."""
        return commands in self._answers

    def __len__(self) -> int:
        """Return the count of distinct recorded command keys."""
        return len(self._answers)

    def __iter__(self) -> Iterator[tuple[tuple[str, ...], ...]]:
        """Iterate distinct recorded command keys."""
        return iter(self._answers)
