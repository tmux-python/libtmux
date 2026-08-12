import { spawn } from "node:child_process";

import type { Readable } from "node:stream";

import type { DeliveryStatus } from "../../common.js";
import type { CommandRequest, RawCommandResult } from "./types.js";
import { snapshotCommandRequest, TransportError } from "./types.js";

export interface NodeSpawnTransportOptions {
  readonly postKillGraceMs?: number;
  readonly terminationGraceMs?: number;
}

interface ClosedProcess {
  readonly code: number | null;
  readonly signal: NodeJS.Signals | null;
}

function collect(stream: Readable, chunks: Buffer[]): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = (): void => {
      stream.removeListener("close", onClose);
      stream.removeListener("data", onData);
      stream.removeListener("end", onEnd);
      stream.removeListener("error", onError);
    };
    const finish = (): void => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(collectedBytes(chunks));
    };
    const onClose = (): void => finish();
    const onData = (chunk: Buffer | Uint8Array): void => {
      chunks.push(Buffer.from(chunk));
    };
    const onEnd = (): void => finish();
    const onError = (error: Error): void => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };
    stream.on("data", onData);
    stream.once("end", onEnd);
    stream.once("error", onError);
    stream.once("close", onClose);
  });
}

function collectedBytes(chunks: readonly Buffer[]): Uint8Array {
  return Buffer.concat(chunks);
}

function isAborted(signal: AbortSignal | undefined): boolean {
  return signal?.aborted === true;
}

export class NodeSpawnTransport {
  readonly #postKillGraceMs: number;
  readonly #terminationGraceMs: number;

  constructor(options: NodeSpawnTransportOptions = {}) {
    this.#postKillGraceMs = options.postKillGraceMs ?? 250;
    this.#terminationGraceMs = options.terminationGraceMs ?? 100;
  }

