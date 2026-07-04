"""Command-line interface for a tmux-native agent console."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import os
import pathlib
import re
import shlex
import signal
import subprocess
import sys
import typing as t
from dataclasses import dataclass

import libtmux
from libtmux.experimental.agents.drive import send_to_agent
from libtmux.experimental.agents.hooks import registry as hook_registry
from libtmux.experimental.agents.hud import HudRenderer
from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.state import Agent, AgentState
from libtmux.experimental.agents.statusline import paint_status_line
from libtmux.experimental.agents.store import AgentStore, JsonFile
from libtmux.experimental.agents.wait import wait_for_agent_state
from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine
from libtmux.experimental.engines.subprocess import SubprocessEngine
from libtmux.experimental.ops._types import NameRef
from libtmux.experimental.workspace import Pane, Window, Workspace

if t.TYPE_CHECKING:
    from collections.abc import Sequence


DEFAULT_SESSION_NAME = "libtmux-agents"
"""Default tmux session name for the agent console."""

DEFAULT_WINDOW_NAME = "agents"
"""Default window name inside the console session."""


@dataclass(frozen=True)
class AgentConsoleConfig:
    """Connection and session settings for the agent console.

    Parameters
    ----------
    session_name : str
        Managed tmux session name.
    socket_name, socket_path : str or None
        tmux server selectors. ``socket_path`` wins when both are present.
    state_path : pathlib.Path or None
        JSON store read by ``status`` and written by ``monitor``.
    detached : bool
        Build or check the session without attaching the current client.
    json : bool
        Prefer machine-readable output for status-like commands.
    hud : bool
        Enable the floating HUD managed by :class:`AgentMonitor`.
    status_line : bool
        Paint a session-scoped ``status-right`` summary from the monitor.

    Examples
    --------
    >>> AgentConsoleConfig(session_name="demo").resolved_state_path.name
    'demo.json'
    """

    session_name: str = DEFAULT_SESSION_NAME
    socket_name: str | None = None
    socket_path: str | pathlib.Path | None = None
    state_path: pathlib.Path | None = None
    detached: bool = False
    json: bool = False
    hud: bool = False
    status_line: bool = True

    @property
    def resolved_state_path(self) -> pathlib.Path:
        """Return the explicit state path or the XDG-derived default.

        Examples
        --------
        >>> AgentConsoleConfig(session_name="my agents").resolved_state_path.name
        'my-agents.json'
        """
        if self.state_path is not None:
            return pathlib.Path(self.state_path)
        return default_state_path(self.session_name)


@dataclass(frozen=True)
class ConsoleResult:
    """Result data for ``start`` and ``attach``.

    Examples
    --------
    >>> ConsoleResult(False, "agents", pathlib.Path("x.json"), False).returncode
    0
    """

    created: bool
    session_name: str
    state_path: pathlib.Path
    attached: bool
    returncode: int = 0


def _slug(value: str) -> str:
    """Return a conservative filesystem slug."""
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return slug or DEFAULT_SESSION_NAME


def default_state_path(session_name: str = DEFAULT_SESSION_NAME) -> pathlib.Path:
    """Return the default JSON store path for *session_name*.

    The path follows ``$XDG_STATE_HOME`` when present and otherwise falls back
    to ``~/.local/state``.

    Examples
    --------
    >>> default_state_path("my agents").name
    'my-agents.json'
    """
    root = os.environ.get("XDG_STATE_HOME")
    base = pathlib.Path(root) if root else pathlib.Path.home() / ".local" / "state"
    return base / "libtmux" / "agents" / f"{_slug(session_name)}.json"


def _socket_args(config: AgentConsoleConfig) -> list[str]:
    """Render tmux socket selectors as argv tokens."""
    if config.socket_path is not None:
        return ["-S", str(config.socket_path)]
    if config.socket_name is not None:
        return ["-L", config.socket_name]
    return []


def _server(config: AgentConsoleConfig) -> libtmux.Server:
    """Build a libtmux server object for *config*."""
    if config.socket_path is not None:
        return libtmux.Server(socket_path=config.socket_path)
    return libtmux.Server(socket_name=config.socket_name)


def _monitor_command(config: AgentConsoleConfig) -> str:
    """Return the shell command run in the monitor pane."""
    argv = [
        sys.executable,
        "-m",
        "libtmux.agents",
        *(_socket_args(config)),
        "--session-name",
        config.session_name,
        "--state-path",
        str(config.resolved_state_path),
        "monitor",
    ]
    if config.hud:
        argv.append("--hud")
    if not config.status_line:
        argv.append("--no-status-line")
    return shlex.join(argv)


def _interactive_shell() -> str:
    """Return the user's shell command, falling back to ``/bin/sh``."""
    return os.environ.get("SHELL") or "/bin/sh"


