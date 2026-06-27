"""Recipe prompts for the engine-ops MCP server.

Each function is a FastMCP prompt -- a template returning the text an MCP client
sends to its model, packaging a few common workflows over the engine-ops
vocabulary (``send_input`` / ``wait_for_output`` / ``capture_pane`` /
``create_session`` / ``split_pane``). Pure string builders, engine-agnostic, so
the same set registers on both the sync and async servers.
"""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


def run_and_wait(command: str, pane_id: str, timeout: float = 60.0) -> str:
    """Run a shell command in a pane and wait for it to settle."""
    return f"""Run this shell command in tmux pane {pane_id}, then wait for the
pane to settle and inspect the result:

1. send_input(target={pane_id!r}, keys={command!r}, enter=True)
2. wait_for_output(pane={pane_id!r}, timeout={timeout}) -- folds the live output
   and returns when the pane goes quiet (needle-free: no regex, no sentinel).
3. Read done.pane_dead / done.pane_dead_status (exit code) and captured_text.
   "Settled" means output stopped, not that the command succeeded -- check the
   done metadata for the exit status.

Prefer this over a send_input + capture_pane retry loop: wait_for_output is
event-backed and reports the process exit."""


def diagnose_failing_pane(pane_id: str) -> str:
    """Gather pane context and propose a root-cause hypothesis."""
    return f"""Something went wrong in tmux pane {pane_id}. Diagnose it:

1. capture_pane(target={pane_id!r}) to read the scrollback (the active prompt and
   most recent output are at the bottom).
2. If the pane is still producing output, wait_for_output(pane={pane_id!r}) until
   it settles, then capture again.
3. Identify the last command that ran (the prompt line and the line above it) and
   the last non-empty output line.
4. Propose a root-cause hypothesis and a minimal command to verify it -- produce
   the plan first; do NOT execute anything yet."""


def build_dev_workspace(session_name: str, log_command: str = "watch -n 1 date") -> str:
    """Construct a simple 3-pane development session."""
    return f"""Set up a 3-pane development workspace named {session_name!r}
(editor on top, a shell bottom-left, a logs tail bottom-right):

1. create_session(name={session_name!r}) -- creates the session with one pane
   (the editor). Capture its first_pane_id as %A.
2. split_pane(target="%A") -- splits off the bottom half (the terminal, %B).
3. split_pane(target="%B", horizontal=True) -- splits %B (the logs pane, %C).
4. send_input(target="%A", keys="vim", enter=True) and
   send_input(target="%C", keys={log_command!r}, enter=True). Leave %B at its
   fresh shell prompt. No pre-launch wait is required -- tmux buffers keystrokes
   into the PTY whether or not the shell has finished drawing.

Use pane ids (%N) for all targeting -- they are stable across layout changes;
window renames are not."""


def interrupt_gracefully(pane_id: str) -> str:
    r"""Interrupt a running command and verify the prompt returned."""
    return rf"""Interrupt whatever is running in pane {pane_id} and verify that
control returns to the shell:

1. send_input(target={pane_id!r}, keys="C-c", enter=False) -- tmux interprets
   C-c as SIGINT.
2. wait_for_output(pane={pane_id!r}, timeout=5.0) -- wait for the pane to settle
   back at a shell prompt.
3. If it does not settle, the process is ignoring SIGINT. Stop and ask the caller
   how to proceed -- do NOT escalate automatically to C-\ (SIGQUIT) or kill."""


def register_prompts(mcp: FastMCP) -> None:
    """Register the recipe prompts on *mcp*."""
    from fastmcp.prompts import Prompt

    for fn in (
        run_and_wait,
        diagnose_failing_pane,
        build_dev_workspace,
        interrupt_gracefully,
    ):
        mcp.add_prompt(Prompt.from_function(fn, name=fn.__name__))
