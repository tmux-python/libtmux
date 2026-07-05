"""Command-line entry to launch a tmuxp-style workspace file.

Run with::

    uv run python -m libtmux.experimental.workspace.cli load <yaml-file>

A thin shell over the declarative tier: it resolves a workspace file (path,
directory, or a name under the workspace dir), expands ``~`` / ``$VAR`` / ``./``
paths relative to the file's directory (the part :func:`~.analyzer.analyze`
deliberately leaves to a caller with a cwd), analyzes it into a
:class:`~.ir.Workspace`, builds it over a :class:`~..engines.SubprocessEngine`,
and -- unless ``-d`` -- attaches (or switches the client when already inside
tmux), mirroring ``tmuxp load``.

Everything here is experimental and outside the versioning policy.
"""

from __future__ import annotations

import argparse
import collections.abc
import os
import pathlib
import sys
import typing as t

from libtmux.experimental.workspace.analyzer import analyze

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import (
        CommandRequest,
        CommandResult,
        TmuxEngine,
    )
    from libtmux.experimental.ops.plan import PlanResult, StepReport
    from libtmux.experimental.workspace.ir import Workspace

#: Filenames searched when a directory is given (tmuxp's convention).
_WORKSPACE_FILENAMES = (".tmuxp.yaml", ".tmuxp.yml", ".tmuxp.json")
#: Extensions tried when a bare name is given (resolved under the workspace dir).
_WORKSPACE_EXTENSIONS = ("yaml", "yml", "json")


def _workspace_dir() -> pathlib.Path:
    """Return the directory bare workspace names resolve against (``~/.tmuxp``)."""
    return pathlib.Path(
        os.environ.get("TMUXP_WORKSPACEDIR", "~/.tmuxp"),
    ).expanduser()


def _find_workspace_file(arg: str) -> pathlib.Path:
    """Resolve *arg* to a concrete workspace file.

    A path to a file is used as-is; a directory is searched for
    ``.tmuxp.{yaml,yml,json}``; a bare name (no directory, no extension) is
    resolved against the workspace dir (``$TMUXP_WORKSPACEDIR`` or ``~/.tmuxp``).
    """
    path = pathlib.Path(arg).expanduser()
    if path.is_file():
        return path
    if path.is_dir():
        for name in _WORKSPACE_FILENAMES:
            candidate = path / name
            if candidate.is_file():
                return candidate
        msg = f"no .tmuxp.{{yaml,yml,json}} found in {path}"
        raise FileNotFoundError(msg)
    if os.sep not in arg and "." not in pathlib.Path(arg).name:
        workspace_dir = _workspace_dir()
        for ext in _WORKSPACE_EXTENSIONS:
            candidate = workspace_dir / f"{arg}.{ext}"
            if candidate.is_file():
                return candidate
    msg = f"workspace file not found: {arg}"
    raise FileNotFoundError(msg)


def _expandshell(value: str, cwd: str | os.PathLike[str]) -> str:
    """Expand ``~`` and ``$VAR``; resolve a ``./``-relative path against *cwd*.

    Mirrors tmuxp's ``expandshell`` + relative-path rule: only ``.``-prefixed
    paths are joined to *cwd* (a bare relative path is left for tmux to resolve
    against the pane's directory).

    Examples
    --------
    >>> _expandshell("/abs/path", "/tmp")
    '/abs/path'
    >>> _expandshell("./src", "/home/me/proj")
    '/home/me/proj/src'
    >>> _expandshell("../sibling", "/home/me/proj")
    '/home/me/sibling'
    """
    raw = os.path.expandvars(value)
    if raw in {".", ".."} or raw.startswith(("./", "../")):
        # Check the relative prefix on the raw value -- Path() would collapse the
        # leading "./" before we could test for it.
        return os.path.normpath(pathlib.Path(cwd) / raw)
    return str(pathlib.Path(raw).expanduser())


def _expand_env(
    environment: collections.abc.Mapping[str, t.Any],
) -> dict[str, str]:
    """Expand ``$VAR`` in environment *values* (values, not paths)."""
    return {key: os.path.expandvars(str(value)) for key, value in environment.items()}


def _expand_pane(pane: t.Any, cwd: str | os.PathLike[str]) -> t.Any:
    """Expand a pane's ``start_directory`` (mappings only; strings pass through)."""
    if isinstance(pane, collections.abc.Mapping) and pane.get("start_directory"):
        expanded = dict(pane)
        expanded["start_directory"] = _expandshell(pane["start_directory"], cwd)
        return expanded
    return pane


