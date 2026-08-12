import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "bun:test";

import { readProcessIdentity, type ProcessIdentity } from "../../src/_internal/test/run_root.js";
import { NodeSpawnTransport } from "../../src/_internal/transport/node_spawn_transport.js";
import { TransportError } from "../../src/_internal/transport/types.js";

const ignoreSigtermFixture = fileURLToPath(
  new URL("../fixtures/ignore_sigterm.mjs", import.meta.url),
);
const echoFixture = fileURLToPath(new URL("../fixtures/echo_argv.mjs", import.meta.url));

async function waitForFile(path: string, attempts = 100): Promise<void> {
  try {
    await readFile(path);
  } catch {
    if (attempts === 1) throw new Error("exit marker was not created");
    await new Promise((resolve) => setTimeout(resolve, 5));
    await waitForFile(path, attempts - 1);
  }
}

async function readHolderIdentity(path: string): Promise<ProcessIdentity> {
  const rawPid = (await readFile(path, "utf8")).trim();
  if (!/^[1-9]\d*$/u.test(rawPid)) throw new Error("holder PID is invalid");
  const identity = await readProcessIdentity(Number(rawPid));
  if (identity === undefined) throw new Error("holder exited before identity capture");
  return identity;
}

function sameIdentity(left: ProcessIdentity | undefined, right: ProcessIdentity): boolean {
  return left?.pid === right.pid && left.startIdentity === right.startIdentity;
}

async function waitForHolderExit(identity: ProcessIdentity): Promise<boolean> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    // Holder cleanup is identity-checked and bounded independently of transport settlement.
    // eslint-disable-next-line no-await-in-loop -- each read must follow the preceding signal.
    const current = await readProcessIdentity(identity.pid);
    if (current === undefined || !sameIdentity(current, identity)) return true;
    // eslint-disable-next-line no-await-in-loop -- the total cleanup deadline is 200 ms.
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  return false;
}

async function stopHolder(identity: ProcessIdentity): Promise<void> {
  if (!sameIdentity(await readProcessIdentity(identity.pid), identity)) return;
  try {
    process.kill(identity.pid, "SIGTERM");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error;
    return;
  }
  if (await waitForHolderExit(identity)) return;
  if (!sameIdentity(await readProcessIdentity(identity.pid), identity)) return;
  process.kill(identity.pid, "SIGKILL");
  if (!(await waitForHolderExit(identity))) throw new Error("holder survived bounded cleanup");
}

