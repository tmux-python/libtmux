"""Emit an agent-state signal from inside an agent's lifecycle hook.

Local (tmux reachable): write the ``@agent_state`` pane option. Remote (SSH):
write an ``OSC 3008`` escape to ``/dev/tty`` -- NOT stdout, which agent hooks
pipe/null -- so it reaches the pane pty and travels over SSH into tmux %output.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import typing as t

if t.TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def emit(
    state: str,
    *,
    name: str | None = None,
    runner: t.Callable[..., t.Any] = subprocess.run,
    tty_path: str = "/dev/tty",
    env: Mapping[str, str] | None = None,
) -> None:
    """Signal *state* for the current pane (local set-option, else remote OSC).

    Parameters
    ----------
    state : str
        Agent state string (e.g. ``"running"``, ``"idle"``).
    name : str or None
        Optional agent name to emit alongside the state.
    runner : callable
        Subprocess runner; injectable for tests. Default: ``subprocess.run``.
    tty_path : str
        Path to the controlling terminal for the remote OSC path.
        Default: ``"/dev/tty"``.
    env : Mapping[str, str] or None
        Environment mapping used to detect ``$TMUX`` / ``$TMUX_PANE``.
        Default: ``os.environ``.

    Examples
    --------
    >>> calls = []
    >>> emit("running", runner=lambda a, **k: calls.append(a),
    ...      env={"TMUX": "x", "TMUX_PANE": "%1"})
    >>> calls[0][:2]
    ['tmux', 'set-option']
    """
    environ = os.environ if env is None else env
    pane = environ.get("TMUX_PANE")
    if environ.get("TMUX") and pane:
        runner(
            ["tmux", "set-option", "-p", "-t", pane, "@agent_state", state],
            check=False,
        )
        if name:
            runner(
                ["tmux", "set-option", "-p", "-t", pane, "@agent_name", name],
                check=False,
            )
        return
    payload = f"state={state}"
    if name:
        payload += f";name={name}"
    escape = f"\033]3008;{payload}\033\\".encode()
    with pathlib.Path(tty_path).open("wb", buffering=0) as tty:
        tty.write(escape)


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point: ``libtmux-agent-emit <state> [--name NAME]``.

    Parameters
    ----------
    argv : Sequence[str] or None
        Argument list; defaults to ``sys.argv[1:]`` when ``None``.

    Returns
    -------
    int
        Exit code: ``0`` on success, ``2`` when no arguments are provided.

    Examples
    --------
    >>> from libtmux.experimental.agents.hooks.emit import main
    >>> main([])
    2

    The success path calls :func:`emit`, which opens ``/dev/tty`` or invokes
    ``tmux``; its coverage lives in
    ``tests/experimental/agents/hooks/test_emit.py``.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return 2
    state = args[0]
    name: str | None = None
    if "--name" in args:
        idx = args.index("--name")
        name = args[idx + 1] if idx + 1 < len(args) else None
    emit(state, name=name)
    return 0
