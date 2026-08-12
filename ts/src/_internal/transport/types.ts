import type { CommandResult, DeliveryStatus, OperationStatus } from "../../common.js";

export interface CommandRequest {
  readonly args: readonly string[];
  readonly environment?: Readonly<Record<string, string | undefined>>;
  readonly executable: string;
  readonly signal?: AbortSignal;
  readonly stdin?: Uint8Array;
  readonly timeoutMs?: number;
}

export function snapshotCommandRequest(request: CommandRequest): CommandRequest {
  const stdin = request.stdin === undefined ? undefined : new Uint8Array(request.stdin);
  const snapshot: CommandRequest = {
    args: Object.freeze([...request.args]),
    ...(request.environment === undefined
      ? {}
      : { environment: Object.freeze({ ...request.environment }) }),
    executable: request.executable,
    ...(request.signal === undefined ? {} : { signal: request.signal }),
    ...(request.timeoutMs === undefined ? {} : { timeoutMs: request.timeoutMs }),
  };
  if (stdin !== undefined) {
    Object.defineProperty(snapshot, "stdin", {
      enumerable: true,
      get: () => new Uint8Array(stdin),
    });
  }
  return Object.freeze(snapshot);
}

export interface RawCommandResult {
  readonly cmd: readonly string[];
  readonly returncode: number;
  readonly signal: NodeJS.Signals | null;
  readonly stderr: Uint8Array;
  readonly stdout: Uint8Array;
}

export type TransportErrorKind = "cancelled" | "pipe" | "protocol" | "spawn" | "timeout";

interface TransportErrorOptions {
  readonly cause?: unknown;
  readonly delivery: DeliveryStatus;
  readonly kind: TransportErrorKind;
  readonly signal?: NodeJS.Signals | null;
  readonly stderr?: Uint8Array;
  readonly stdout?: Uint8Array;
}

export class TransportError extends Error {
  readonly #stderr: Uint8Array;
  readonly #stdout: Uint8Array;
  readonly delivery: DeliveryStatus;
  readonly kind: TransportErrorKind;
  readonly signal: NodeJS.Signals | null | undefined;

  constructor(message: string, options: TransportErrorOptions) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "TransportError";
    this.delivery = options.delivery;
    this.kind = options.kind;
    this.signal = options.signal;
    this.#stderr = new Uint8Array(options.stderr ?? []);
    this.#stdout = new Uint8Array(options.stdout ?? []);
  }

  get stderr(): Uint8Array {
    return new Uint8Array(this.#stderr);
  }

  get stdout(): Uint8Array {
    return new Uint8Array(this.#stdout);
  }
}

export interface CommandTransport {
  execute(request: CommandRequest): Promise<RawCommandResult>;
}

export interface BatchOutcome {
  readonly delivery: DeliveryStatus;
  readonly error?: TransportError;
  readonly index: number;
  readonly rawResult?: RawCommandResult;
  readonly request: CommandRequest;
  readonly result?: CommandResult;
  readonly status: OperationStatus;
}
