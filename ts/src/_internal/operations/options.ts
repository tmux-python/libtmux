import type { RuntimeContext } from "../runtime/context.js";
import { runCommand } from "./command.js";

/** The tmux option scope a lookup is addressed to. */
export type OptionScope = "pane" | "server" | "session" | "window";

const SCOPE_FLAGS: Readonly<Record<OptionScope, readonly string[]>> = Object.freeze({
  pane: ["-p"],
  server: ["-s"],
  session: [],
  window: ["-w"],
});

/**
 * tmux prints one option per line as a name and an optional value, quoting the
 * value only when it needs to. Array-valued options arrive as repeated lines
 * carrying their index in the name, as in `command-alias[0]`, and are preserved
 * verbatim here so the index survives for a later sparse-array reader.
 */
export function parseNameValueLine(line: string): readonly [string, string] | undefined {
  if (line === "") return undefined;
  const separator = line.indexOf(" ");
  if (separator === -1) return [line, ""];
  const name = line.slice(0, separator);
  const raw = line.slice(separator + 1);
  const unquoted =
    raw.length >= 2 && raw.startsWith('"') && raw.endsWith('"') ? raw.slice(1, -1) : raw;
  return [name, unquoted];
}

/**
 * Read the options tmux reports for one scope.
 *
 * This is the scope's own view, not a resolved one. Window and pane scopes list
 * only what was set on them, so a freshly created pane reports nothing at all
 * rather than the values it would inherit. Resolving inheritance needs tmux's
 * `-A`, which is a separate reader because it changes what a caller is asking.
 */
export async function showOptions(
  runtime: RuntimeContext,
  scope: OptionScope,
  target?: string | null,
): Promise<ReadonlyMap<string, string>> {
  const lines = await runCommand(runtime, [
    "show-options",
    ...SCOPE_FLAGS[scope],
    ...(target == null ? [] : ["-t", target]),
  ]);

  const options = new Map<string, string>();
  for (const line of lines) {
    const parsed = parseNameValueLine(line);
    if (parsed !== undefined) options.set(parsed[0], parsed[1]);
  }
  return options;
}

/** Set one option at a scope. `append` uses tmux's `-a` to extend a value. */
export async function setOption(
  runtime: RuntimeContext,
  scope: OptionScope,
  target: string | null | undefined,
  name: string,
  value: string,
  options: { readonly append?: boolean; readonly global?: boolean } = {},
): Promise<void> {
  await runCommand(runtime, [
    "set-option",
    ...SCOPE_FLAGS[scope],
    ...(options.global === true ? ["-g"] : []),
    ...(options.append === true ? ["-a"] : []),
    ...(target == null ? [] : ["-t", target]),
    name,
    value,
  ]);
}

/** Remove one option at a scope so it falls back to what it inherits. */
export async function unsetOption(
  runtime: RuntimeContext,
  scope: OptionScope,
  target: string | null | undefined,
  name: string,
  options: { readonly global?: boolean } = {},
): Promise<void> {
  await runCommand(runtime, [
    "set-option",
    ...SCOPE_FLAGS[scope],
    ...(options.global === true ? ["-g"] : []),
    "-u",
    ...(target == null ? [] : ["-t", target]),
    name,
  ]);
}