  async execute(request: CommandRequest): Promise<RawCommandResult> {
    const submitted = snapshotCommandRequest(request);
    if (isAborted(submitted.signal)) {
      throw new TransportError("command cancelled before spawn", {
        delivery: "not_started",
        kind: "cancelled",
      });
    }
    const stdin = submitted.stdin;

    let child;
    try {
      child = spawn(submitted.executable, [...submitted.args], {
        env: submitted.environment,
        shell: false,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (error) {
      throw new TransportError("command spawn failed", {
        cause: error,
        delivery: "not_started",
        kind: "spawn",
      });
    }

    let closed = false;
    let drainageDiscarded = false;
    let interruption: "cancelled" | "timeout" | undefined;
    let observedExit: ClosedProcess | undefined;
    let delivery: DeliveryStatus = "not_started";
    let escalationTimer: NodeJS.Timeout | undefined;
    let postKillTimer: NodeJS.Timeout | undefined;
    let timeoutTimer: NodeJS.Timeout | undefined;
    let spawnError: unknown;
    let stdinError: unknown;
    let forcedSettlement = false;
    const stderrChunks: Buffer[] = [];
    const stdoutChunks: Buffer[] = [];

    let settleLifecycle!: (value: ClosedProcess) => void;
    const lifecyclePromise = new Promise<ClosedProcess>((resolve) => {
      settleLifecycle = resolve;
    });

    const clearLifecycleTimers = (): void => {
      if (escalationTimer !== undefined) clearTimeout(escalationTimer);
      if (postKillTimer !== undefined) clearTimeout(postKillTimer);
      if (timeoutTimer !== undefined) clearTimeout(timeoutTimer);
    };

    const removeAbortListener = (): void => {
      submitted.signal?.removeEventListener("abort", onAbort);
    };

    const discardDrainage = (): void => {
      if (drainageDiscarded) return;
      drainageDiscarded = true;
      child.stdin.destroy();
      child.stdout.destroy();
      child.stderr.destroy();
    };

    const forceSettlement = (): void => {
      if (closed || forcedSettlement) return;
      forcedSettlement = true;
      discardDrainage();
      child.removeListener("close", onClose);
      child.unref();
      clearLifecycleTimers();
      removeAbortListener();
      settleLifecycle(observedExit ?? { code: null, signal: null });
    };

    const armHardSettlement = (): void => {
      postKillTimer ??= setTimeout(forceSettlement, this.#postKillGraceMs);
    };

    const terminate = (): void => {
      child.stdin.destroy();
      if (closed || forcedSettlement || observedExit !== undefined) return;
      child.kill("SIGTERM");
      escalationTimer ??= setTimeout(() => {
        if (closed || forcedSettlement || observedExit !== undefined) return;
        child.kill("SIGKILL");
        armHardSettlement();
      }, this.#terminationGraceMs);
      escalationTimer.unref();
    };

    const interrupt = (kind: "cancelled" | "timeout"): void => {
      if (interruption !== undefined) return;
      if (observedExit !== undefined) {
        discardDrainage();
        armHardSettlement();
        return;
      }
      interruption = kind;
      if (delivery === "written" || child.pid !== undefined) delivery = "indeterminate";
      terminate();
    };
    const onAbort = (): void => {
      interrupt("cancelled");
    };

    child.stdin.on("error", (error) => {
      stdinError = error;
    });
    child.once("spawn", () => {
      if (interruption !== undefined) {
        delivery = "indeterminate";
        terminate();
        return;
      }
      delivery = "written";
      child.stdin.end(stdin);
    });
    child.once("error", (error) => {
      spawnError = error;
    });
    child.once("exit", (code, signal) => {
      observedExit = { code, signal };
      if (escalationTimer !== undefined) clearTimeout(escalationTimer);
      if (interruption !== undefined) {
        discardDrainage();
        armHardSettlement();
      }
    });

    const stdoutPromise = collect(child.stdout, stdoutChunks);
    const stderrPromise = collect(child.stderr, stderrChunks);
    function onClose(code: number | null, signal: NodeJS.Signals | null): void {
      closed = true;
      clearLifecycleTimers();
      removeAbortListener();
      settleLifecycle({ code, signal });
    }
    child.once("close", onClose);

    submitted.signal?.addEventListener("abort", onAbort, { once: true });
    if (isAborted(submitted.signal)) onAbort();
    if (submitted.timeoutMs !== undefined) {
      timeoutTimer = setTimeout(() => interrupt("timeout"), submitted.timeoutMs);
      timeoutTimer.unref();
    }

    const stdoutStatePromise = stdoutPromise.then(
      (value) => ({ status: "fulfilled" as const, value }),
      (reason: unknown) => ({ reason, status: "rejected" as const }),
    );
    const stderrStatePromise = stderrPromise.then(
      (value) => ({ status: "fulfilled" as const, value }),
      (reason: unknown) => ({ reason, status: "rejected" as const }),
    );

    const close = await lifecyclePromise;
    const [stdoutState, stderrState] = forcedSettlement
      ? [
          { status: "fulfilled" as const, value: collectedBytes(stdoutChunks) },
          { status: "fulfilled" as const, value: collectedBytes(stderrChunks) },
        ]
      : await Promise.all([stdoutStatePromise, stderrStatePromise]);

    if (interruption !== undefined) {
      throw new TransportError(
        interruption === "timeout" ? "command timed out" : "command cancelled",
        {
          delivery,
          kind: interruption,
          ...(observedExit === undefined ? {} : { signal: observedExit.signal }),
          ...(stderrState.status === "fulfilled" ? { stderr: stderrState.value } : {}),
          ...(stdoutState.status === "fulfilled" ? { stdout: stdoutState.value } : {}),
        },
      );
    }
    if (spawnError !== undefined) {
      throw new TransportError("command spawn failed", {
        cause: spawnError,
        delivery: "not_started",
        kind: "spawn",
        signal: close.signal,
      });
    }
    if (stdinError !== undefined) {
      throw new TransportError("command stdin failed", {
        cause: stdinError,
        delivery: "indeterminate",
        kind: "pipe",
        signal: close.signal,
      });
    }
    if (stdoutState.status === "rejected" && !drainageDiscarded) {
      throw new TransportError("command output failed", {
        cause: stdoutState.reason,
        delivery: "indeterminate",
        kind: "pipe",
        signal: close.signal,
      });
    }
    if (stderrState.status === "rejected" && !drainageDiscarded) {
      throw new TransportError("command output failed", {
        cause: stderrState.reason,
        delivery: "indeterminate",
        kind: "pipe",
        signal: close.signal,
      });
    }
    const terminal = observedExit ?? close;
    if (terminal.code === null) {
      throw new TransportError("command closed without an exit code", {
        delivery: "indeterminate",
        kind: "protocol",
        signal: terminal.signal,
      });
    }

    return {
      cmd: Object.freeze([submitted.executable, ...submitted.args]),
      returncode: terminal.code,
      signal: terminal.signal,
      stderr: stderrState.status === "fulfilled" ? stderrState.value : new Uint8Array(),
      stdout: stdoutState.status === "fulfilled" ? stdoutState.value : new Uint8Array(),
    };
  }
}
