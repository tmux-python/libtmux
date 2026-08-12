import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { StringDecoder } from "node:string_decoder";

import { runWithCleanup } from "./run_root.js";
import type { TestServer } from "./test_server.js";

export interface ControlModeOptions {
  readonly server: TestServer;
  readonly targetSession: string;
}

interface LineWaiter {
  readonly accept: (line: string) => boolean;
  readonly minimumIndex: number;
  readonly reject: (error: Error) => void;
  readonly resolve: (line: string) => void;
  readonly timer: NodeJS.Timeout;
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function waitForClose(
  child: ChildProcessWithoutNullStreams,
  milliseconds: number,
  isClosed: () => boolean,
): Promise<boolean> {
  if (isClosed()) return Promise.resolve(true);
  return new Promise<boolean>((resolve) => {
    let settled = false;
    let timer: NodeJS.Timeout | undefined;
    const finish = (closed: boolean): void => {
      if (settled) return;
      settled = true;
      if (timer !== undefined) clearTimeout(timer);
      child.removeListener("close", onClose);
      resolve(closed);
    };
    const onClose = (): void => finish(true);
    child.once("close", onClose);
    timer = setTimeout(() => finish(false), milliseconds);
    timer.unref();
    if (isClosed()) finish(true);
  });
}

export class ControlMode {
  readonly clientName: string;
  readonly pid: number;
  readonly #child: ChildProcessWithoutNullStreams;
  readonly #lines: string[];
  readonly #waiters: Set<LineWaiter>;
  readonly #server: TestServer;
  #cleanupPromise: Promise<void> | undefined;

  private constructor(
    child: ChildProcessWithoutNullStreams,
    clientName: string,
    lines: string[],
    waiters: Set<LineWaiter>,
    server: TestServer,
  ) {
    if (child.pid === undefined) throw new Error("control-mode client has no PID");
    this.#child = child;
    this.clientName = clientName;
    this.pid = child.pid;
    this.#lines = lines;
    this.#waiters = waiters;
    this.#server = server;
  }

  static async open(options: ControlModeOptions): Promise<ControlMode> {
    await options.server.assertControllerCurrent();
    const child = spawn(
      options.server.tmuxExecutable,
      ["-S", options.server.socketPath, "-C", "attach-session", "-t", options.targetSession],
      {
        env: options.server.controllerEnvironment,
        shell: false,
        stdio: ["pipe", "pipe", "pipe"],
      },
    );
    const lines: string[] = [];
    const waiters = new Set<LineWaiter>();
    const stdoutDecoder = new StringDecoder("utf8");
    const stderrDecoder = new StringDecoder("utf8");
    let stdoutPending = "";
    let stderr = "";
    let closed = false;
    let spawnError: Error | undefined;

    const publishLine = (line: string): void => {
      const index = lines.push(line) - 1;
      for (const waiter of waiters) {
        if (index < waiter.minimumIndex || !waiter.accept(line)) continue;
        clearTimeout(waiter.timer);
        waiters.delete(waiter);
        waiter.resolve(line);
      }
    };
    child.stdout.on("data", (chunk: Buffer) => {
      stdoutPending += stdoutDecoder.write(chunk);
      const complete = stdoutPending.split("\n");
      stdoutPending = complete.pop() ?? "";
      for (const line of complete) publishLine(line);
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += stderrDecoder.write(chunk);
    });
    child.once("close", () => {
      closed = true;
      const tail = stdoutPending + stdoutDecoder.end();
      if (tail !== "") publishLine(tail);
      stderr += stderrDecoder.end();
      for (const waiter of waiters) {
        clearTimeout(waiter.timer);
        waiter.reject(new Error(`control-mode client exited: ${stderr.trim()}`));
      }
      waiters.clear();
    });
    child.once("error", (error) => {
      spawnError = error;
      closed = true;
      for (const waiter of waiters) {
        clearTimeout(waiter.timer);
        waiter.reject(error);
      }
      waiters.clear();
    });

    const cleanupPartial = async (): Promise<void> => {
      child.stdin.end();
      if (!closed) child.kill("SIGTERM");
      for (let attempt = 0; attempt < 50 && !closed; attempt += 1) {
        // Control client teardown is bounded; fixture readiness never uses this loop.
        // eslint-disable-next-line no-await-in-loop -- each probe observes state after the preceding bound.
        await wait(10);
      }
      if (!closed) child.kill("SIGKILL");
      if (!closed) {
        await waitForClose(child, 500, () => closed);
      }
      if (!closed) {
        child.stdin.destroy();
        child.stdout.destroy();
        child.stderr.destroy();
        child.unref();
      }
    };

    try {
      if (child.pid === undefined) throw new Error("control-mode client did not spawn");
      const registrationDeadline = performance.now() + 500;
      while (performance.now() < registrationDeadline) {
        if (closed) {
          throw new Error(`control-mode attach failed: ${spawnError?.message ?? stderr.trim()}`);
        }
        const remaining = Math.max(1, registrationDeadline - performance.now());
        let probeTimer: NodeJS.Timeout | undefined;
        let clients: Awaited<ReturnType<TestServer["executeText"]>>;
        try {
          // eslint-disable-next-line no-await-in-loop -- registration probes must observe this exact child in order.
          clients = await Promise.race([
            options.server.executeText(["list-clients", "-F", "#{client_pid}\t#{client_name}"]),
            new Promise<never>((_, reject) => {
              probeTimer = setTimeout(
                () => reject(new Error("control-mode client registration timed out")),
                remaining,
              );
            }),
          ]);
        } finally {
          if (probeTimer !== undefined) clearTimeout(probeTimer);
        }
        for (const line of clients.stdout) {
          const [rawPid, clientName] = line.split("\t", 2);
          if (rawPid === String(child.pid) && clientName !== undefined && clientName !== "") {
            return new ControlMode(child, clientName, lines, waiters, options.server);
          }
        }
        // eslint-disable-next-line no-await-in-loop -- registration probes are deliberately bounded and sequential.
        await wait(Math.min(10, Math.max(0, registrationDeadline - performance.now())));
      }
      throw new Error("control-mode client registration timed out");
    } catch (error) {
      await cleanupPartial();
      throw error;
    }
  }