def build_console_workspace(config: AgentConsoleConfig) -> Workspace:
    """Declare the managed tmux session used by ``start``.

    The monitor pane starts from a sent command so the build can reuse the
    existing workspace compiler and fold the session creation plan.

    Examples
    --------
    >>> cfg = AgentConsoleConfig(session_name="demo", state_path=pathlib.Path("s.json"))
    >>> ws = build_console_workspace(cfg)
    >>> (ws.name, ws.windows[0].name, len(ws.windows[0].panes))
    ('demo', 'agents', 2)
    """
    return Workspace(
        name=config.session_name,
        options={"status": "on"},
        windows=[
            Window(
                name=DEFAULT_WINDOW_NAME,
                layout="main-horizontal",
                panes=[
                    Pane(run=_monitor_command(config)),
                    Pane(shell=_interactive_shell(), focus=True),
                ],
            )
        ],
    )


def _attach_client(config: AgentConsoleConfig) -> int:
    """Attach or switch the current tmux client to the configured session."""
    if config.detached:
        return 0

    cmd = ["tmux", *_socket_args(config)]
    if os.environ.get("TMUX"):
        cmd.extend(("switch-client", "-t", config.session_name))
    else:
        cmd.extend(("attach-session", "-t", config.session_name))
    try:
        return subprocess.run(cmd, check=False).returncode
    except FileNotFoundError:
        print("tmux not found", file=sys.stderr)
        return 127


def start(config: AgentConsoleConfig) -> ConsoleResult:
    """Create the console session if needed, then attach or switch to it.

    Examples
    --------
    >>> import inspect
    >>> "config" in inspect.signature(start).parameters
    True
    """
    state_path = config.resolved_state_path
    server = _server(config)
    created = False
    if not server.has_session(config.session_name):
        workspace = build_console_workspace(config)
        result = workspace.build(
            SubprocessEngine.for_server(server),
            preflight=False,
        )
        if not result.ok:
            stderr = "\n".join(
                line
                for command_result in result.results
                for line in command_result.stderr
            )
            msg = stderr or f"failed to build {config.session_name!r}"
            raise RuntimeError(msg)
        created = True

    returncode = _attach_client(config)
    return ConsoleResult(
        created=created,
        session_name=config.session_name,
        state_path=state_path,
        attached=not config.detached and returncode == 0,
        returncode=returncode,
    )


def attach(config: AgentConsoleConfig) -> ConsoleResult:
    """Attach or switch to an already-running console session.

    Examples
    --------
    >>> import inspect
    >>> "config" in inspect.signature(attach).parameters
    True
    """
    state_path = config.resolved_state_path
    server = _server(config)
    if not server.has_session(config.session_name):
        print(
            f"agent console {config.session_name!r} is not running; "
            "run `python -m libtmux.agents start` first",
            file=sys.stderr,
        )
        return ConsoleResult(False, config.session_name, state_path, False, 1)

    returncode = _attach_client(config)
    return ConsoleResult(
        created=False,
        session_name=config.session_name,
        state_path=state_path,
        attached=not config.detached and returncode == 0,
        returncode=returncode,
    )


def _store_from_path(path: pathlib.Path) -> AgentStore:
    """Load an :class:`AgentStore` from *path*, returning empty when absent."""
    data = JsonFile(path).load()
    return AgentStore.from_dict(data) if data else AgentStore()


def _agent_payload(agent: Agent) -> dict[str, t.Any]:
    """Serialize one agent for JSON output."""
    return dataclasses.asdict(agent) | {"state": agent.state.value}


def _sorted_agents(store: AgentStore) -> list[Agent]:
    """Return store agents in stable pane-id order."""
    return sorted(store.agents.values(), key=lambda agent: agent.pane_id)


