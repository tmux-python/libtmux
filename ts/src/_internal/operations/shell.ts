import { runCommand } from "./command.js";
import type { RuntimeContext } from "../runtime/context.js";

export interface RunShellOptions {
  /** Pane the command's `#{pane_*}` formats resolve against. */
  readonly target?: string | null;
}

/** Run a shell command through tmux and return whatever it printed. */
export async function runShell(
  runtime: RuntimeContext,
  command: string,
  options: RunShellOptions = {},
): Promise<readonly string[]> {
  return runCommand(runtime, [
    "run-shell",
    ...(options.target == null ? [] : ["-t", options.target]),
    command,
  ]);
}

export interface IfShellOptions {
  /** Command to run when the condition fails. */
  readonly otherwise?: string;
  /** Treat the condition as a tmux format rather than a shell command. */
  readonly format?: boolean;
  readonly target?: string | null;
}

/**
 * Run one command or another depending on a condition.
 *
 * `-b` is deliberately not passed: a backgrounded `if-shell` returns before the
 * branch has run, which would make the resolved promise mean nothing.
 */
export async function ifShell(
  runtime: RuntimeContext,
  condition: string,
  command: string,
  options: IfShellOptions = {},
): Promise<void> {
  await runCommand(runtime, [
    "if-shell",
    ...(options.format === true ? ["-F"] : []),
    ...(options.target == null ? [] : ["-t", options.target]),
    condition,
    command,
    ...(options.otherwise === undefined ? [] : [options.otherwise]),
  ]);
}

/** Expand a tmux format string against a target and return the result. */
export async function displayMessage(
  runtime: RuntimeContext,
  message: string,
  target: string | null,
): Promise<readonly string[]> {
  return runCommand(runtime, [
    "display-message",
    "-p",
    ...(target == null ? [] : ["-t", target]),
    message,
  ]);
}

export interface RespawnOptions {
  /** Replace a pane that is still running rather than only a dead one. */
  readonly kill?: boolean;
  readonly startDirectory?: string;
}

/** Restart a pane's command in place. */
export async function respawnPane(
  runtime: RuntimeContext,
  paneId: string | null,
  command: string | undefined,
  options: RespawnOptions = {},
): Promise<void> {
  await runCommand(runtime, [
    "respawn-pane",
    ...(options.kill === true ? ["-k"] : []),
    ...(options.startDirectory === undefined ? [] : ["-c", options.startDirectory]),
    ...(paneId == null ? [] : ["-t", paneId]),
    ...(command === undefined ? [] : [command]),
  ]);
}

/** Move a pane out into a window of its own. */
export async function breakPane(
  runtime: RuntimeContext,
  paneId: string | null,
  windowName: string | undefined,
): Promise<void> {
  await runCommand(runtime, [
    "break-pane",
    "-d",
    ...(paneId == null ? [] : ["-s", paneId]),
    ...(windowName === undefined ? [] : ["-n", windowName]),
  ]);
}

/** Move a pane into another window, joining it as a split. */
export async function joinPane(
  runtime: RuntimeContext,
  paneId: string | null,
  target: string,
  options: { readonly vertical?: boolean } = {},
): Promise<void> {
  await runCommand(runtime, [
    "join-pane",
    "-d",
    ...(options.vertical === false ? ["-h"] : []),
    ...(paneId == null ? [] : ["-s", paneId]),
    "-t",
    target,
  ]);
}

/**
 * Enter or leave a pane's mode.
 *
 * Leaving is idempotent; entering is not. Any failure other than "already not
 * in a mode" still propagates.
 */
export async function setCopyMode(
  runtime: RuntimeContext,
  paneId: string | null,
  active: boolean,
): Promise<void> {
  const target = paneId == null ? [] : ["-t", paneId];
  if (active) {
    await runCommand(runtime, ["copy-mode", ...target]);
    return;
  }
  try {
    await runCommand(runtime, ["send-keys", ...target, "-X", "cancel"]);
  } catch (error) {
    // tmux rejects `cancel` on a pane that is not in a mode, but "make sure
    // this pane is not in a mode" is the caller's intent, and failing an
    // already-satisfied condition would push a pre-check into every call site.
    if (!String(error).includes("not in a mode")) throw error;
  }
}

/** Detach every client attached to a target, or one named client. */
export async function detachClient(runtime: RuntimeContext, target: string | null): Promise<void> {
  await runCommand(runtime, ["detach-client", ...(target == null ? [] : ["-t", target])]);
}

/** Point a client at a different session. */
export async function switchClient(
  runtime: RuntimeContext,
  clientName: string | null,
  sessionId: string,
): Promise<void> {
  await runCommand(runtime, [
    "switch-client",
    ...(clientName == null ? [] : ["-c", clientName]),
    "-t",
    sessionId,
  ]);
}
