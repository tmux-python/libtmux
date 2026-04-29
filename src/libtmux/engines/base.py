"""Core abstractions for libtmux command engines."""

from __future__ import annotations

import pathlib
import typing as t
from dataclasses import dataclass
from enum import Enum, IntEnum


@dataclass(frozen=True)
class CommandRequest:
    """Description of a tmux command invocation."""

    args: tuple[str, ...]
    tmux_bin: str | None = None

    @classmethod
    def from_args(
        cls,
        *args: t.Any,
        tmux_bin: str | pathlib.Path | None = None,
    ) -> CommandRequest:
        """Build a request from arbitrary command arguments."""
        return cls(
            args=tuple(str(arg) for arg in args),
            tmux_bin=str(tmux_bin) if tmux_bin is not None else None,
        )


@dataclass
class CommandResult:
    """Result of executing a tmux command."""

    cmd: list[str]
    stdout: list[str]
    stderr: list[str]
    returncode: int
    process: object | None = None


class EngineKind(str, Enum):
    """Named command engine families."""

    SUBPROCESS = "subprocess"
    IMSG = "imsg"


class ImsgProtocolVersion(IntEnum):
    """Known tmux imsg protocol versions."""

    V8 = 8


SubprocessEngineName: t.TypeAlias = t.Literal["subprocess"]
ImsgEngineName: t.TypeAlias = t.Literal["imsg"]
EngineName: t.TypeAlias = SubprocessEngineName | ImsgEngineName
ImsgProtocolHint: t.TypeAlias = str | int | ImsgProtocolVersion


@dataclass(frozen=True)
class EngineSpec:
    """Typed engine configuration for libtmux callers."""

    kind: EngineKind
    protocol_version: int | None = None

    def __post_init__(self) -> None:
        """Normalize enum and protocol fields after construction."""
        kind = EngineKind(self.kind)
        protocol_version = (
            int(self.protocol_version) if self.protocol_version is not None else None
        )
        if kind is not EngineKind.IMSG and protocol_version is not None:
            msg = "protocol_version is only valid for the imsg engine"
            raise ValueError(msg)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "protocol_version", protocol_version)

    @classmethod
    def subprocess(cls) -> EngineSpec:
        """Build a subprocess engine spec."""
        return cls(kind=EngineKind.SUBPROCESS)

    @classmethod
    def imsg(
        cls,
        protocol: ImsgProtocolVersion | int | None = None,
    ) -> EngineSpec:
        """Build an imsg engine spec."""
        return cls(
            kind=EngineKind.IMSG,
            protocol_version=int(protocol) if protocol is not None else None,
        )


class TmuxEngine(t.Protocol):
    """Protocol for components that can execute tmux commands."""

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute a tmux command and return a structured result."""


EngineLike = TmuxEngine | EngineSpec | EngineName | None