def _expand_window(
    window: collections.abc.Mapping[str, t.Any],
    cwd: str | os.PathLike[str],
) -> dict[str, t.Any]:
    """Expand a window's ``start_directory`` / ``environment`` and its panes."""
    expanded = dict(window)
    if window.get("start_directory"):
        expanded["start_directory"] = _expandshell(window["start_directory"], cwd)
    if window.get("environment"):
        expanded["environment"] = _expand_env(window["environment"])
    panes = window.get("panes")
    if panes:
        expanded["panes"] = [_expand_pane(pane, cwd) for pane in panes]
    return expanded


def _expand_workspace(
    raw: collections.abc.Mapping[str, t.Any],
    cwd: str | os.PathLike[str],
) -> dict[str, t.Any]:
    """Expand path/var-bearing fields relative to the workspace file's *cwd*.

    The analyzer is intentionally pure (no cwd), so this CLI does the
    expansion ``tmuxp load`` does: ``start_directory`` (session/window/pane),
    ``before_script``, and ``environment`` values.
    """
    expanded = dict(raw)
    if raw.get("start_directory"):
        expanded["start_directory"] = _expandshell(raw["start_directory"], cwd)
    if raw.get("before_script"):
        expanded["before_script"] = _expandshell(raw["before_script"], cwd)
    if raw.get("environment"):
        expanded["environment"] = _expand_env(raw["environment"])
    expanded["windows"] = [
        _expand_window(window, cwd) for window in raw.get("windows", []) or []
    ]
    return expanded


def _read_workspace(path: pathlib.Path) -> dict[str, t.Any]:
    """Parse a YAML/JSON workspace file into a mapping (YAML parses JSON too)."""
    import yaml  # type: ignore[import-untyped]

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, collections.abc.Mapping):
        msg = f"workspace file {path} must contain a mapping"
        raise TypeError(msg)
    return dict(data)


def _attach(session: t.Any, *, detached: bool) -> None:
    """Attach the session, or switch the client when already inside tmux."""
    if detached:
        return
    if "TMUX" in os.environ:
        session.switch_client()
    else:
        session.attach()