def status(config: AgentConsoleConfig) -> int:
    """Print the persisted agent snapshot without contacting tmux.

    Examples
    --------
    >>> import inspect
    >>> "config" in inspect.signature(status).parameters
    True
    """
    store = _store_from_path(config.resolved_state_path)
    agents = _sorted_agents(store)
    if config.json:
        print(json.dumps([_agent_payload(agent) for agent in agents]))
        return 0
    if not agents:
        print("no agents")
        return 0
    print(f"{'pane':<8} {'state':<14} {'agent':<12} {'alive':<5} source")
    for agent in agents:
        name = agent.name or "-"
        alive = "yes" if agent.alive else "no"
        print(
            f"{agent.pane_id:<8} {agent.state.value:<14} "
            f"{name:<12} {alive:<5} {agent.source}"
        )
    return 0


def _render_dashboard(monitor: AgentMonitor) -> str:
    """Render a full-screen monitor dashboard from the current store."""
    store = AgentStore(
        agents={agent.pane_id: agent for agent in monitor.agents},
        stamps={},
    )
    return HudRenderer().render(store)


async def _redraw_monitor(
    engine: AsyncControlModeEngine,
    monitor: AgentMonitor,
    config: AgentConsoleConfig,
) -> None:
    """Paint stdout and the session status line from the monitor snapshot."""
    print("\033[H\033[J", end="")
    print(_render_dashboard(monitor), flush=True)
    if config.status_line:
        with contextlib.suppress(Exception):
            await paint_status_line(
                engine,
                monitor,
                target=NameRef(config.session_name, exact=True),
            )


async def run_monitor(config: AgentConsoleConfig) -> int:
    """Run the long-lived monitor loop inside the console session.

    Examples
    --------
    >>> import inspect
    >>> "config" in inspect.signature(run_monitor).parameters
    True
    """
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for item in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(item, stop.set)

    server = _server(config)
    async with AsyncControlModeEngine.for_server(server) as engine:
        monitor = AgentMonitor(
            engine,
            sink=JsonFile(config.resolved_state_path),
            hud=config.hud,
        )

        redraws: set[asyncio.Task[None]] = set()

        def changed(_: t.Any) -> None:
            task = loop.create_task(_redraw_monitor(engine, monitor, config))
            redraws.add(task)
            task.add_done_callback(redraws.discard)

        monitor.add_transition_observer(changed)
        await monitor.start()
        await _redraw_monitor(engine, monitor, config)
        try:
            await stop.wait()
        finally:
            await monitor.stop()
    return 0


def _parse_states(raw: str) -> tuple[AgentState, ...]:
    """Parse a comma-separated state list."""
    return tuple(
        AgentState.from_signal(part)
        for part in (item.strip() for item in raw.split(","))
        if part
    )


async def _wait_command(args: argparse.Namespace, config: AgentConsoleConfig) -> int:
    """Run the ``wait`` command."""
    async with AsyncControlModeEngine.for_server(_server(config)) as engine:
        monitor = AgentMonitor(engine, sink=JsonFile(config.resolved_state_path))
        await monitor.start()
        try:
            outcome = await wait_for_agent_state(
                monitor,
                args.pane_id,
                _parse_states(args.state),
                timeout=args.timeout,
            )
        finally:
            await monitor.stop()
    if args.json:
        print(
            json.dumps(
                {
                    "pane_id": outcome.pane_id,
                    "reason": outcome.reason.value,
                    "state": outcome.agent.state.value if outcome.agent else None,
                }
            )
        )
    else:
        state = outcome.agent.state.value if outcome.agent else "-"
        print(f"{outcome.pane_id} {outcome.reason.value} {state}")
    return 0 if outcome.reached else 1


async def _send_command(args: argparse.Namespace, config: AgentConsoleConfig) -> int:
    """Run the ``send`` command."""
    text = " ".join(args.text)
    async with AsyncControlModeEngine.for_server(_server(config)) as engine:
        monitor = AgentMonitor(engine, sink=JsonFile(config.resolved_state_path))
        await monitor.start()
        try:
            outcome = await send_to_agent(
                monitor,
                args.pane_id,
                text,
                wait_ready=not args.no_wait,
                timeout=args.timeout,
            )
        finally:
            await monitor.stop()
    wait = outcome.wait
    if args.json:
        print(
            json.dumps(
                {
                    "pane_id": outcome.pane_id,
                    "sent": outcome.sent,
                    "deduplicated": outcome.deduplicated,
                    "wait": wait.reason.value if wait is not None else None,
                }
            )
        )
    else:
        print(f"{outcome.pane_id} sent={str(outcome.sent).lower()}")
    return 0 if outcome.sent else 1


