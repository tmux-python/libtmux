"""The base :class:`Operation` value.

An operation is an immutable, keyword-only dataclass that carries everything an
engine needs to render a tmux command, validate it against a tmux version, and
type its result -- but it never dispatches. Operation classes declare their
stable metadata (``kind``, ``command``, ``scope``, ``result_cls``, effects,
safety, version gates) as class variables, so the class itself is the single
source of truth that the registry, serializer, and docs catalog all read from.

Rendering is pure: :meth:`Operation.render` produces an argv tuple from the
operation's fields, dropping version-gated flags an older tmux cannot accept,
and :meth:`Operation.build_result` adapts raw tmux output into the operation's
typed result -- both without touching a tmux server.
"""

from __future__ import annotations

import logging
import types
import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import render_target
from libtmux.experimental.ops.exc import VersionUnsupported
from libtmux.experimental.ops.results import Result, status_for
from libtmux.neo import _normalize_tmux_version

if t.TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from libtmux.experimental.ops._chain import OpChain
    from libtmux.experimental.ops._types import (
        Effects,
        Safety,
        Scope,
        Status,
        Target,
    )

logger = logging.getLogger(__name__)

ResultT = t.TypeVar("ResultT", bound=Result)


def _requested_format_fields(argv: tuple[str, ...]) -> int:
    """How many ``#{...}`` fields a rendered ``-P -F`` template asks tmux to print.

    Returns ``0`` when the argv carries no printed format, so a non-capturing
    operation is never held to a capture invariant.

    Examples
    --------
    >>> _requested_format_fields(("new-session", "-d", "-P", "-F", "#{session_id}"))
    1
    >>> _requested_format_fields(
    ...     ("new-session", "-P", "-F", "#{session_id} #{window_id} #{pane_id}")
    ... )
    3
    >>> _requested_format_fields(("kill-window", "-t", "@1"))
    0
    """
    if "-P" not in argv or "-F" not in argv:
        return 0
    index = argv.index("-F") + 1
    if index >= len(argv):
        return 0
    return argv[index].count("#{")


def _check_capture_invariant(result: Result) -> None:
    """Log when a creating operation succeeded but captured fewer ids than it asked for.

    A create op rendered with ``-P -F`` tells tmux exactly how many ids to print.
    A ``complete`` result must therefore carry that many. When it carries fewer --
    none at all, or a *partial* line missing the trailing fields -- the missing
    ids become ``None`` silently, and the failure only surfaces later and
    elsewhere: as an unresolvable forward reference in a plan, or as an
    ``AttributeError`` when a ``None`` id is wrapped in a typed target.

    Comparing against the requested field count (rather than only
    :attr:`~.results.Result.created_id`) is what catches the partial case, where
    the primary id parsed fine and only its implicit children went missing.

    Examples
    --------
    >>> from libtmux.experimental.ops import NewSession
    >>> full = NewSession(capture_panes=True).build_result(
    ...     returncode=0, stdout=("$1 @2 %3",)
    ... )
    >>> (full.new_id, full.first_window_id, full.first_pane_id)
    ('$1', '@2', '%3')

    A short line silently drops the children -- which is what this check reports:

    >>> partial = NewSession(capture_panes=True).build_result(
    ...     returncode=0, stdout=("$1",)
    ... )
    >>> (partial.new_id, partial.first_window_id, partial.first_pane_id)
    ('$1', None, None)
    """
    operation = result.operation
    if not getattr(operation.effects, "creates", None):
        return
    if result.status != "complete":
        # A create that did not complete has no id to hand downstream. Nothing
        # raises here (results never raise on construction), so the ``None`` id
        # travels until something dereferences it -- far from the real cause.
        # Naming the failing create here is what makes that cause findable.
        logger.warning(
            "tmux create op did not complete; downstream ids will be None",
            extra={
                "tmux_cmd": " ".join(result.argv),
                "tmux_subcommand": operation.command,
                "tmux_exit_code": result.returncode,
                "tmux_stdout": list(result.stdout),
                "tmux_stdout_len": len(result.stdout),
                "tmux_stderr": list(result.stderr),
                "tmux_stderr_len": len(result.stderr),
            },
        )
        return
    expected = _requested_format_fields(result.argv)
    if expected == 0:
        return  # the op never asked tmux to print an id (capture=False)
    captured = len(result.stdout[0].split()) if result.stdout else 0
    if captured >= expected:
        return
    logger.error(
        "tmux create op completed but captured %s of %s requested ids",
        captured,
        expected,
        extra={
            "tmux_cmd": " ".join(result.argv),
            "tmux_subcommand": operation.command,
            "tmux_target": " ".join(result.argv[:3]),
            "tmux_exit_code": result.returncode,
            "tmux_stdout": list(result.stdout),
            "tmux_stdout_len": len(result.stdout),
            "tmux_stderr": list(result.stderr),
            "tmux_stderr_len": len(result.stderr),
        },
    )


