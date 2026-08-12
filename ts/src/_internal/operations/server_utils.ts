import { adaptRawResult, prepareCommandRequest } from "./request.js";
import { runCommand } from "./command.js";
import type { RuntimeContext } from "../runtime/context.js";

/**
 * Ask tmux whether a session exists.
 *
 * `has-session` reports absence with a nonzero exit rather than empty output,
 * so this deliberately bypasses the raising runner: "no such session" is an
 * answer, not a failure.
 */
export async function hasSession(runtime: RuntimeContext, name: string): Promise<boolean> {
  const result = adaptRawResult(
    await runtime.transport.execute(
      prepareCommandRequest(runtime.connection, ["has-session", "-t", name]),
    ),
  );
  return result.returncode === 0;
}

/** Run a tmux config file against the server. */
export async function sourceFile(runtime: RuntimeContext, path: string): Promise<void> {
  await runCommand(runtime, ["source-file", path]);
}

/** Every command name the running tmux understands. */
export async function listCommands(runtime: RuntimeContext): Promise<readonly string[]> {
  return runCommand(runtime, ["list-commands", "-F", "#{command_list_name}"]);
}

/** Store a named paste buffer. */
export async function setBuffer(
  runtime: RuntimeContext,
  name: string,
  data: string,
): Promise<void> {
  await runCommand(runtime, ["set-buffer", "-b", name, data]);
}

/** Read a named paste buffer's contents. */
export async function showBuffer(
  runtime: RuntimeContext,
  name: string,
): Promise<readonly string[]> {
  return runCommand(runtime, ["show-buffer", "-b", name]);
}

/** Every buffer name the server currently holds. */
export async function listBuffers(runtime: RuntimeContext): Promise<readonly string[]> {
  return runCommand(runtime, ["list-buffers", "-F", "#{buffer_name}"]);
}

/** Discard a named paste buffer. */
export async function deleteBuffer(runtime: RuntimeContext, name: string): Promise<void> {
  await runCommand(runtime, ["delete-buffer", "-b", name]);
}

/** Paste a buffer into a pane without appending a newline. */
export async function pasteBuffer(
  runtime: RuntimeContext,
  name: string,
  paneId: string | null,
): Promise<void> {
  await runCommand(runtime, [
    "paste-buffer",
    "-b",
    name,
    ...(paneId == null ? [] : ["-t", paneId]),
  ]);
}

/**
 * Whether the tmux server is reachable.
 *
 * A missing daemon, an absent socket, a permission error, and a missing tmux
 * binary all answer `false` rather than raising, because "is the server there?"
 * is a question with a negative answer, not a failure to ask it.
 */
export async function isAlive(runtime: RuntimeContext): Promise<boolean> {
  try {
    const result = adaptRawResult(
      await runtime.transport.execute(prepareCommandRequest(runtime.connection, ["list-sessions"])),
    );
    return result.returncode === 0;
  } catch {
    return false;
  }
}

/**
 * Assert the tmux server is reachable, raising with tmux's own reason if not.
 *
 * The list-shaped accessors are lenient: they return an empty selection when
 * tmux cannot be reached, so an empty result is indistinguishable from a server
 * that is gone. This is the explicit way to tell those apart.
 */
export async function raiseIfDead(runtime: RuntimeContext): Promise<void> {
  await runCommand(runtime, ["list-sessions"]);
}
