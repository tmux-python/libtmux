"""Engines: the seam between libtmux's object API and tmux itself.

An *engine* answers one question -- how does a tmux command actually get run?
:class:`~libtmux.engines.subprocess.SubprocessEngine` is the default and forks the
tmux CLI, which is what libtmux has always done. Because
:class:`~libtmux.engines.base.TmuxEngine` is a
:class:`typing.Protocol`, an in-memory fake, a recorder, or a control-mode client
can take its place:

>>> from libtmux.engines import CommandRequest, CommandResult, TmuxEngine
>>> class RecordingEngine:
...     def __init__(self):
...         self.seen: list[tuple[str, ...]] = []
...
...     def run(self, request):
...         self.seen.append(request.args)
...         return CommandResult(cmd=("tmux", *request.args), stdout=("$1",))
...
...     def run_batch(self, requests):
...         return [self.run(request) for request in requests]
>>> engine = RecordingEngine()
>>> isinstance(engine, TmuxEngine)
True

Injection happens at the :class:`~libtmux.Server` boundary:

>>> from libtmux.server import Server
>>> Server(socket_name="engine_docs", engine=engine).cmd("list-sessions").stdout
['$1']
>>> engine.seen
[('list-sessions',)]

The connection flags (``-L``/``-S``/``-f``/``-2``/``-8``) are *not* part of a
request: they belong to the engine's
:class:`~libtmux.engines.connection.ServerConnection`, so every engine sees the
same request regardless of which tmux server it targets.
"""

from __future__ import annotations

from libtmux.engines.base import (
    AsyncTmuxEngine,
    CommandRequest,
    CommandResult,
    CommandSeparator,
    DirectArgv,
    SupportsCommandLine,
    SupportsConnection,
    SupportsTmuxVersion,
    TmuxEngine,
    encode_direct_argv,
    is_command_separator,
    split_direct_argv,
)
from libtmux.engines.connection import ServerConnection
from libtmux.engines.record import (
    Exchange,
    RecordingEngine,
    ReplayEngine,
    Tape,
)
from libtmux.engines.registry import (
    ENGINE_ENTRY_POINT_GROUP,
    available_engines,
    create_engine,
    register_engine,
    unregister_engine,
)
from libtmux.engines.subprocess import SubprocessEngine

__all__ = (
    "ENGINE_ENTRY_POINT_GROUP",
    "AsyncTmuxEngine",
    "CommandRequest",
    "CommandResult",
    "CommandSeparator",
    "DirectArgv",
    "Exchange",
    "RecordingEngine",
    "ReplayEngine",
    "ServerConnection",
    "SubprocessEngine",
    "SupportsCommandLine",
    "SupportsConnection",
    "SupportsTmuxVersion",
    "Tape",
    "TmuxEngine",
    "available_engines",
    "create_engine",
    "encode_direct_argv",
    "is_command_separator",
    "register_engine",
    "split_direct_argv",
    "unregister_engine",
)