@dataclass(frozen=True, kw_only=True)
class Operation(t.Generic[ResultT]):
    """Inert, typed description of one tmux command.

    Subclasses declare the class-level metadata and provide :meth:`args` (the
    positional tokens after the target). The instance fields describe one
    concrete invocation.

    Parameters
    ----------
    target : Target or None
        The ``-t`` target, or ``None`` for "no explicit target".
    src_target : Target or None
        The ``-s`` source target for dual-target commands (``swap-pane``,
        ``join-pane``, ``link-window``, ...), or ``None`` when unused.

    Notes
    -----
    Class variables (set by subclasses):

    ``kind``
        Stable discriminator, also the registry key (e.g. ``"split_window"``).
    ``command``
        The tmux command name (e.g. ``"split-window"``).
    ``scope``
        The tmux object scope (:data:`~._types.Scope`).
    ``result_cls``
        The :class:`~.results.Result` subclass this operation returns.
    ``chainable``
        Whether the command may be folded into a one-dispatch sequence.
    ``primitive``
        ``True`` when the operation wraps one tmux command; ``False`` when it is
        composed from others (e.g. a synthesized server-exists check).
    ``safety``
        The :data:`~._types.Safety` tier.
    ``effects``
        An :class:`~._types.Effects` descriptor.
    ``min_version``
        Minimum tmux version the whole operation requires, if any.
    ``flag_version_map``
        Maps a feature label to the minimum tmux version that supports it; the
        operation consults this in :meth:`args` to drop unsupported flags.
    """

    target: Target | None = None
    src_target: Target | None = None

    kind: t.ClassVar[str]
    command: t.ClassVar[str]
    scope: t.ClassVar[Scope]
    result_cls: t.ClassVar[type[Result]]
    chainable: t.ClassVar[bool] = True
    primitive: t.ClassVar[bool] = True
    safety: t.ClassVar[Safety] = "mutating"
    effects: t.ClassVar[Effects]
    min_version: t.ClassVar[str | None] = None
    flag_version_map: t.ClassVar[Mapping[str, str]] = types.MappingProxyType({})

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Return the positional argument tokens after the target.

        Override per operation. ``version`` is the tmux version the engine will
        run against (``None`` means "assume latest"); use :meth:`flag_available`
        to drop flags an older tmux cannot accept.

        Returns
        -------
        tuple[str, ...]
        """
        return ()

    def render(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render this operation as a tmux argv tuple.

        Parameters
        ----------
        version : str or None
            The tmux version to render against. ``None`` renders every flag.

        Returns
        -------
        tuple[str, ...]
            ``(command, ["-t", target], *args)``.

        Raises
        ------
        ~libtmux.experimental.ops.exc.VersionUnsupported
            When the running tmux is older than :attr:`min_version`.
        TypeError
            When the target is an unresolved
            :class:`~._types.SlotRef` (a planner bug).

        Examples
        --------
        >>> from libtmux.experimental.ops import SendKeys
        >>> from libtmux.experimental.ops._types import PaneId
        >>> SendKeys(target=PaneId("%1"), keys="echo hi", enter=True).render()
        ('send-keys', '-t', '%1', 'echo hi', 'Enter')
        """
        self.check_version(version)
        rendered: list[str] = [self.command]
        token = render_target(self.target)
        if token is not None:
            rendered.extend(("-t", token))
        rendered.extend(self.args(version=version))
        return tuple(rendered)

    def check_version(self, version: str | None) -> None:
        """Raise if *version* is older than this operation's :attr:`min_version`.

        Parameters
        ----------
        version : str or None
            The running tmux version, or ``None`` to skip the check.

        Examples
        --------
        >>> from libtmux.experimental.ops import SplitWindow
        >>> from libtmux.experimental.ops._types import PaneId
        >>> SplitWindow(target=PaneId("%1")).check_version("3.4")
        """
        if version is None or self.min_version is None:
            return
        if _normalize_tmux_version(version) < _normalize_tmux_version(self.min_version):
            raise VersionUnsupported(
                self.kind,
                need=self.min_version,
                have=version,
            )

    def flag_available(self, label: str, version: str | None) -> bool:
        """Whether a version-gated feature is available on *version*.

        Parameters
        ----------
        label : str
            A key in :attr:`flag_version_map`.
        version : str or None
            The running tmux version, or ``None`` to assume latest.

        Returns
        -------
        bool
            ``True`` when the feature is ungated, unknown, or supported.

        Examples
        --------
        >>> from libtmux.experimental.ops import CapturePane
        >>> from libtmux.experimental.ops._types import PaneId
        >>> op = CapturePane(target=PaneId("%1"), trim_trailing=True)
        >>> op.flag_available("trim_trailing", "3.4")
        True
        >>> op.flag_available("trim_trailing", "3.0")
        False
        """
        need = self.flag_version_map.get(label)
        if need is None or version is None:
            return True
        return _normalize_tmux_version(version) >= _normalize_tmux_version(need)

    def src_args(self) -> tuple[str, ...]:
        """Render the ``-s`` source target, or ``()`` when there is none.

        Dual-target commands call this from :meth:`args` to emit their source.

        Examples
        --------
        >>> from libtmux.experimental.ops import SwapPane
        >>> from libtmux.experimental.ops._types import PaneId
        >>> SwapPane(target=PaneId("%1"), src_target=PaneId("%2")).src_args()
        ('-s', '%2')
        """
        token = render_target(self.src_target)
        return ("-s", token) if token is not None else ()

    def build_result(
        self,
        *,
        returncode: int,
        argv: tuple[str, ...] | None = None,
        stdout: Sequence[str] = (),
        stderr: Sequence[str] = (),
        version: str | None = None,
    ) -> ResultT:
        """Adapt raw tmux output into this operation's typed result.

        Parameters
        ----------
        returncode : int
            tmux exit code.
        argv : tuple[str, ...] or None
            The argv that produced the output; rendered from this operation when
            omitted.
        stdout, stderr : Sequence[str]
            Captured output lines.
        version : str or None
            The tmux version the output was produced against. Used to render
            *argv* when omitted, and passed to :meth:`_make_result` so payload
            parsing can match the version-gated render (e.g. a ``-F`` template).

        Returns
        -------
        ResultT
            An instance of :attr:`result_cls`.
        """
        rendered = argv if argv is not None else self.render(version=version)
        status = status_for(returncode, stderr)
        result = self._make_result(
            rendered,
            status,
            returncode,
            tuple(stdout),
            tuple(stderr),
            version=version,
        )
        _check_capture_invariant(result)
        return result

    def result_with_status(
        self,
        status: Status,
        *,
        version: str | None = None,
        returncode: int = 0,
        stdout: Sequence[str] = (),
        stderr: Sequence[str] = (),
    ) -> ResultT:
        """Build a result with an explicit *status* (no status inference).

        Used when the status is known out of band -- e.g. a chained operation
        whose ``;`` group ran but whose own outcome must be marked ``skipped``
        because an earlier member failed.
        """
        return self._make_result(
            self.render(version=version),
            status,
            returncode,
            tuple(stdout),
            tuple(stderr),
            version=version,
        )

    def then(self, other: Operation[t.Any] | OpChain) -> OpChain:
        """Compose with another operation (or chain) into an :class:`OpChain`."""
        from libtmux.experimental.ops._chain import OpChain

        return OpChain((self,)).then(other)

    def __rshift__(self, other: Operation[t.Any] | OpChain) -> OpChain:
        """Compose operations with ``>>`` into an :class:`OpChain`."""
        return self.then(other)

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
        version: str | None = None,
    ) -> ResultT:
        """Construct the result instance; override to populate typed payloads.

        ``version`` is the tmux version the output was produced against; payload
        parsers that depend on a version-gated render (read ops) use it. The base
        implementation and simple overrides ignore it.
        """
        return t.cast(
            "ResultT",
            self.result_cls(
                operation=self,
                argv=argv,
                status=status,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
            ),
        )
