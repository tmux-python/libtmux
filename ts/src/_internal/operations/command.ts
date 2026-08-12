import { LibTmuxException } from "../../exc.js";
import type { RuntimeContext } from "../runtime/context.js";
import { adaptRawResult, prepareCommandRequest } from "./request.js";

/**
 * Run one tmux command and return its stdout lines, raising on failure.
 *
 * Operations that only care about success ignore the return value. Reporting
 * tmux's own stderr rather than a synthesized message keeps the cause visible;
 * tmux is far more specific about why a target or option was rejected than any
 * wrapper could be.
 */
export async function runCommand(
  runtime: RuntimeContext,
  args: readonly string[],
): Promise<readonly string[]> {
  const result = adaptRawResult(
    await runtime.transport.execute(prepareCommandRequest(runtime.connection, args)),
  );
  if (result.returncode !== 0) {
    throw new LibTmuxException(`${args[0] ?? "tmux command"} failed: ${result.stderr.join("; ")}`);
  }
  return result.stdout;
}
