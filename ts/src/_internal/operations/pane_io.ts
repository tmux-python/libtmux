import type { CaptureOptions, SendKeysOptions } from "../../types.js";
import type { RuntimeContext } from "../runtime/context.js";
import { runCommand } from "./command.js";

/**
 * Send keys to a pane.
 *
 * Enter is a separate `send-keys` rather than a newline appended to the string,
 * because `-l` would send a literal newline character while an unquoted `Enter`
 * is a key name tmux resolves. Keeping them separate makes `literal` mean only
 * what it says about the caller's own text.
 */
export async function sendKeys(
  runtime: RuntimeContext,
  paneId: string | null,
  keys: string,
  options: SendKeysOptions = {},
): Promise<void> {
  const target = paneId == null ? [] : ["-t", paneId];
  await runCommand(runtime, [
    "send-keys",
    ...target,
    ...(options.literal === true ? ["-l"] : []),
    keys,
  ]);
  if (options.enter !== false) await runCommand(runtime, ["send-keys", ...target, "Enter"]);
}

/** Capture a pane's contents as lines, without the trailing blank line tmux emits. */
export async function capturePane(
  runtime: RuntimeContext,
  paneId: string | null,
  options: CaptureOptions = {},
): Promise<readonly string[]> {
  return runCommand(runtime, [
    "capture-pane",
    "-p",
    ...(paneId == null ? [] : ["-t", paneId]),
    ...(options.joinWrapped === true ? ["-J"] : []),
    ...(options.start === undefined ? [] : ["-S", String(options.start)]),
    ...(options.end === undefined ? [] : ["-E", String(options.end)]),
  ]);
}

/** Discard a pane's scrollback history. */
export async function clearHistory(runtime: RuntimeContext, paneId: string | null): Promise<void> {
  await runCommand(runtime, ["clear-history", ...(paneId == null ? [] : ["-t", paneId])]);
}