describe("transport cancellation", () => {
  test("does not spawn for an already-aborted signal", async () => {
    const controller = new AbortController();
    controller.abort();
    const transport = new NodeSpawnTransport({ terminationGraceMs: 20 });

    try {
      await transport.execute({
        args: [],
        executable: "/definitely/not/an/executable",
        signal: controller.signal,
      });
      throw new Error("expected cancellation");
    } catch (error) {
      expect(error).toBeInstanceOf(TransportError);
      expect(error).toMatchObject({ delivery: "not_started", kind: "cancelled" });
    }
  });

  test("closes blocked stdin and escalates an ignored SIGTERM to SIGKILL", async () => {
    const temporaryRoot = await mkdtemp(join(tmpdir(), "libtmux-sigterm-"));
    const markerPath = join(temporaryRoot, "ready");
    const controller = new AbortController();
    const transport = new NodeSpawnTransport({ terminationGraceMs: 30 });
    const execution = transport.execute({
      args: [ignoreSigtermFixture, markerPath],
      executable: process.execPath,
      signal: controller.signal,
      stdin: new Uint8Array(16 * 1024 * 1024),
    });

    try {
      await waitForFile(markerPath);
      controller.abort();
      try {
        await execution;
        throw new Error("expected cancellation");
      } catch (error) {
        expect(error).toBeInstanceOf(TransportError);
        expect(error).toMatchObject({
          delivery: "indeterminate",
          kind: "cancelled",
          signal: "SIGKILL",
        });
      }
    } finally {
      await execution.catch(() => undefined);
      await rm(temporaryRoot, { force: true, recursive: true });
    }
  }, 5_000);

  test("bounds execution time and reports an indeterminate timeout", async () => {
    const transport = new NodeSpawnTransport({ terminationGraceMs: 20 });

    await expect(
      transport.execute({
        args: [ignoreSigtermFixture, "--exit-after=2000"],
        executable: process.execPath,
        timeoutMs: 500,
      }),
    ).rejects.toMatchObject({
      delivery: "indeterminate",
      kind: "timeout",
      signal: "SIGKILL",
    });
  });

  test("retains immutable synchronized partial output after cancellation", async () => {
    const temporaryRoot = await mkdtemp(join(tmpdir(), "libtmux-partial-output-"));
    const markerPath = join(temporaryRoot, "holder.pid");
    const controller = new AbortController();
    const transport = new NodeSpawnTransport({ terminationGraceMs: 20 });
    const execution = transport.execute({
      args: [ignoreSigtermFixture, `--inherit-pipes=${markerPath}`],
      executable: process.execPath,
      signal: controller.signal,
    });
    let failure: unknown;
    let holder: ProcessIdentity | undefined;
    try {
      await waitForFile(markerPath);
      holder = await readHolderIdentity(markerPath);
      const interruptedAt = performance.now();
      controller.abort();
      const outcome = await Promise.race([
        execution.then(
          (value) => ({ kind: "value" as const, value }),
          (error: unknown) => ({ error, kind: "error" as const }),
        ),
        new Promise<{ readonly kind: "deadline" }>((resolve) =>
          setTimeout(() => resolve({ kind: "deadline" }), 800),
        ),
      ]);
      expect(outcome.kind).not.toBe("deadline");
      expect(performance.now() - interruptedAt).toBeLessThan(800);
      if (outcome.kind === "error") failure = outcome.error;

      expect(failure).toBeInstanceOf(TransportError);
      expect(failure).toMatchObject({ delivery: "indeterminate", kind: "cancelled" });
      const diagnostic = failure as TransportError;
      expect(new TextDecoder().decode(diagnostic.stdout)).toBe("launch-frame\n");
      expect(new TextDecoder().decode(diagnostic.stderr)).toBe("launch-diagnostic\n");
      diagnostic.stdout[0] = 0;
      diagnostic.stderr[0] = 0;
      expect(new TextDecoder().decode(diagnostic.stdout)).toBe("launch-frame\n");
      expect(new TextDecoder().decode(diagnostic.stderr)).toBe("launch-diagnostic\n");
    } finally {
      if (holder !== undefined) await stopHolder(holder);
      await execution.catch(() => undefined);
      await rm(temporaryRoot, { force: true, recursive: true });
    }
  }, 5_000);

  test("bounds timeout cleanup when a killed parent has a descendant holding both pipes", async () => {
    const temporaryRoot = await mkdtemp(join(tmpdir(), "libtmux-held-pipes-"));
    const markerPath = join(temporaryRoot, "holder.pid");
    const transport = new NodeSpawnTransport({ terminationGraceMs: 20 });
    const startedAt = performance.now();
    const execution = transport.execute({
      args: [ignoreSigtermFixture, `--inherit-pipes=${markerPath}`],
      executable: process.execPath,
      timeoutMs: 500,
    });
    let holder: ProcessIdentity | undefined;
    try {
      await waitForFile(markerPath);
      holder = await readHolderIdentity(markerPath);
      const outcome = await Promise.race([
        execution.then(
          (value) => ({ kind: "value" as const, value }),
          (error: unknown) => ({ error, kind: "error" as const }),
        ),
        new Promise<{ readonly kind: "deadline" }>((resolve) =>
          setTimeout(() => resolve({ kind: "deadline" }), 1_400),
        ),
      ]);
      expect(outcome.kind).not.toBe("deadline");
      expect(performance.now() - startedAt).toBeLessThan(1_400);
      if (outcome.kind !== "error") throw new Error("expected transport timeout");
      expect(outcome.error).toBeInstanceOf(TransportError);
      expect(outcome.error).toMatchObject({ delivery: "indeterminate", kind: "timeout" });
      const diagnostic = outcome.error as TransportError;
      expect(new TextDecoder().decode(diagnostic.stdout)).toBe("launch-frame\n");
      expect(new TextDecoder().decode(diagnostic.stderr)).toBe("launch-diagnostic\n");
    } finally {
      if (holder !== undefined) await stopHolder(holder);
      await execution.catch(() => undefined);
      await rm(temporaryRoot, { force: true, recursive: true });
    }
  }, 5_000);

  test("settles each abort and exit race exactly once", async () => {
    const transport = new NodeSpawnTransport({ terminationGraceMs: 20 });

    const exerciseRace = async (): Promise<void> => {
      const controller = new AbortController();
      let settlements = 0;
      const execution = transport.execute({
        args: ["--input-type=module", "--eval", "setTimeout(() => {}, 15)"],
        executable: process.execPath,
        signal: controller.signal,
      });
      void execution.then(
        () => {
          settlements += 1;
        },
        () => {
          settlements += 1;
        },
      );
      setTimeout(() => controller.abort(), 15);
      await execution.catch(() => undefined);
      await new Promise((resolve) => setTimeout(resolve, 5));
      expect(settlements).toBe(1);
    };

    for (let index = 0; index < 20; index += 1) {
      // eslint-disable-next-line no-await-in-loop -- races repeat sequentially to avoid hiding orphaned children.
      await exerciseRace();
    }
  }, 10_000);

  test("keeps a terminal exit authoritative while inherited pipes finish closing", async () => {
    const temporaryRoot = await mkdtemp(join(tmpdir(), "libtmux-exit-race-"));
    const markerPath = join(temporaryRoot, "exited");
    const controller = new AbortController();
    const transport = new NodeSpawnTransport({ terminationGraceMs: 20 });
    const execution = transport.execute({
      args: [echoFixture, "--exit-with-inherited-pipe", markerPath, "1200"],
      executable: process.execPath,
      signal: controller.signal,
    });
    let holder: ProcessIdentity | undefined;
    try {
      await waitForFile(markerPath);
      holder = await readHolderIdentity(markerPath);
      await new Promise((resolve) => setTimeout(resolve, 25));
      const interruptedAt = performance.now();
      controller.abort();

      const result = await execution;

      expect(result.returncode).toBe(0);
      expect(result.signal).toBeNull();
      expect(performance.now() - interruptedAt).toBeLessThan(500);
    } finally {
      await execution.catch(() => undefined);
      if (holder !== undefined) await stopHolder(holder);
      await rm(temporaryRoot, { force: true, recursive: true });
    }
  }, 5_000);

  test("bounds post-exit drainage at the timeout while retaining the exit result", async () => {
    const temporaryRoot = await mkdtemp(join(tmpdir(), "libtmux-exit-timeout-"));
    const markerPath = join(temporaryRoot, "exited");
    const transport = new NodeSpawnTransport({ terminationGraceMs: 20 });
    const startedAt = performance.now();
    const execution = transport.execute({
      args: [echoFixture, "--exit-with-inherited-pipe", markerPath, "1200"],
      executable: process.execPath,
      timeoutMs: 300,
    });
    let holder: ProcessIdentity | undefined;
    try {
      await waitForFile(markerPath);
      holder = await readHolderIdentity(markerPath);
      const result = await execution;

      expect(result.returncode).toBe(0);
      expect(result.signal).toBeNull();
      expect(performance.now() - startedAt).toBeLessThan(800);
    } finally {
      await execution.catch(() => undefined);
      if (holder !== undefined) await stopHolder(holder);
      await rm(temporaryRoot, { force: true, recursive: true });
    }
  }, 5_000);
});
