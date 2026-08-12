import { runCommand } from "./command.js";
import type { RuntimeContext } from "../runtime/context.js";

export async function renameSession(
  runtime: RuntimeContext,
  sessionId: string | null,
  name: string,
): Promise<void> {
  await runCommand(runtime, [
    "rename-session",
    ...(sessionId == null ? [] : ["-t", sessionId]),
    name,
  ]);
}

/**
 * Select a window within a session.
 *
 * tmux spells relative movement as separate subcommands rather than targets, so
 * the three directions map to `last-window`, `next-window`, and
 * `previous-window`; anything else is treated as a window target.
 */

export async function selectWindowIn(
  runtime: RuntimeContext,
  sessionId: string | null,
  target: string,
): Promise<void> {
  const scope = sessionId == null ? [] : ["-t", sessionId];
  if (target === "last") return void (await runCommand(runtime, ["last-window", ...scope]));
  if (target === "next") return void (await runCommand(runtime, ["next-window", ...scope]));
  if (target === "previous") {
    return void (await runCommand(runtime, ["previous-window", ...scope]));
  }
  const qualified = sessionId == null ? target : `${sessionId}:${target}`;
  await runCommand(runtime, ["select-window", "-t", qualified]);
}
