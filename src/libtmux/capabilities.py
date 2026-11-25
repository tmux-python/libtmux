"""Runtime feature and workaround inspection for an observed tmux daemon."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux import exc
from libtmux._internal.daemon_guard import DaemonGuard
from libtmux._internal.support import capabilities as _cap_table
from libtmux._internal.support.capabilities import (
    CAPABILITIES,
    TMUX_MIN_VERSION,
    WORKAROUNDS,
    evaluate_capability,
    get_workaround,
)

__all__ = (
    "Capability",
    "ServerCapabilities",
    "Workaround",
)


@dataclass(frozen=True, slots=True)
class Capability:
    """Feature availability decision for one observed tmux daemon.

    Attributes
    ----------
    name : str
        Stable capability identifier (for example ``"control-mode"``).
    since : str
        First tmux release supporting this capability.
    status : {"supported", "unsupported", "unknown"}
        Evaluation outcome; ``"unknown"`` never authorizes a gated operation.
    reason : str
        Human-readable explanation of *status*.

    Examples
    --------
    >>> from libtmux.capabilities import ServerCapabilities
    >>> caps = ServerCapabilities(pid=100, start_time=1700000000, version="3.8a")
    >>> cap = caps.feature("control-mode")
    >>> cap.status, cap.supported
    ('supported', True)
    """

    name: str
    since: str
    status: t.Literal["supported", "unsupported", "unknown"]
    reason: str

    @property
    def id(self) -> str:
        """Alias for :attr:`name` matching ``capabilities.json`` ``id``."""
        return self.name

    @property
    def supported(self) -> bool:
        """Return ``True`` only when ``status == "supported"``."""
        return self.status == "supported"

    @property
    def until(self) -> str | None:
        """First release where the feature was removed, or ``None``."""
        spec = _cap_table._BY_ID.get(self.name)
        return spec.until if spec is not None else None

    @property
    def handling(self) -> t.Literal["refuse", "fallback", "repair"]:
        """Configured fallback/refusal policy from the capability registry."""
        spec = _cap_table._BY_ID.get(self.name)
        return spec.handling if spec is not None else "refuse"

    @property
    def summary(self) -> str:
        """Short description of the capability."""
        spec = _cap_table._BY_ID.get(self.name)
        return spec.summary if spec is not None else ""


@dataclass(frozen=True, slots=True)
class Workaround:
    """Release-specific upstream workaround state on an observed daemon.

    Attributes
    ----------
    id : str
        Stable workaround identifier.
    name : str
        Human-readable workaround title.
    summary : str
        Description of the upstream defect and mitigation.
    releases : tuple[str, ...]
        Affected tmux release strings.
    handling : {"refuse", "repair"}
        Mitigation mode applied by libtmux.
    active : bool
        ``True`` when the connected daemon's version is in ``releases``.
    """

    id: str
    name: str
    summary: str
    releases: tuple[str, ...]
    handling: t.Literal["refuse", "repair"]
    active: bool


@dataclass(frozen=True, slots=True)
class ServerCapabilities:
    """Immutable capability snapshot for one observed tmux daemon generation.

    Attributes
    ----------
    pid : int
        Observed tmux daemon process identifier.
    start_time : int
        Daemon start timestamp in Unix epoch seconds.
    version : str
        Daemon version reported by ``#{version}`` without client substitution.

    Examples
    --------
    >>> from libtmux.capabilities import ServerCapabilities
    >>> report = ServerCapabilities(pid=42, start_time=1700000000, version="3.6a")
    >>> report.supports("run-shell-start-directory")
    True
    >>> report.supports("control-mode")
    False
    """

    pid: int
    start_time: int
    version: str

    @property
    def minimum_version(self) -> str:
        """Minimum tmux version supported by this libtmux release."""
        return TMUX_MIN_VERSION

    @property
    def daemon_guard(self) -> DaemonGuard:
        """Generation fence matching this snapshot's ``pid`` and ``start_time``."""
        return DaemonGuard(pid=self.pid, start_time=self.start_time)

    @property
    def features(self) -> tuple[Capability, ...]:
        """Decisions for every registered capability, in manifest order."""
        return tuple(self.feature(spec.id) for spec in CAPABILITIES)

    @property
    def workarounds(self) -> tuple[Workaround, ...]:
        """States for every registered workaround, in manifest order."""
        return tuple(self.workaround(spec.id) for spec in WORKAROUNDS)

    def feature(self, name: str) -> Capability:
        """Return :class:`Capability` for *name*, raising ``KeyError`` if unknown."""
        spec = _cap_table.get(name)
        status, reason = evaluate_capability(self.version, spec)
        return Capability(
            name=spec.id,
            since=spec.since,
            status=status,
            reason=reason,
        )

    def workaround(self, workaround_id: str) -> Workaround:
        """Return :class:`Workaround` for *workaround_id*, or raise ``KeyError``."""
        spec = get_workaround(workaround_id)
        return Workaround(
            id=spec.id,
            name=spec.name,
            summary=spec.summary,
            releases=spec.releases,
            handling=spec.handling,
            active=self.version in spec.releases,
        )

    def supports(self, name: str) -> bool:
        """Return ``True`` when feature *name* is supported on this daemon."""
        return self.feature(name).supported

    def require(self, name: str) -> None:
        """Raise :exc:`~libtmux.exc.VersionTooLow` when *name* is unsupported."""
        decision = self.feature(name)
        if not decision.supported:
            msg = f"{name}: {decision.reason}"
            raise exc.VersionTooLow(msg)