  static async run<T>(
    options: ControlModeOptions,
    body: (control: ControlMode) => Promise<T>,
  ): Promise<T> {
    const control = await ControlMode.open(options);
    return runWithCleanup(
      () => body(control),
      () => control.dispose(),
    );
  }

  async sendAndWaitFor(command: string, until: (line: string) => boolean): Promise<string> {
    const minimumIndex = this.#lines.length;
    const response = new Promise<string>((resolve, reject) => {
      const waiter: LineWaiter = {
        accept: until,
        minimumIndex,
        reject,
        resolve,
        timer: setTimeout(() => {
          this.#waiters.delete(waiter);
          reject(new Error("control-mode response timed out"));
        }, 3_000),
      };
      this.#waiters.add(waiter);
    });
    this.#child.stdin.write(`${command}\n`, "utf8", (error) => {
      if (error === null || error === undefined) return;
      for (const waiter of this.#waiters) {
        if (waiter.minimumIndex !== minimumIndex) continue;
        clearTimeout(waiter.timer);
        this.#waiters.delete(waiter);
        waiter.reject(error);
      }
    });
    return response;
  }

  dispose(): Promise<void> {
    this.#cleanupPromise ??= (async () => {
      this.#child.stdin.end();
      if (this.#child.exitCode === null && this.#child.signalCode === null) {
        this.#child.kill("SIGTERM");
        const grace = await waitForClose(
          this.#child,
          500,
          () => this.#child.exitCode !== null || this.#child.signalCode !== null,
        );
        if (!grace) {
          this.#child.kill("SIGKILL");
          const killed = await waitForClose(
            this.#child,
            500,
            () => this.#child.exitCode !== null || this.#child.signalCode !== null,
          );
          if (!killed) {
            this.#child.stdin.destroy();
            this.#child.stdout.destroy();
            this.#child.stderr.destroy();
            this.#child.unref();
            throw new Error("control-mode client close exceeded hard deadline after SIGKILL");
          }
        }
      }
      const listed = await this.#server.executeText([
        "list-clients",
        "-F",
        "#{client_pid}\t#{client_name}",
      ]);
      if (listed.stdout.includes(`${String(this.pid)}\t${this.clientName}`)) {
        throw new Error("owned control-mode client remained registered after cleanup");
      }
    })();
    return this.#cleanupPromise;
  }

  async [Symbol.asyncDispose](): Promise<void> {
    await this.dispose();
  }
}
