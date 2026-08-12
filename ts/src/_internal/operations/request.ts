import type { CommandOptions, CommandResult, OperationStatus } from "../../common.js";
import { decodeBackslashReplace } from "../codec/backslash_replace.js";
import type { TmuxConnection } from "../runtime/connection.js";
import type {
  BatchOutcome,
  CommandRequest,
  CommandTransport,
  RawCommandResult,
} from "../transport/types.js";
import { snapshotCommandRequest, TransportError } from "../transport/types.js";

function connectionArguments(connection: TmuxConnection): string[] {
  const args: string[] = [];
  if (connection.colors === 256) args.push("-2");
  if (connection.colors === 88) args.push("-8");
  if (connection.configFile !== undefined) args.push(`-f${connection.configFile}`);
  if (connection.socketName !== undefined) args.push(`-L${connection.socketName}`);
  if (connection.socketPath !== undefined) args.push(`-S${connection.socketPath}`);
  return args;
}

export function prepareCommandRequest(
  connection: TmuxConnection,
  args: readonly string[],
  options: CommandOptions = {},
): CommandRequest {
  if (options.stdin !== undefined && !(args[0] === "load-buffer" && args.at(-1) === "-")) {
    throw new TypeError(`${args[0] ?? "command"} does not accept stdin`);
  }
  return snapshotCommandRequest({
    args: Object.freeze([...connectionArguments(connection), ...args]),
    environment: connection.environment,
    executable: connection.executable,
    ...(options.signal === undefined ? {} : { signal: options.signal }),
    ...(options.stdin === undefined
      ? {}
      : {
          stdin:
            typeof options.stdin === "string"
              ? new TextEncoder().encode(options.stdin)
              : new Uint8Array(options.stdin),
        }),
  });
}

export function adaptRawResult(raw: RawCommandResult): CommandResult {
  const stdout = decodeBackslashReplace(raw.stdout).split("\n");
  while (stdout.at(-1) === "") stdout.pop();
  const stderr = decodeBackslashReplace(raw.stderr)
    .split("\n")
    .filter((line) => line !== "");
  const adaptedStdout =
    raw.cmd.includes("has-session") && stderr.length > 0 && stdout.length === 0
      ? [stderr[0]!]
      : stdout;

  return Object.freeze({
    cmd: Object.freeze([...raw.cmd]),
    returncode: raw.returncode,
    stderr: Object.freeze(stderr),
    stdout: Object.freeze(adaptedStdout),
  });
}

export async function executeBatch(
  transport: CommandTransport,
  requests: readonly CommandRequest[],
): Promise<readonly BatchOutcome[]> {
  const queuedRequests = requests.map((request) => snapshotCommandRequest(request));
  const outcomes: BatchOutcome[] = [];
  for (const [index, request] of queuedRequests.entries()) {
    try {
      // eslint-disable-next-line no-await-in-loop -- independent batches execute sequentially by contract.
      const rawResult = await transport.execute(request);
      const result = adaptRawResult(rawResult);
      const status: OperationStatus = rawResult.returncode === 0 ? "complete" : "failed";
      outcomes.push(
        Object.freeze({
          delivery: "replied" as const,
          index,
          rawResult,
          request,
          result,
          status,
        }),
      );
    } catch (error) {
      if (!(error instanceof TransportError)) throw error;
      outcomes.push(
        Object.freeze({
          delivery: error.delivery,
          error,
          index,
          request,
          status: error.delivery === "not_started" ? ("failed" as const) : ("unknown" as const),
        }),
      );
    }
  }
  return Object.freeze(outcomes);
}
