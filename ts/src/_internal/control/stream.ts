import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";

import type { TmuxConnection } from "../runtime/connection.js";
import { connectionArguments } from "../operations/request.js";
import type {
  AbortLike,
  TmuxEvent,
  TmuxEventStream as PublicEventStream,
  WatchOptions,
} from "../../types.js";
import { parseControlLine } from "./events.js";

const NEWLINE = 0x0a;
const DEFAULT_BUFFER_SIZE = 1024;

/**
 * A live stream of tmux control-mode events.
 *
 * The stream owns a `tmux -C attach-session` process. It is an async iterable
 * and an async disposable, so `await using` ends the connection on scope exit
 * even when the loop throws:
 *
 * ```ts
 * await using events = server.watch();
 * for await (const event of events) {
 *   if (event.kind === "output") process.stdout.write(event.data);
 * }
 * ```
 *
 * Iterating twice is not supported; the events are consumed, not replayed.
 */
export class TmuxEventStream implements PublicEventStream {
  readonly #buffer: TmuxEvent[] = [];
  readonly #bufferSize: number;
  #child: ChildProcessWithoutNullStreams | undefined;
  #closed = false;
  #dropped = 0;
  #failure: Error | undefined;
  #iterated = false;
  #pending: (() => void) | undefined;
  #onAbort: (() => void) | undefined;
  readonly #signal: AbortLike | undefined;

  constructor(connection: TmuxConnection, options: WatchOptions = {}) {
    this.#bufferSize = options.bufferSize ?? DEFAULT_BUFFER_SIZE;
    if (!Number.isInteger(this.#bufferSize) || this.#bufferSize < 1) {
      throw new TypeError("bufferSize must be a positive integer");
    }
    this.#signal = options.signal;

    // A bare `tmux -C` is a control client that never attached, and tmux sends
    // it no %output at all. Attaching is what makes the pane stream arrive.
    const argv = [
      ...connectionArguments(connection),
      "-C",
      "attach-session",
      ...(options.target === undefined ? [] : ["-t", options.target]),
    ];
    this.#child = spawn(connection.executable, argv, {
      env: { ...process.env, ...connection.environment },
      stdio: ["pipe", "pipe", "pipe"],
    }) as ChildProcessWithoutNullStreams;

    this.#listen();
  }

  /** Events discarded because the consumer fell behind. */
  get dropped(): number {
    return this.#dropped;
  }

  #listen(): void {
    const child = this.#child;
    if (child === undefined) return;
    let carry = new Uint8Array(0);
    let inBlock = false;

    child.stdout.on("data", (chunk: Buffer) => {
      const merged = new Uint8Array(carry.length + chunk.length);
      merged.set(carry);
      merged.set(chunk, carry.length);
      let start = 0;
      for (;;) {
        const newline = merged.indexOf(NEWLINE, start);
        if (newline === -1) break;
        const line = merged.subarray(start, newline);
        start = newline + 1;
        const parsed = parseControlLine(line);
        if (parsed === undefined) continue;
        if (parsed.kind === "block-begin") {
          inBlock = true;
          continue;
        }
        if (parsed.kind === "block-end") {
          inBlock = false;
          continue;
        }
        // Lines inside a block are one command's output, not notifications.
        if (!inBlock) this.#offer(parsed);
      }
      carry = merged.subarray(start);
    });

    const stderr: Buffer[] = [];
    child.stderr.on("data", (chunk: Buffer) => stderr.push(chunk));
    child.once("error", (error: Error) => this.#finish(error));
    child.once("close", (code) => {
      const message = Buffer.concat(stderr).toString("utf8").trim();
      this.#finish(
        code === 0 || code === null || this.#closed
          ? undefined
          : new Error(
              `tmux control mode exited with ${String(code)}${message === "" ? "" : `: ${message}`}`,
            ),
      );
    });

    if (this.#signal !== undefined) {
      this.#onAbort = () => void this.close();
      if (this.#signal.aborted) this.#onAbort();
      else this.#signal.addEventListener("abort", this.#onAbort, { once: true });
    }
  }

  #offer(event: TmuxEvent): void {
    if (this.#buffer.length >= this.#bufferSize) {
      this.#buffer.shift();
      this.#dropped += 1;
    }
    this.#buffer.push(event);
    this.#wake();
  }

  #finish(failure: Error | undefined): void {
    this.#failure ??= failure;
    this.#closed = true;
    this.#child = undefined;
    this.#wake();
  }

  #wake(): void {
    const pending = this.#pending;
    this.#pending = undefined;
    pending?.();
  }

  async *[Symbol.asyncIterator](): AsyncIterator<TmuxEvent> {
    if (this.#iterated) throw new Error("a tmux event stream can only be iterated once");
    this.#iterated = true;
    try {
      for (;;) {
        while (this.#buffer.length > 0) yield this.#buffer.shift()!;
        if (this.#closed) {
          if (this.#failure !== undefined) throw this.#failure;
          return;
        }
        // eslint-disable-next-line no-await-in-loop -- one wait per drained buffer.
        await new Promise<void>((resolve) => {
          this.#pending = resolve;
        });
      }
    } finally {
      await this.close();
    }
  }

  /** End the connection. Safe to call more than once. */
  async close(): Promise<void> {
    if (this.#signal !== undefined && this.#onAbort !== undefined) {
      this.#signal.removeEventListener("abort", this.#onAbort);
      this.#onAbort = undefined;
    }
    const child = this.#child;
    this.#closed = true;
    this.#wake();
    if (child === undefined) return;
    this.#child = undefined;
    await new Promise<void>((resolve) => {
      child.once("close", () => resolve());
      child.kill("SIGTERM");
    });
  }

  async [Symbol.asyncDispose](): Promise<void> {
    await this.close();
  }
}

/** Open a control-mode event stream against a server. */
export function watchServer(connection: TmuxConnection, options?: WatchOptions): PublicEventStream {
  return new TmuxEventStream(connection, options);
}
