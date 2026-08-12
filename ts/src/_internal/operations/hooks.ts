import type { HookScope } from "../../types.js";
import { parseNameValueLine } from "./options.js";
import { runCommand } from "./command.js";
import type { RuntimeContext } from "../runtime/context.js";

function scopeArguments(scope: HookScope, target: string | null | undefined): readonly string[] {
  if (scope === "server") return ["-g"];
  return target == null ? [] : ["-t", target];
}

/** Every hook tmux reports at one scope, keyed by name with its index kept. */
export async function showHooks(
  runtime: RuntimeContext,
  scope: HookScope,
  target?: string | null,
): Promise<ReadonlyMap<string, string>> {
  const lines = await runCommand(runtime, ["show-hooks", ...scopeArguments(scope, target)]);
  const hooks = new Map<string, string>();
  for (const line of lines) {
    const parsed = parseNameValueLine(line);
    if (parsed !== undefined) hooks.set(parsed[0], parsed[1]);
  }
  return hooks;
}

/** Bind a tmux command to a hook name at one scope. */
export async function setHook(
  runtime: RuntimeContext,
  scope: HookScope,
  target: string | null | undefined,
  name: string,
  command: string,
): Promise<void> {
  await runCommand(runtime, ["set-hook", ...scopeArguments(scope, target), name, command]);
}

/** Remove every command bound to a hook name at one scope. */
export async function unsetHook(
  runtime: RuntimeContext,
  scope: HookScope,
  target: string | null | undefined,
  name: string,
): Promise<void> {
  await runCommand(runtime, ["set-hook", "-u", ...scopeArguments(scope, target), name]);
}
