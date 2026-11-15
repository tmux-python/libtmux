"""Feature decisions for an observed tmux daemon."""

from __future__ import annotations

import dataclasses
import re
import typing as t

_FEATURES = {"program-owned": "3.8"}


def _release(raw: str) -> tuple[int, int, int, int] | None:
    next_release = re.fullmatch(r"next-(\d+)\.(\d+)", raw)
    if next_release is not None:
        next_major, next_minor = map(int, next_release.groups())
        return next_major, next_minor, 0, 0
    release = re.fullmatch(r"(\d+)\.(\d+)(?:([a-z])|-rc(\d*))?", raw)
    if release is None:
        return None
    major, minor, patch, candidate = release.groups()
    if candidate is not None:
        return int(major), int(minor), 1, int(candidate or 0)
    return int(major), int(minor), 2, ord(patch) - ord("a") + 1 if patch else 0


@dataclasses.dataclass(frozen=True, slots=True)
class Capability:
    """Explain whether one operation is available on an observed daemon.

    Attributes
    ----------
    name : str
        Stable feature identifier, independent of the client's tmux version.
    since : str
        First qualified tmux release for this library operation.
    status : str
        ``supported``, ``unsupported`` or ``unknown``. Unknown versions never
        authorize an operation.
    reason : str
        Explanation suitable for a caller's feature-selection interface.
    """

    name: str
    since: str
    status: t.Literal["supported", "unsupported", "unknown"]
    reason: str


@dataclasses.dataclass(frozen=True, slots=True)
class ServerCapabilities:
    """Describe features at one observation of a connected daemon.

    This immutable report is informational. Operations recheck their own route
    and identity; retaining a report does not authorize a later mutation.

    Attributes
    ----------
    pid : int
        Observed tmux daemon process identifier.
    start_time : int
        Daemon start time in seconds since the Unix epoch.
    version : str
        Version returned by the daemon, without client-binary substitution.
    """

    pid: int
    start_time: int
    version: str

    @property
    def features(self) -> tuple[Capability, ...]:
        """Return immutable decisions for each library feature in the registry."""
        return tuple(self.feature(name) for name in _FEATURES)

    def feature(self, name: str) -> Capability:
        """Return a decision, raising ``KeyError`` for an unregistered feature."""
        since = _FEATURES[name]
        have, minimum = _release(self.version), _release(since)
        assert minimum is not None
        if have is None:
            return Capability(
                name, since, "unknown", f"unrecognized daemon version {self.version!r}"
            )
        if have < minimum:
            return Capability(
                name, since, "unsupported", f"requires connected tmux {since} or newer"
            )
        return Capability(name, since, "supported", f"available on tmux {self.version}")

    def supports(self, name: str) -> bool:
        """Return false for unsupported or unknown daemon versions."""
        return self.feature(name).status == "supported"