def _selected_hooks(target: str) -> list[t.Any]:
    """Return the hook installers selected by *target*."""
    hooks = hook_registry.registry()
    if target == "all":
        return hooks
    selected = [hook for hook in hooks if hook.name == target]
    if selected:
        return selected
    print(f"unknown hook target {target!r}", file=sys.stderr)
    return []


def _hooks_command(args: argparse.Namespace) -> int:
    """Run the ``hooks`` subcommand."""
    target = args.target or "all"
    hooks = _selected_hooks(target)
    if not hooks:
        return 1

    if args.hooks_action == "status":
        print(f"{'hook':<12} {'status':<10} detected")
        for hook in hooks:
            detected = "yes" if hook.detect() else "no"
            print(f"{hook.name:<12} {hook.status():<10} {detected}")
        return 0

    for hook in hooks:
        hook.install()
        print(f"installed {hook.name}")
    return 0


def _add_common(parser: argparse.ArgumentParser, *, suppress: bool = False) -> None:
    """Add shared tmux connection options to *parser*."""
    default: t.Any = argparse.SUPPRESS if suppress else None
    parser.add_argument("-L", "--socket-name", default=default)
    parser.add_argument("-S", "--socket-path", default=default)
    parser.add_argument(
        "-s",
        "--session-name",
        default=argparse.SUPPRESS if suppress else DEFAULT_SESSION_NAME,
    )
    parser.add_argument(
        "--state-path",
        type=pathlib.Path,
        default=default,
    )


def _add_detach(parser: argparse.ArgumentParser, *, suppress: bool = False) -> None:
    """Add attach-control flags to *parser*."""
    parser.add_argument(
        "-d",
        "--detached",
        action="store_true",
        default=argparse.SUPPRESS if suppress else False,
        help="create/check the session without attaching the current client",
    )


