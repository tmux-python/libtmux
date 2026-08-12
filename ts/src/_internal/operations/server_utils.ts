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
