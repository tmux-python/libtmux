"""Immutable sampled pane text and capture provenance."""

from __future__ import annotations

import time
import typing as t
from dataclasses import dataclass, field

from libtmux import exc
from libtmux.common import raise_if_stderr

if t.TYPE_CHECKING:
    from libtmux.pane import Pane


@dataclass(frozen=True, slots=True)
class PaneObservation:
    """Retain decoded capture text without a live pane or server reference.

    ``lines`` and ``command`` are owned tuples. The interval counts controller
    monotonic nanoseconds around one command; it is not a server timestamp.
    ``pane_id`` records the requested target. Its daemon/object lifetime remains
    unknown with the legacy pane handle, so ``target_lifetime_verified`` is None.
    """

    pane_id: str
    lines: tuple[str, ...] = field(repr=False)
    command: tuple[str, ...] = field(repr=False)
    start: t.Literal["-"] | int | None
    end: t.Literal["-"] | int | None
    join_wrapped: bool
    started_ns: int
    finished_ns: int
    target_lifetime_verified: bool | None = field(default=None, init=False)

    @property
    def text(self) -> str:
        """Return retained lines joined with LF, without terminal-column semantics."""
        return "\n".join(self.lines)

    @classmethod
    def capture(
        cls,
        pane: Pane,
        *,
        start: t.Literal["-"] | int | None = None,
        end: t.Literal["-"] | int | None = None,
        join_wrapped: bool = False,
        max_text_codepoints: int = 1_048_576,
    ) -> PaneObservation:
        """Capture once through the supplied pane's command route.

        The call retains plain decoded text using the existing command's
        trailing-empty-line policy. The text limit includes LF between lines
        and counts Python Unicode code points. It applies after transport
        decoding; it is not a transport memory cap or command deadline.

        Parameters
        ----------
        pane : Pane
            Borrowed pane providing the backend and target. No cleanup is acquired.
        start, end : int | "-" | None
            Requested tmux line range, using ordinary capture-pane semantics.
        join_wrapped : bool
            Join wrapped physical lines using tmux's capture policy.
        max_text_codepoints : int
            Positive admission limit for retained decoded text, including LF.

        Raises
        ------
        ValueError
            Invalid selection, absent pane ID, or text exceeding the limit.
        TypeError
            ``join_wrapped`` is not a bool.
        libtmux.exc.LibTmuxException
            The capture command reports stderr or a nonzero/unknown exit status.

        Notes
        -----
        Backend exceptions propagate unchanged. Blocking defaults remain those
        of ``pane.cmd``; this method adds no cancellation operation. A retained
        value survives pane removal while referenced, but supplies no continuity,
        durable storage, hidden terminal state, or application-completion proof.
        """
        if (
            isinstance(max_text_codepoints, bool)
            or not isinstance(max_text_codepoints, int)
            or max_text_codepoints <= 0
        ):
            msg = "max_text_codepoints must be a positive integer"
            raise ValueError(msg)
        for name, value in (("start", start), ("end", end)):
            if value is not None and (
                isinstance(value, bool) or not (isinstance(value, int) or value == "-")
            ):
                msg = f"{name} must be an integer, '-' or None"
                raise ValueError(msg)
        if not isinstance(join_wrapped, bool):
            msg = "join_wrapped must be a bool"
            raise TypeError(msg)
        pane_id = pane.pane_id
        if not pane_id:
            msg = "Pane must have a pane_id to capture"
            raise ValueError(msg)
        args = ["-p"]
        if start is not None:
            args.extend(("-S", str(start)))
        if end is not None:
            args.extend(("-E", str(end)))
        if join_wrapped:
            args.append("-J")
        started_ns = time.monotonic_ns()
        result = pane.cmd("capture-pane", *args, target=pane_id)
        finished_ns = time.monotonic_ns()
        raise_if_stderr(result, "capture-pane")
        if result.returncode != 0:
            msg = f"command exited with status {result.returncode}"
            raise exc.LibTmuxException(msg, subcommand="capture-pane")
        text_size = sum(map(len, result.stdout)) + max(0, len(result.stdout) - 1)
        if text_size > max_text_codepoints:
            msg = "captured text exceeds max_text_codepoints"
            raise ValueError(msg)
        return cls(
            pane_id=pane_id,
            lines=tuple(result.stdout),
            command=tuple(result.cmd),
            start=start,
            end=end,
            join_wrapped=join_wrapped,
            started_ns=started_ns,
            finished_ns=finished_ns,
        )