class _RecordingEngine:
    """Wrap an engine, capturing every dispatched argv for the dry run.

    Each recorded entry is one tmux dispatch -- a folded ``;`` chain renders as a
    single argv with bare ``;`` separators, exactly as the real build sends it.
    """

    def __init__(self, inner: TmuxEngine) -> None:
        self.inner = inner
        self.calls: list[tuple[str, ...]] = []

    def run(self, request: CommandRequest) -> CommandResult:
        """Record the argv, then forward to the wrapped engine."""
        self.calls.append(request.args)
        return self.inner.run(request)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Forward each request in order, recording as it goes."""
        return [self.run(req) for req in requests]


def _print_dry_run(
    workspace: Workspace,
    *,
    socket_name: str | None,
    socket_path: str | None,
    fold: bool = True,
) -> None:
    r"""Print the tmux commands a build would run, without touching tmux.

    The plan is resolved against the in-memory ``MockEngine`` (which
    fabricates ids) through the *same* planner the real build uses, so the
    printed lines are the folded ``;`` dispatches that would actually run -- not
    an unfolded op-per-line view. Pass ``fold=False`` for one tmux call per
    operation. Host steps (sleep / before_script / pane-readiness) print as
    comments in execution order, and a standalone ``;`` renders as ``\;`` so a
    line stays copy-pasteable into a shell.
    """
    import shlex

    from libtmux.experimental.engines import MockEngine
    from libtmux.experimental.ops import (
        BoundedPlanner,
        MarkedPlanner,
        SequentialPlanner,
    )
    from libtmux.experimental.workspace.compiler import HostStep, compile_full

    compiled = compile_full(workspace)
    prefix: list[str] = ["tmux"]
    if socket_name:
        prefix += ["-L", socket_name]
    if socket_path:
        prefix += ["-S", socket_path]

    planner = (
        BoundedPlanner(MarkedPlanner(), frozenset(compiled.host_after))
        if fold
        else SequentialPlanner()
    )
    engine = _RecordingEngine(MockEngine())
    hosts_per_dispatch: list[tuple[HostStep, ...]] = []

    def on_step(report: StepReport) -> None:
        steps: list[HostStep] = []
        for index in report.step.indices:
            steps.extend(compiled.host_after.get(index, ()))
        hosts_per_dispatch.append(tuple(steps))

    compiled.plan.execute(engine, planner=planner, on_step=on_step)

    def _emit_host(step: HostStep) -> None:
        if step.kind == "sleep":
            print(f"# sleep {step.seconds}")
        elif step.kind == "script":
            where = f" (cwd {step.cwd})" if step.cwd else ""
            print(f"# before_script{where}: {step.command}")
        elif step.kind == "wait_pane":
            print("# wait for the pane's shell to be ready")

    def _render(argv: tuple[str, ...]) -> str:
        return " ".join(
            "\\;" if token == ";" else shlex.quote(token) for token in (*prefix, *argv)
        )

    shape = "folded" if fold else "sequential"
    print(
        f"# build plan for session {workspace.name!r} "
        f"({len(engine.calls)} dispatches, {shape}, ids fabricated)",
    )
    for step in compiled.pre:
        _emit_host(step)
    for argv, hosts in zip(engine.calls, hosts_per_dispatch, strict=True):
        print(_render(argv))
        for step in hosts:
            _emit_host(step)


def load(
    workspace_file: str,
    *,
    socket_name: str | None = None,
    socket_path: str | None = None,
    new_session_name: str | None = None,
    detached: bool = False,
    dry_run: bool = False,
    fold: bool = True,
) -> PlanResult | None:
    """Build (and unless *detached*, attach) a workspace file.

    Resolves *workspace_file*, expands its paths, analyzes it, and builds it over
    a subprocess engine bound to a :class:`libtmux.Server` on the given socket. An
    already-running session of the same name is attached rather than rebuilt
    (unless the file's ``on_exists`` opts into ``replace``/``reuse``). With
    *dry_run*, the tmux commands are printed and nothing is executed.

    The build folds tmux dispatches by default (``fold=True``); ``fold=False``
    issues one tmux call per operation, for both the dry run and the real build.

    Returns
    -------
    PlanResult or None
        The build outcome, or ``None`` when an existing session was attached or a
        dry run was requested.
    """
    path = _find_workspace_file(workspace_file)
    raw = _expand_workspace(_read_workspace(path), cwd=path.parent)
    if new_session_name:
        raw["session_name"] = new_session_name
    workspace = analyze(raw)

    if dry_run:
        _print_dry_run(
            workspace,
            socket_name=socket_name,
            socket_path=socket_path,
            fold=fold,
        )
        return None

    import libtmux
    from libtmux.experimental.engines import SubprocessEngine
    from libtmux.experimental.ops import SequentialPlanner

    server = libtmux.Server(socket_name=socket_name, socket_path=socket_path)
    engine = SubprocessEngine.for_server(server)

    existed = server.has_session(workspace.name)
    result: PlanResult | None = None
    try:
        result = workspace.build(engine, planner=None if fold else SequentialPlanner())
    except FileExistsError:
        # on_exists="error" (the default) and the session is already running;
        # attach to it rather than failing, matching `tmuxp load`.
        existed = True

    session = server.sessions.get(session_name=workspace.name, default=None)
    if session is None:
        msg = f"session {workspace.name!r} was not found after build"
        raise RuntimeError(msg)

    verb = "attached existing" if (existed and result is None) else "built"
    windows = len(session.windows)
    panes = sum(len(window.panes) for window in session.windows)
    sys.stderr.write(
        f"✓ {verb} session {workspace.name!r} ({windows} windows, {panes} panes)\n",
    )
    _attach(session, detached=detached)
    return result


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the workspace CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m libtmux.experimental.workspace.cli",
        description="Build and attach an experimental libtmux workspace file.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    load_parser = sub.add_parser(
        "load",
        help="build (and attach) a tmuxp-style workspace file",
        description=(
            "Load a .tmuxp.{yaml,yml,json} workspace: a file path, a directory "
            "(searched for .tmuxp.*), or a bare name under "
            "$TMUXP_WORKSPACEDIR (default ~/.tmuxp)."
        ),
    )
    load_parser.add_argument(
        "workspace_file",
        metavar="workspace-file",
        help="path, directory, or name of a .tmuxp.{yaml,yml,json} file",
    )
    load_parser.add_argument(
        "-L",
        dest="socket_name",
        metavar="socket-name",
        help="tmux -L socket name",
    )
    load_parser.add_argument(
        "-S",
        dest="socket_path",
        metavar="socket-path",
        help="tmux -S socket path",
    )
    load_parser.add_argument(
        "-s",
        dest="new_session_name",
        metavar="session-name",
        help="override the workspace's session name",
    )
    load_parser.add_argument(
        "-d",
        "--detached",
        action="store_true",
        help="build the session without attaching",
    )
    load_parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="print the tmux commands that would run, without executing them",
    )
    load_parser.add_argument(
        "--no-fold",
        dest="fold",
        action="store_false",
        help="dispatch one tmux call per operation (no ; chaining)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the workspace CLI (the ``python -m ...workspace.cli`` entry).

    Requires a tmux binary on ``PATH``. ``load`` builds the workspace and, unless
    ``-d`` is given, attaches it (or switches the client when already inside
    tmux).
    """
    args = _build_parser().parse_args(argv)
    if args.command == "load":
        load(
            args.workspace_file,
            socket_name=args.socket_name,
            socket_path=args.socket_path,
            new_session_name=args.new_session_name,
            detached=args.detached,
            dry_run=args.dry_run,
            fold=args.fold,
        )


if __name__ == "__main__":
    main()