def _add_monitor_flags(
    parser: argparse.ArgumentParser,
    *,
    suppress: bool = False,
) -> None:
    """Add monitor display flags to *parser*."""
    parser.add_argument(
        "--hud",
        action="store_true",
        default=argparse.SUPPRESS if suppress else False,
        help="show a floating agent HUD when tmux supports it",
    )
    parser.add_argument(
        "--no-status-line",
        action="store_false",
        dest="status_line",
        default=argparse.SUPPRESS if suppress else True,
        help="do not paint the managed session status line",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser.

    Examples
    --------
    >>> _build_parser().prog
    'python -m libtmux.agents'
    """
    parser = argparse.ArgumentParser(
        prog="python -m libtmux.agents",
        description="Boot, attach, and inspect the libtmux agent console.",
    )
    _add_common(parser)
    _add_detach(parser)
    _add_monitor_flags(parser)
    subcommands = parser.add_subparsers(dest="command")

    start_parser = subcommands.add_parser(
        "start",
        help="create the console session if needed, then attach",
    )
    _add_common(start_parser, suppress=True)
    _add_detach(start_parser, suppress=True)
    _add_monitor_flags(start_parser, suppress=True)
    start_parser.set_defaults(command="start")

    attach_parser = subcommands.add_parser(
        "attach",
        aliases=["att"],
        help="attach to an already-running console",
    )
    _add_common(attach_parser, suppress=True)
    _add_detach(attach_parser, suppress=True)
    attach_parser.set_defaults(command="attach")

    monitor_parser = subcommands.add_parser(
        "monitor",
        help="run the long-lived monitor pane",
    )
    _add_common(monitor_parser, suppress=True)
    _add_monitor_flags(monitor_parser, suppress=True)
    monitor_parser.set_defaults(command="monitor")

    status_parser = subcommands.add_parser(
        "status",
        aliases=["list"],
        help="print the persisted agent snapshot without tmux calls",
    )
    _add_common(status_parser, suppress=True)
    status_parser.add_argument("--json", action="store_true", default=False)
    status_parser.set_defaults(command="status")

    hooks_parser = subcommands.add_parser("hooks", help="manage agent hooks")
    hooks_subcommands = hooks_parser.add_subparsers(dest="hooks_action", required=True)
    hooks_status = hooks_subcommands.add_parser("status", help="show hook status")
    hooks_status.add_argument("target", nargs="?", default="all")
    hooks_status.set_defaults(command="hooks")
    hooks_install = hooks_subcommands.add_parser("install", help="install hooks")
    hooks_install.add_argument("target", nargs="?", default="all")
    hooks_install.set_defaults(command="hooks")

    wait_parser = subcommands.add_parser(
        "wait",
        help="wait until a pane's agent reaches a state",
    )
    _add_common(wait_parser, suppress=True)
    wait_parser.add_argument("pane_id")
    wait_parser.add_argument("--state", default="awaiting_input,done,idle")
    wait_parser.add_argument("--timeout", type=float, default=None)
    wait_parser.add_argument("--json", action="store_true", default=False)
    wait_parser.set_defaults(command="wait")

    send_parser = subcommands.add_parser(
        "send",
        help="send text to an agent pane when it is ready",
    )
    _add_common(send_parser, suppress=True)
    send_parser.add_argument("pane_id")
    send_parser.add_argument("text", nargs=argparse.REMAINDER)
    send_parser.add_argument("--timeout", type=float, default=None)
    send_parser.add_argument("--no-wait", action="store_true", default=False)
    send_parser.add_argument("--json", action="store_true", default=False)
    send_parser.set_defaults(command="send")

    help_parser = subcommands.add_parser("help", help="show command help")
    help_parser.add_argument("topic", nargs="?")
    help_parser.set_defaults(command="help")
    return parser


def _fill_defaults(args: argparse.Namespace) -> argparse.Namespace:
    """Backfill shared defaults suppressed by nested parsers."""
    defaults: dict[str, t.Any] = {
        "command": "start",
        "socket_name": None,
        "socket_path": None,
        "session_name": DEFAULT_SESSION_NAME,
        "state_path": None,
        "detached": False,
        "hud": False,
        "status_line": True,
        "json": False,
    }
    for key, value in defaults.items():
        if not hasattr(args, key) or (getattr(args, key) is None and key == "command"):
            setattr(args, key, value)
    return args


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI args, defaulting an absent subcommand to ``start``.

    Examples
    --------
    >>> parse_args([]).command
    'start'
    >>> parse_args(["att", "--detached"]).command
    'attach'
    """
    parser = _build_parser()
    items = sys.argv[1:] if argv is None else list(argv)
    args = parser.parse_args(items)
    return _fill_defaults(args)


def _config_from_args(args: argparse.Namespace) -> AgentConsoleConfig:
    """Build :class:`AgentConsoleConfig` from argparse output."""
    return AgentConsoleConfig(
        session_name=args.session_name,
        socket_name=args.socket_name,
        socket_path=args.socket_path,
        state_path=args.state_path,
        detached=args.detached,
        json=args.json,
        hud=args.hud,
        status_line=args.status_line,
    )


def _print_command_help(parser: argparse.ArgumentParser, topic: str | None) -> int:
    """Print top-level or subcommand help."""
    if topic is None:
        parser.print_help()
        return 0
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            command = action.choices.get(topic)
            if command is not None:
                command.print_help()
                return 0
    print(f"unknown help topic {topic!r}", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``libtmux.agents`` command.

    Examples
    --------
    >>> callable(main)
    True
    """
    parser = _build_parser()
    items = sys.argv[1:] if argv is None else list(argv)
    args = _fill_defaults(parser.parse_args(items))

    if args.command == "help":
        return _print_command_help(parser, args.topic)

    config = _config_from_args(args)
    if args.command == "start":
        return start(config).returncode
    if args.command == "attach":
        return attach(config).returncode
    if args.command == "monitor":
        return asyncio.run(run_monitor(config))
    if args.command == "status":
        return status(config)
    if args.command == "hooks":
        return _hooks_command(args)
    if args.command == "wait":
        return asyncio.run(_wait_command(args, config))
    if args.command == "send":
        if not args.text:
            print("send requires text", file=sys.stderr)
            return 2
        return asyncio.run(_send_command(args, config))

    parser.error(f"unknown command {args.command!r}")
    return 2
