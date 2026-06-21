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

import types
import typing as t
from dataclasses import dataclass

from libtmux._compat import LooseVersion
from libtmux.experimental.ops._types import render_target
from libtmux.experimental.ops.exc import VersionUnsupported
from libtmux.experimental.ops.results import Result, status_for

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

ResultT = t.TypeVar("ResultT", bound=Result)


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
        if LooseVersion(version) < LooseVersion(self.min_version):
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
        return LooseVersion(version) >= LooseVersion(need)

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
        return self._make_result(
            rendered,
            status,
            returncode,
            tuple(stdout),
            tuple(stderr),
            version=version,
        )

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
