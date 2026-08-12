import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { createServer } from "node:net";
import {
  access,
  chmod,
  copyFile,
  lstat,
  link,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
  rmdir,
  stat,
  symlink,
  unlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "bun:test";

import {
  beginFixtureLaunch,
  OWNER_RECORD_NAME,
  parseProcStatStartTime,
  prepareRunRoot,
  readDaemonIdentity,
  readFixtureRecord,
  readProcessIdentity,
  promoteFixtureLaunch,
  reapFixture,
  reapOwnedRunRoot,
  reapStaleRunRoot,
  reserveFixture,
  rollbackFixtureLaunchNotStarted,
  runSupervisor,
  validateOwnedRecordMetadata,
  type FixtureRecord,
} from "../../src/_internal/test/run_root.js";
import { TestServer } from "../../src/_internal/test/test_server.js";

interface ClosableServer {
  close(callback: () => void): unknown;
}

const tsRoot = fileURLToPath(new URL("../..", import.meta.url));
const workerPath = fileURLToPath(new URL("../fixtures/leaking_tmux_worker.ts", import.meta.url));
const supervisorPath = fileURLToPath(new URL("../../scripts/test_supervisor.ts", import.meta.url));
const reaperPath = fileURLToPath(new URL("../../scripts/reap-test-run.ts", import.meta.url));
const differentialRunnerPath = fileURLToPath(
  new URL("../../scripts/run-differential-tests.ts", import.meta.url),
);
const nodeRunnerPath = fileURLToPath(new URL("../../scripts/test-node.ts", import.meta.url));

interface ClosedChild {
  readonly code: number | null;
  readonly signal: string | null;
  readonly stderr: string;
  readonly stdout: string;
}

async function closeChild(child: ReturnType<typeof spawn>): Promise<ClosedChild> {
  const stdout: Buffer[] = [];
  const stderr: Buffer[] = [];
  child.stdout?.on("data", (chunk: Buffer) => stdout.push(chunk));
  child.stderr?.on("data", (chunk: Buffer) => stderr.push(chunk));
  return new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code, signal) =>
      resolve({
        code,
        signal,
        stderr: Buffer.concat(stderr).toString("utf8"),
        stdout: Buffer.concat(stdout).toString("utf8"),
      }),
    );
  });
}

async function closeChildWithin(
  child: ReturnType<typeof spawn>,
  timeoutMs: number,
): Promise<ClosedChild> {
  const stdout: Buffer[] = [];
  const stderr: Buffer[] = [];
  const onStdout = (chunk: Buffer): number => stdout.push(chunk);
  const onStderr = (chunk: Buffer): number => stderr.push(chunk);
  child.stdout?.on("data", onStdout);
  child.stderr?.on("data", onStderr);
  const waitForClose = async (
    boundMs: number,
  ): Promise<{ code: number | null; signal: string | null } | undefined> => {
    if (child.exitCode !== null || child.signalCode !== null) {
      return { code: child.exitCode, signal: child.signalCode };
    }
    return await new Promise((resolve, reject) => {
      const cleanup = (): void => {
        clearTimeout(timer);
        child.removeListener("close", onClose);
        child.removeListener("error", onError);
      };
      const onClose = (code: number | null, signal: string | null): void => {
        cleanup();
        resolve({ code, signal });
      };
      const onError = (error: Error): void => {
        cleanup();
        reject(error);
      };
      const timer = setTimeout(() => {
        cleanup();
        resolve(undefined);
      }, boundMs);
      timer.unref();
      child.once("close", onClose);
      child.once("error", onError);
      if (child.exitCode !== null || child.signalCode !== null) {
        onClose(child.exitCode, child.signalCode);
      }
    });
  };
  try {
    let closed = await waitForClose(timeoutMs);
    if (closed === undefined) {
      child.kill("SIGTERM");
      closed = await waitForClose(100);
    }
    if (closed === undefined) {
      child.kill("SIGKILL");
      closed = await waitForClose(500);
    }
    if (closed === undefined) {
      child.stdin?.destroy();
      child.stdout?.destroy();
      child.stderr?.destroy();
      child.unref();
      throw new Error("owned child did not close after SIGKILL");
    }
    return {
      ...closed,
      stderr: Buffer.concat(stderr).toString("utf8"),
      stdout: Buffer.concat(stdout).toString("utf8"),
    };
  } finally {
    child.stdout?.removeListener("data", onStdout);
    child.stderr?.removeListener("data", onStderr);
  }
}

async function exitChildWithin(
  child: ReturnType<typeof spawn>,
  timeoutMs: number,
): Promise<{ code: number | null; signal: string | null }> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      new Promise<{ code: number | null; signal: string | null }>((resolve, reject) => {
        child.once("error", reject);
        child.once("exit", (code, signal) => resolve({ code, signal }));
      }),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error("child exit exceeded hard deadline")), timeoutMs);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

async function waitForPath(path: string, attempts = 200): Promise<void> {
  try {
    await stat(path);
  } catch {
    if (attempts === 1) throw new Error(`path was not created: ${path}`);
    await new Promise((resolve) => setTimeout(resolve, 5));
    await waitForPath(path, attempts - 1);
  }
}

async function observePathWhileRunning(
  candidatePath: string,
  child: ReturnType<typeof spawn>,
): Promise<boolean> {
  for (let attempt = 0; attempt < 400; attempt += 1) {
    try {
      // eslint-disable-next-line no-await-in-loop -- observation is bounded by process lifetime.
      await access(candidatePath);
      return true;
    } catch {
      if (child.exitCode !== null || child.signalCode !== null) return false;
      // eslint-disable-next-line no-await-in-loop -- observation is bounded by process lifetime.
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
  }
  return false;
}

async function observeReservationWhileRunning(
  runRoot: string,
  child: ReturnType<typeof spawn>,
): Promise<{ distinctOwners: boolean; observed: boolean }> {
  for (let attempt = 0; attempt < 400; attempt += 1) {
    try {
      // eslint-disable-next-line no-await-in-loop -- this observes worker-owned state while the runner is live.
      const entries = await readdir(runRoot, { withFileTypes: true });
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        const reservation = join(runRoot, entry.name);
        // eslint-disable-next-line no-await-in-loop -- both files must coexist in the same observed reservation.
        const [record, socket] = await Promise.all([
          stat(join(reservation, "fixture.json")).catch(() => undefined),
          stat(join(reservation, "s")).catch(() => undefined),
        ]);
        if (record?.isFile() === true && socket?.isSocket() === true) {
          // eslint-disable-next-line no-await-in-loop -- ownership must be read from the reservation just observed.
          const [ownerValue, fixtureValue] = await Promise.all([
            readFile(join(runRoot, OWNER_RECORD_NAME), "utf8"),
            readFile(join(reservation, "fixture.json"), "utf8"),
          ]);
          const owner = JSON.parse(ownerValue) as { owner: { pid: number } };
          const fixture = JSON.parse(fixtureValue) as { owner: { pid: number } };
          return { distinctOwners: owner.owner.pid !== fixture.owner.pid, observed: true };
        }
      }
    } catch {
      // The supervisor may still be publishing the root.
    }
    if (child.exitCode !== null || child.signalCode !== null) {
      return { distinctOwners: false, observed: false };
    }
    // eslint-disable-next-line no-await-in-loop -- observation is bounded by process lifetime.
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  return { distinctOwners: false, observed: false };
}

async function makeRoot(name: string): Promise<{ parent: string; root: string }> {
  const parent = await mkdtemp(join(tmpdir(), "ltx4-supervisor-"));
  const root = join(parent, name);
  await prepareRunRoot(root);
  return { parent, root };
}

async function listenOnUnixSocket(socketPath: string): Promise<ClosableServer> {
  const server = createServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(socketPath, resolve);
  });
  return server;
}

async function closeNetServer(server: ClosableServer | undefined): Promise<void> {
  if (server === undefined) return;
  await new Promise<void>((resolve) => server.close(() => resolve()));
}

function journalIdentity(metadata: Awaited<ReturnType<typeof lstat>>) {
  return {
    device: String(metadata.dev),
    inode: String(metadata.ino),
    kind: metadata.isDirectory()
      ? "directory"
      : metadata.isFile()
        ? "file"
        : metadata.isSocket()
          ? "socket"
          : "other",
    mode: String(metadata.mode),
    uid: String(metadata.uid),
  };
}

async function writeFixtureEscrowJournal(
  reserved: {
    readonly record: FixtureRecord;
    readonly recordPath: string;
    readonly reservationPath: string;
  },
  escrow: string,
  protocol: "libtmux-fixture-escrow-v2" | "libtmux-fixture-escrow-v3" = "libtmux-fixture-escrow-v3",
): Promise<void> {
  const recordText = await readFile(reserved.recordPath, "utf8");
  const socket = await lstat(reserved.record.socketPath).catch(() => undefined);
  await writeFile(
    join(escrow, "journal.json"),
    `${JSON.stringify({
      logicalSocketName: reserved.record.logicalSocketName,
      protocol,
      record: journalIdentity(await lstat(reserved.recordPath)),
      recordDigest: createHash("sha256").update(recordText).digest("hex"),
      recordPath: reserved.recordPath,
      ...(protocol === "libtmux-fixture-escrow-v3" ? { recordSnapshot: reserved.record } : {}),
      reservation: journalIdentity(await lstat(reserved.reservationPath)),
      reservationPath: reserved.reservationPath,
      runId: reserved.record.runId,
      ...(socket === undefined ? {} : { socket: journalIdentity(socket) }),
      socketPath: reserved.record.socketPath,
    })}\n`,
    { flag: "wx", mode: 0o600 },
  );
}

async function removeOwnedRoot(parent: string, root: string): Promise<void> {
  await reapOwnedRunRoot(root);
  await rm(parent, { force: true, recursive: true });
}

async function spawnLeakingWorker(
  root: string,
  mode: string,
  marker: string,
  environment: NodeJS.ProcessEnv = {},
) {
  return spawn("bun", [workerPath, "--mode", mode, "--marker", marker], {
    cwd: tsRoot,
    env: { ...process.env, ...environment, LIBTMUX_TEST_RUN_ROOT: root },
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

function syntheticLaunchInput(record: Extract<FixtureRecord, { readonly phase: "reserved" }>) {
  const value = randomUUID();
  const generation = {
    name: `LIBTMUX_TEST_GENERATION_${value.replaceAll("-", "").toUpperCase()}`,
    value,
  };
  const readyChannel = `ready-${randomUUID()}`;
  const paneCommand = [
    "env",
    "-u",
    shellQuote(generation.name),
    shellQuote(record.controller.executablePath),
    "-N",
    "-S",
    shellQuote(record.socketPath),
    "wait-for",
    "-S",
    shellQuote(readyChannel),
    "&&",
    "exec",
    "cat",
  ].join(" ");
  const bootstrapArgv = [
    record.controller.executablePath,
    "-f",
    "/dev/null",
    "-S",
    record.socketPath,
    "start-server",
    ";",
    "if-shell",
    "-F",
    `#{==:#{${generation.name}},${generation.value}}`,
    `new-session -d -P -F '#{socket_path}\t#{pid}\t#{session_id}' -s 'fixture-synthetic' ${shellQuote(paneCommand)}`,
    `display-message -p 'generation-mismatch-${randomUUID()}'`,
  ] as const;
  return { bootstrapArgv, generation };
}

async function beginSyntheticLaunch(reserved: {
  readonly capability: Parameters<typeof beginFixtureLaunch>[0];
  readonly record: Extract<FixtureRecord, { readonly phase: "reserved" }>;
  readonly reservationPath: string;
}) {
  const launch = syntheticLaunchInput(reserved.record);
  const attempt = await beginFixtureLaunch(reserved.capability, launch);
  const record = await readFixtureRecord(reserved.reservationPath);
  if (record.phase !== "launching") throw new Error("synthetic launch did not persist launching");
  return { attempt, record };
}

async function writeLaunchingHoldWrapper(parent: string, marker: string): Promise<string> {
  const python = Bun.which("python3");
  const tmux = Bun.which("tmux");
  if (python === null) throw new Error("python3 is required");
  if (tmux === null) throw new Error("tmux is required");
  const wrapper = join(parent, "tmux-launching-hold");
  const program = `import ctypes
import os
import signal
import subprocess
import sys

parent = os.getppid()
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
    raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")
if os.getppid() != parent:
    os.kill(os.getpid(), signal.SIGKILL)
completed = subprocess.run([sys.argv[2], *sys.argv[3:]], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
sys.stdout.buffer.write(completed.stdout)
sys.stdout.buffer.flush()
sys.stderr.buffer.write(completed.stderr)
sys.stderr.buffer.flush()
with open(sys.argv[1], "wb") as stream:
    stream.write(f"{os.getpid()}\\n".encode() + completed.stdout)
    stream.flush()
    os.fsync(stream.fileno())
signal.pause()
`;
  await writeFile(
    wrapper,
    `#!/bin/sh
exec ${shellQuote(python)} -c ${shellQuote(program)} ${shellQuote(marker)} ${shellQuote(tmux)} "$@"
`,
    { mode: 0o700 },
  );
  await chmod(wrapper, 0o700);
  return wrapper;
}

interface CapturedTmuxCleanup {
  readonly commandLine: Buffer;
  readonly daemon: NonNullable<Awaited<ReturnType<typeof readDaemonIdentity>>>;
  readonly recoverySocket: string;
  readonly socketIdentity: { readonly device: bigint; readonly inode: bigint };
}

async function captureTmuxCleanup(
  pid: number,
  socketPath: string,
  recoverySocket: string,
): Promise<CapturedTmuxCleanup> {
  const daemon = await readDaemonIdentity(pid);
  if (daemon === undefined) throw new Error("test-owned tmux daemon disappeared before capture");
  const commandLine = await readFile(`/proc/${String(pid)}/cmdline`);
  const socket = await lstat(socketPath, { bigint: true });
  if (!socket.isSocket()) throw new Error("test-owned tmux path is not a socket");
  await link(socketPath, recoverySocket);
  const recovery = await lstat(recoverySocket, { bigint: true });
  if (recovery.dev !== socket.dev || recovery.ino !== socket.ino) {
    throw new Error("test-owned recovery socket does not match the captured socket");
  }
  return {
    commandLine,
    daemon,
    recoverySocket,
    socketIdentity: { device: socket.dev, inode: socket.ino },
  };
}

async function terminateCapturedTmux(captured: CapturedTmuxCleanup): Promise<void> {
  const recovery = await lstat(captured.recoverySocket, { bigint: true });
  expect({ device: recovery.dev, inode: recovery.ino }).toEqual(captured.socketIdentity);
  const observed = await readDaemonIdentity(captured.daemon.pid);
  if (observed === undefined) return;
  expect(observed).toEqual(captured.daemon);
  expect((await readFile(`/proc/${String(captured.daemon.pid)}/cmdline`)).toString("hex")).toBe(
    captured.commandLine.toString("hex"),
  );
  const mismatch = `test-cleanup-mismatch-${randomUUID()}`;
  const guarded = await closeChildWithin(
    spawn(
      captured.daemon.executablePath,
      [
        "-N",
        "-S",
        captured.recoverySocket,
        "if-shell",
        "-F",
        `#{==:#{pid},${String(captured.daemon.pid)}}`,
        "kill-server",
        `display-message -p ${mismatch}`,
      ],
      { stdio: ["ignore", "pipe", "pipe"] },
    ),
    2_000,
  );
  if (guarded.code !== 0 || guarded.stdout === `${mismatch}\n`) {
    throw new Error(`test-owned tmux cleanup refused: ${guarded.stderr || guarded.stdout}`);
  }
  await waitForProcessExit(captured.daemon.pid);
  expect(await readDaemonIdentity(captured.daemon.pid)).toBeUndefined();
  const after = await lstat(captured.recoverySocket, { bigint: true });
  expect({ device: after.dev, inode: after.ino }).toEqual(captured.socketIdentity);
}

async function launchExactTmux(socketPath: string): Promise<number> {
  const launched = await closeChild(
    spawn(
      "tmux",
      [
        "-f",
        "/dev/null",
        "-S",
        socketPath,
        "new-session",
        "-d",
        "-P",
        "-F",
        "#{pid}",
        "-s",
        `replacement-${randomUUID().slice(0, 8)}`,
        "exec cat",
      ],
      { stdio: ["ignore", "pipe", "pipe"] },
    ),
  );
  if (launched.code !== 0) throw new Error(`tmux exact launch failed: ${launched.stderr}`);
  const pid = Number.parseInt(launched.stdout.trim(), 10);
  if (!Number.isSafeInteger(pid) || pid < 1) throw new Error("tmux exact launch returned bad PID");
  return pid;
}

async function waitForProcessExit(pid: number): Promise<void> {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (!processExists(pid)) return;
    // eslint-disable-next-line no-await-in-loop -- process exit is observed within one fixed test bound.
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(`process ${String(pid)} did not exit within the test bound`);
}

async function killExactTmux(socketPath: string, pid: number): Promise<void> {
  const recoverySocket = `${socketPath}.test-cleanup-${randomUUID()}`;
  const captured = await captureTmuxCleanup(pid, socketPath, recoverySocket);
  await terminateCapturedTmux(captured);
  const original = await lstat(socketPath, { bigint: true }).catch(
    (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined;
      throw error;
    },
  );
  if (original !== undefined) {
    expect({ device: original.dev, inode: original.ino }).toEqual(captured.socketIdentity);
    await unlink(socketPath);
  }
  const recovery = await lstat(recoverySocket, { bigint: true });
  expect({ device: recovery.dev, inode: recovery.ino }).toEqual(captured.socketIdentity);
  await unlink(recoverySocket);
}

function processExists(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") return false;
    throw error;
  }
}

describe("process identity", () => {
  test("parses field 22 after the final parenthesis without numeric coercion", () => {
    const line =
      "91 (tmux: odd ) server) S " +
      Array.from({ length: 18 }, (_, i) => `${i + 1}`).join(" ") +
      " 18446744073709551614 99";
    expect(parseProcStatStartTime(line)).toBe("18446744073709551614");
  });

  test("rejects record metadata owned by a different uid", () => {
    expect(() =>
      validateOwnedRecordMetadata(
        { isRegularFile: true, mode: 0o600, uid: 4242 },
        "fixture identity record",
        1000,
      ),
    ).toThrow("wrong uid");
  });
});

describe("worker and exact-root reaping", () => {
  test("discovers, promotes, and reaps a generation-authenticated launching fixture", async () => {
    const { parent, root } = await makeRoot("stale-launching-generation");
    const marker = join(parent, "launch.frame");
    const wrapper = await writeLaunchingHoldWrapper(parent, marker);
    const worker = await spawnLeakingWorker(root, "launching-hold", marker, {
      LIBTMUX_TEST_LAUNCH_WRAPPER: wrapper,
    });
    let daemonPid: number | undefined;
    let captured: CapturedTmuxCleanup | undefined;
    let socketPath: string | undefined;
    let wrapperPid: number | undefined;
    try {
      await waitForPath(marker);
      const [rawWrapperPid, frame] = (await readFile(marker, "utf8")).trim().split("\n");
      wrapperPid = Number(rawWrapperPid);
      [socketPath, daemonPid] = [frame?.split("\t")[0], Number(frame?.split("\t")[1])];
      expect(processExists(daemonPid)).toBe(true);
      if (socketPath === undefined) throw new Error("launch wrapper omitted the socket path");
      captured = await captureTmuxCleanup(
        daemonPid,
        socketPath,
        join(parent, "launching-recovery.sock"),
      );
      worker.kill("SIGKILL");
      await exitChildWithin(worker, 2_000);
      await waitForProcessExit(wrapperPid);

      const reservations = (await readdir(root)).filter((entry) => entry !== OWNER_RECORD_NAME);
      expect(reservations).toHaveLength(1);
      expect((await readFixtureRecord(join(root, reservations[0]!))).phase).toBe("launching");
      const report = await reapOwnedRunRoot(root);
      expect(report.leaks).toEqual([]);
      expect(report.rootRemoved).toBe(true);
      expect(processExists(daemonPid)).toBe(false);
    } finally {
      if (worker.exitCode === null && worker.signalCode === null) {
        worker.kill("SIGKILL");
        await exitChildWithin(worker, 2_000);
      }
      if (wrapperPid !== undefined) await waitForProcessExit(wrapperPid);
      if (captured !== undefined) await terminateCapturedTmux(captured);
      await reapOwnedRunRoot(root).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  }, 10_000);

  test("preserves stale launching evidence when the process generation mismatches", async () => {
    const { parent, root } = await makeRoot("stale-launching-generation-mismatch");
    const marker = join(parent, "launch.frame");
    const wrapper = await writeLaunchingHoldWrapper(parent, marker);
    const worker = await spawnLeakingWorker(root, "launching-hold", marker, {
      LIBTMUX_TEST_LAUNCH_WRAPPER: wrapper,
    });
    let captured: CapturedTmuxCleanup | undefined;
    let wrapperPid: number | undefined;
    try {
      await waitForPath(marker);
      const [rawWrapperPid, frame] = (await readFile(marker, "utf8")).trim().split("\n");
      wrapperPid = Number(rawWrapperPid);
      const socketPath = frame?.split("\t")[0];
      const daemonPid = Number(frame?.split("\t")[1]);
      if (socketPath === undefined || !Number.isSafeInteger(daemonPid)) {
        throw new Error("launch wrapper returned an invalid frame");
      }
      const authority = await captureTmuxCleanup(
        daemonPid,
        socketPath,
        join(parent, "launching-mismatch-recovery.sock"),
      );
      captured = authority;
      worker.kill("SIGKILL");
      await exitChildWithin(worker, 2_000);
      await waitForProcessExit(wrapperPid);

      const reservations = (await readdir(root)).filter((entry) => entry !== OWNER_RECORD_NAME);
      expect(reservations).toHaveLength(1);
      const reservationPath = join(root, reservations[0]!);
      const recordPath = join(reservationPath, "fixture.json");
      const originalRecord = JSON.parse(await readFile(recordPath, "utf8")) as {
        generation?: { name: string; value: string };
        phase?: string;
      };
      if (originalRecord.generation === undefined) {
        throw new Error("launching fixture lacks a durable generation");
      }
      expect(originalRecord.phase).toBe("launching");
      const mismatchedValue = "11111111-1111-4111-8111-111111111111";
      expect(originalRecord.generation.value).not.toBe(mismatchedValue);
      const mutatedRecord = `${JSON.stringify({
        ...originalRecord,
        generation: { ...originalRecord.generation, value: mismatchedValue },
      })}\n`;
      await writeFile(recordPath, mutatedRecord, { mode: 0o600 });
      const recordEntry = journalIdentity(await lstat(recordPath));
      const socketEntry = journalIdentity(await lstat(socketPath));

      const report = await reapOwnedRunRoot(root);

      expect(report.rootRemoved).toBe(false);
      expect(report.leaks.some((leak) => leak.includes("generation"))).toBe(true);
      expect(await readDaemonIdentity(daemonPid)).toEqual(authority.daemon);
      expect(await readFile(recordPath, "utf8")).toBe(mutatedRecord);
      expect(journalIdentity(await lstat(recordPath))).toEqual(recordEntry);
      expect(journalIdentity(await lstat(socketPath))).toEqual(socketEntry);
    } finally {
      if (worker.exitCode === null && worker.signalCode === null) {
        worker.kill("SIGKILL");
        await exitChildWithin(worker, 2_000);
      }
      if (wrapperPid !== undefined) await waitForProcessExit(wrapperPid);
      if (captured !== undefined) await terminateCapturedTmux(captured);
      await rm(parent, { force: true, recursive: true });
    }
  }, 10_000);

  test("refuses a fabricated non-tmux daemon record without signaling its process", async () => {
    const { parent, root } = await makeRoot("fabricated-non-tmux");
    const reservation = join(root, "fabricated");
    await mkdir(reservation, { mode: 0o700 });
    const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    const childClosed = closeChild(child);
    if (child.pid === undefined) throw new Error("test child has no PID");
    const identity = await readProcessIdentity(child.pid);
    if (identity === undefined) throw new Error("test child exited before identity capture");
    const owner = JSON.parse(await readFile(join(root, OWNER_RECORD_NAME), "utf8")) as {
      runId: string;
    };
    const socketPath = join(reservation, "s");
    const listener = await listenOnUnixSocket(socketPath);
    await writeFile(
      join(reservation, "fixture.json"),
      `${JSON.stringify({
        daemon: {
          ...identity,
          comm: "tmux: server",
          executablePath: await realpath(`/proc/${String(child.pid)}/exe`),
        },
        logicalSocketName: "fabricated",
        owner: await readProcessIdentity(process.pid),
        phase: "running",
        protocol: "libtmux-test-fixture-v2",
        runId: owner.runId,
        socketIdentity: journalIdentity(await lstat(socketPath)),
        socketPath,
        tmuxExecutable: "tmux",
      })}\n`,
      { mode: 0o600 },
    );
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report.leaks.some((leak) => /bad magic|protocol/u.test(leak))).toBe(true);
      expect(processExists(child.pid)).toBe(true);
    } finally {
      if (processExists(child.pid)) child.kill("SIGKILL");
      await childClosed.catch(() => undefined);
      await closeNetServer(listener);
      await unlink(socketPath).catch(() => undefined);
      await removeOwnedRoot(parent, root);
    }
  });

  test("refuses a fabricated stale record copied from a tmux daemon on another socket", async () => {
    const unrelatedRoot = await makeRoot("unrelated-tmux-root");
    const unrelated = await TestServer.create({ runRoot: unrelatedRoot.root });
    const stale = await makeRoot("fabricated-stale-tmux");
    const reservation = join(stale.root, "fabricated");
    await mkdir(reservation, { mode: 0o700 });
    const ownerPath = join(stale.root, OWNER_RECORD_NAME);
    const owner = JSON.parse(await readFile(ownerPath, "utf8")) as { runId: string };
    const daemon = await readDaemonIdentity(unrelated.daemonIdentity.pid);
    if (daemon === undefined) throw new Error("unrelated tmux daemon disappeared");
    const socketPath = join(reservation, "s");
    const listener = await listenOnUnixSocket(socketPath);
    await writeFile(
      join(reservation, "fixture.json"),
      `${JSON.stringify({
        daemon,
        logicalSocketName: "fabricated",
        owner: await readProcessIdentity(process.pid),
        phase: "running",
        protocol: "libtmux-test-fixture-v2",
        runId: owner.runId,
        socketIdentity: journalIdentity(await lstat(socketPath)),
        socketPath,
        tmuxExecutable: "tmux",
      })}\n`,
      { mode: 0o600 },
    );
    await writeFile(
      ownerPath,
      `${JSON.stringify({
        ...owner,
        owner: {
          pid: 2_147_483_000,
          startIdentity: "linux:00000000-0000-4000-8000-000000000000:1",
        },
      })}\n`,
      { mode: 0o600 },
    );
    try {
      const report = await reapStaleRunRoot(stale.root);
      expect(processExists(unrelated.daemonIdentity.pid)).toBe(true);
      expect(report.leaks.some((leak) => /bad magic|protocol/u.test(leak))).toBe(true);
      expect(
        (await unrelated.executeText(["display-message", "-p", "#{socket_path}"])).stdout,
      ).toEqual([unrelated.socketPath]);
    } finally {
      await closeNetServer(listener);
      await unlink(socketPath).catch(() => undefined);
      await unrelated.dispose().catch(() => undefined);
      await removeOwnedRoot(unrelatedRoot.parent, unrelatedRoot.root);
      await rm(stale.parent, { force: true, recursive: true });
    }
  });

  test("refuses to record another socket's tmux daemon for a legitimate reservation", async () => {
    const { parent, root } = await makeRoot("record-wrong-daemon");
    const unrelated = await TestServer.create({ runRoot: root });
    const reserved = await reserveFixture(root);
    const { attempt } = await beginSyntheticLaunch(reserved);
    const daemon = await readDaemonIdentity(unrelated.daemonIdentity.pid);
    if (daemon === undefined) throw new Error("unrelated tmux daemon disappeared");
    let recordError: unknown;
    try {
      try {
        await promoteFixtureLaunch(attempt, daemon.pid);
      } catch (error) {
        recordError = error;
      }
      expect(processExists(unrelated.daemonIdentity.pid)).toBe(true);
      expect(recordError).toBeInstanceOf(Error);
    } finally {
      await rollbackFixtureLaunchNotStarted(attempt).catch(() => undefined);
      await reapFixture(reserved.capability).catch(() => undefined);
      await unrelated.dispose().catch(() => undefined);
      await removeOwnedRoot(parent, root);
    }
  });

  test("rejects the legacy path-and-record phase writer before it can publish authority", async () => {
    const { parent, root } = await makeRoot("legacy-phase-writer");
    const reserved = await reserveFixture(root);
    try {
      await expect(
        Reflect.apply(beginFixtureLaunch, undefined, [
          reserved.recordPath,
          { bootstrapArgv: [], generation: { name: "invalid", value: "invalid" } },
        ]),
      ).rejects.toThrow("authenticated reservation capability");
      expect((await readFixtureRecord(reserved.reservationPath)).phase).toBe("reserved");
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("rejects a structurally copied reservation capability at runtime", async () => {
    const { parent, root } = await makeRoot("fake-writer-capability");
    const reserved = await reserveFixture(root);
    const fakeCapability = { ...reserved.capability };
    try {
      await expect(
        Reflect.apply(beginFixtureLaunch, undefined, [
          fakeCapability,
          { bootstrapArgv: [], generation: { name: "invalid", value: "invalid" } },
        ]),
      ).rejects.toThrow("authenticated reservation capability");
      expect((await readFixtureRecord(reserved.reservationPath)).phase).toBe("reserved");
    } finally {
      await reapFixture(reserved.capability).catch(() => undefined);
      await removeOwnedRoot(parent, root).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("rejects the legacy daemon writer without a launch-attempt capability", async () => {
    const { parent, root } = await makeRoot("legacy-daemon-writer");
    const reserved = await reserveFixture(root);
    try {
      await expect(
        Reflect.apply(promoteFixtureLaunch, undefined, [reserved.recordPath, process.pid]),
      ).rejects.toThrow("authenticated launch-attempt capability");
      expect((await readFixtureRecord(reserved.reservationPath)).phase).toBe("reserved");
    } finally {
      await reapFixture(reserved.capability);
      await removeOwnedRoot(parent, root);
    }
  });

  test("does not adopt an exact-path daemon with the wrong generation", async () => {
    const parent = await mkdtemp(join(tmpdir(), "x4-"));
    const root = join(parent, "r");
    await prepareRunRoot(root);
    const reserved = await reserveFixture(root);
    const { attempt, record: launching } = await beginSyntheticLaunch(reserved);
    const pid = await launchExactTmux(launching.socketPath);
    try {
      const report = await reapFixture(reserved.capability);
      expect(report.leaks.some((leak) => leak.includes("generation"))).toBe(true);
      expect(processExists(pid)).toBe(true);
      expect((await lstat(launching.socketPath)).isSocket()).toBe(true);
      expect((await readFixtureRecord(reserved.reservationPath)).phase).toBe("launching");
    } finally {
      await killExactTmux(launching.socketPath, pid);
      await unlink(launching.socketPath).catch(() => undefined);
      await rollbackFixtureLaunchNotStarted(attempt);
      await reapFixture(reserved.capability);
      await removeOwnedRoot(parent, root);
    }
  });

  for (const intendedState of ["live", "exited"] as const) {
    test(`preserves a foreign replacement socket when the recorded daemon is ${intendedState}`, async () => {
      const parent = await mkdtemp(join(tmpdir(), `ltx4-foreign-socket-${intendedState}-`));
      const root = join(parent, "root");
      const intendedRecoverySocket = join(parent, "intended.sock");
      const replacementRecoverySocket = join(parent, "replacement.sock");
      await prepareRunRoot(root);
      const intended = await TestServer.create({ runRoot: root });
      if (intendedState === "exited") {
        const killed = await closeChild(
          spawn("tmux", ["-N", "-S", intended.socketPath, "kill-server"], {
            stdio: ["ignore", "pipe", "pipe"],
          }),
        );
        if (killed.code !== 0) throw new Error(`intended tmux kill failed: ${killed.stderr}`);
        await waitForProcessExit(intended.daemonIdentity.pid);
      }
      await rename(intended.socketPath, intendedRecoverySocket);
      const replacementPid = await launchExactTmux(intended.socketPath);
      await link(intended.socketPath, replacementRecoverySocket);
      const replacementSocketIdentity = journalIdentity(await lstat(intended.socketPath));
      let cleanupError: unknown;
      try {
        await intended.dispose();
      } catch (error) {
        cleanupError = error;
      }
      try {
        expect(String(cleanupError)).toContain("foreign socket");
        if (intendedState === "live") {
          expect(processExists(intended.daemonIdentity.pid)).toBe(false);
        }
        expect(processExists(replacementPid)).toBe(true);
        expect(journalIdentity(await lstat(intended.socketPath))).toEqual(
          replacementSocketIdentity,
        );
        expect((await lstat(intended.recordPath)).isFile()).toBe(true);
        const replacementSocket = await closeChild(
          spawn("tmux", ["-N", "-S", intended.socketPath, "display-message", "-p", "#{pid}"], {
            stdio: ["ignore", "pipe", "pipe"],
          }),
        );
        expect(replacementSocket.stdout.trim()).toBe(String(replacementPid));
      } finally {
        await killExactTmux(replacementRecoverySocket, replacementPid);
        await unlink(replacementRecoverySocket).catch(() => undefined);
        await unlink(intendedRecoverySocket).catch(() => undefined);
        await unlink(intended.socketPath).catch(() => undefined);
        await rm(parent, { force: true, recursive: true });
      }
    }, 10_000);
  }

  test("fails closed on a version-one running record instead of inferring socket authority", async () => {
    const { parent, root } = await makeRoot("version-one-record");
    const server = await TestServer.create({ runRoot: root });
    const original = await readFile(server.recordPath, "utf8");
    const oldRecord = JSON.parse(original) as Record<string, unknown>;
    oldRecord.protocol = "libtmux-test-fixture-v1";
    delete oldRecord.socketIdentity;
    await writeFile(server.recordPath, `${JSON.stringify(oldRecord)}\n`, { mode: 0o600 });
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report.leaks.some((leak) => leak.includes("bad magic"))).toBe(true);
      expect(processExists(server.daemonIdentity.pid)).toBe(true);
      expect((await lstat(server.socketPath)).isSocket()).toBe(true);
      expect((await lstat(server.recordPath)).isFile()).toBe(true);
    } finally {
      if (
        await access(server.recordPath)
          .then(() => true)
          .catch(() => false)
      ) {
        await writeFile(server.recordPath, original, { mode: 0o600 });
        await server.dispose().catch(() => undefined);
      } else {
        await killExactTmux(server.socketPath, server.daemonIdentity.pid);
      }
      await rm(parent, { force: true, recursive: true });
    }
  });

  for (const mutation of ["reserved-with-daemon", "running-without-socket"] as const) {
    test(`rejects a fixture phase/authority mismatch: ${mutation}`, async () => {
      const { parent, root } = await makeRoot(`phase-authority-${mutation}`);
      const server = await TestServer.create({ runRoot: root });
      const original = await readFile(server.recordPath, "utf8");
      const tampered = JSON.parse(original) as Record<string, unknown>;
      if (mutation === "reserved-with-daemon") {
        tampered.phase = "reserved";
        delete tampered.socketIdentity;
      } else {
        tampered.phase = "running";
        delete tampered.socketIdentity;
      }
      await writeFile(server.recordPath, `${JSON.stringify(tampered)}\n`, { mode: 0o600 });
      try {
        await expect(readFixtureRecord(server.reservationPath)).rejects.toThrow(
          /fixture identity record/u,
        );
        expect(processExists(server.daemonIdentity.pid)).toBe(true);
      } finally {
        await writeFile(server.recordPath, original, { mode: 0o600 });
        await server.dispose().catch(() => undefined);
        await removeOwnedRoot(parent, root).catch(() => undefined);
        await rm(parent, { force: true, recursive: true });
      }
    });
  }

  for (const order of ["fixture-first", "fixture-last"] as const) {
    test(`rejects ambiguous repeated socket selectors with the fixture ${order}`, async () => {
      const { parent, root } = await makeRoot(`repeated-selector-${order}`);
      const reserved = await reserveFixture(root);
      const otherSocket = join(parent, "other.sock");
      const launch = syntheticLaunchInput(reserved.record);
      const bootstrapArgv = [...launch.bootstrapArgv];
      const insertion = order === "fixture-first" ? 5 : 3;
      bootstrapArgv.splice(insertion, 0, "-S", otherSocket);
      try {
        await expect(
          beginFixtureLaunch(reserved.capability, {
            bootstrapArgv,
            generation: launch.generation,
          }),
        ).rejects.toThrow(/bootstrap argv/u);
        expect((await readFixtureRecord(reserved.reservationPath)).phase).toBe("reserved");
      } finally {
        await reapFixture(reserved.capability);
        await removeOwnedRoot(parent, root);
      }
    });
  }

  test("standalone stale reaper refuses a fixture under a live owner", async () => {
    const { parent, root } = await makeRoot("live-owner-reaper");
    const server = await TestServer.create({ runRoot: root });
    try {
      const reaper = spawn("bun", [reaperPath, "--run-root", root], {
        cwd: tsRoot,
        stdio: ["ignore", "pipe", "pipe"],
      });
      const result = await closeChildWithin(reaper, 2_000);
      expect(result.code).not.toBe(0);
      expect(result.stderr).toContain("live owner");
      expect(processExists(server.daemonIdentity.pid)).toBe(true);
      expect((await stat(server.socketPath)).isSocket()).toBe(true);
    } finally {
      await server.dispose().catch(() => undefined);
      await removeOwnedRoot(parent, root);
    }
  });

  for (const signal of ["SIGTERM", "SIGKILL"] as const) {
    test(`reaps a fixture abandoned by a worker killed with ${signal}`, async () => {
      const { parent, root } = await makeRoot(`worker-${signal}`);
      const marker = join(parent, "ready.json");
      const child = await spawnLeakingWorker(root, "hold", marker);
      try {
        await waitForPath(marker);
        const state = JSON.parse(await readFile(marker, "utf8")) as { daemonPid: number };
        child.kill(signal);
        const closed = await closeChild(child);
        expect(
          closed.signal === signal || closed.code === 128 + (signal === "SIGTERM" ? 15 : 9),
        ).toBe(true);
        expect(processExists(state.daemonPid)).toBe(true);

        expect((await reapOwnedRunRoot(root)).leaks).toEqual([]);
        expect(processExists(state.daemonPid)).toBe(false);
        await expect(stat(root)).rejects.toMatchObject({ code: "ENOENT" });
      } finally {
        if (child.exitCode === null && child.signalCode === null) {
          child.kill("SIGKILL");
          await closeChild(child).catch(() => undefined);
        }
        await removeOwnedRoot(parent, root);
      }
    }, 10_000);
  }

  test("enumerates only the exact run root", async () => {
    const { parent, root } = await makeRoot("exact");
    const sibling = join(parent, "exact-sibling");
    await mkdir(sibling, { mode: 0o700 });
    await writeFile(join(sibling, "sentinel"), "keep");
    try {
      expect((await reapOwnedRunRoot(root)).leaks).toEqual([]);
      expect(await readFile(join(sibling, "sentinel"), "utf8")).toBe("keep");
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("refuses broad, relative, missing-magic, and symlink run roots", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-root-guard-"));
    const ordinary = join(parent, "ordinary");
    const linked = join(parent, "linked");
    await mkdir(ordinary, { mode: 0o700 });
    await writeFile(join(ordinary, "sentinel"), "keep");
    await symlink(ordinary, linked);
    try {
      await expect(reapOwnedRunRoot("relative-root")).rejects.toThrow("absolute");
      await expect(reapOwnedRunRoot("/")).rejects.toThrow("unsafe run root");
      await expect(reapOwnedRunRoot(tmpdir())).rejects.toThrow("unsafe run root");
      await expect(reapOwnedRunRoot(ordinary)).rejects.toThrow("owner record");
      await expect(reapOwnedRunRoot(linked)).rejects.toThrow("symlink");
      expect(await readFile(join(ordinary, "sentinel"), "utf8")).toBe("keep");
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("rejects a canonical-looking root reached through a symlinked parent", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-parent-link-"));
    const realParent = join(parent, "real");
    const linkedParent = join(parent, "linked");
    await mkdir(realParent, { mode: 0o700 });
    await symlink(realParent, linkedParent);
    const root = join(linkedParent, "run");
    try {
      await expect(prepareRunRoot(root)).rejects.toThrow(/symlink|canonical/u);
      await expect(stat(join(realParent, "run"))).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("validates owner and fixture record file ownership metadata before reading", async () => {
    const { parent, root } = await makeRoot("record-metadata");
    const ownerPath = join(root, OWNER_RECORD_NAME);
    const ownerBackup = join(parent, "owner-backup");
    await copyFile(ownerPath, ownerBackup);
    await unlink(ownerPath);
    await symlink(ownerBackup, ownerPath);
    try {
      await expect(reapOwnedRunRoot(root)).rejects.toThrow(/owner.*symlink|regular file|ELOOP/u);
      expect((await lstat(ownerPath)).isSymbolicLink()).toBe(true);
    } finally {
      await unlink(ownerPath).catch(() => undefined);
      try {
        await stat(root);
        await copyFile(ownerBackup, ownerPath);
        await chmod(ownerPath, 0o600);
        await removeOwnedRoot(parent, root);
      } catch {
        await rm(parent, { force: true, recursive: true });
      }
    }
  });

  test("preserves socket and identity evidence when a reservation has unexpected entries", async () => {
    const { parent, root } = await makeRoot("evidence-order");
    const server = await TestServer.create({ runRoot: root });
    const unexpected = join(server.reservationPath, "unexpected");
    await writeFile(unexpected, "keep");
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report.leaks.some((leak) => leak.includes("unexpected"))).toBe(true);
      expect((await stat(server.socketPath)).isSocket()).toBe(true);
      expect((await stat(server.recordPath)).isFile()).toBe(true);
      expect(processExists(server.daemonIdentity.pid)).toBe(true);
    } finally {
      await unlink(unexpected);
      await server.dispose().catch(() => undefined);
      await removeOwnedRoot(parent, root);
    }
  });

  for (const corruption of ["run-id", "mode", "symlink"] as const) {
    test(`refuses a fixture record with ${corruption} corruption before signaling`, async () => {
      const { parent, root } = await makeRoot(`fixture-record-${corruption}`);
      const server = await TestServer.create({ runRoot: root });
      const original = await readFile(server.recordPath, "utf8");
      const backup = join(parent, `fixture-${corruption}.json`);
      try {
        if (corruption === "run-id") {
          const record = JSON.parse(original) as FixtureRecord;
          await writeFile(
            server.recordPath,
            `${JSON.stringify({ ...record, runId: randomUUID() })}\n`,
            { mode: 0o600 },
          );
        } else if (corruption === "mode") {
          await chmod(server.recordPath, 0o644);
        } else {
          await copyFile(server.recordPath, backup);
          await unlink(server.recordPath);
          await symlink(backup, server.recordPath);
        }
        await expect(server.dispose()).rejects.toThrow();
        expect(processExists(server.daemonIdentity.pid)).toBe(true);
        expect((await stat(server.socketPath)).isSocket()).toBe(true);
      } finally {
        await unlink(server.recordPath).catch(() => undefined);
        await writeFile(server.recordPath, original, { mode: 0o600 });
        await reapOwnedRunRoot(root).catch(() => undefined);
        await rm(parent, { force: true, recursive: true });
      }
    });
  }

  test("does not follow a reservation symlink outside the exact root", async () => {
    const { parent, root } = await makeRoot("symlink-child");
    const external = join(parent, "external");
    await mkdir(external, { mode: 0o700 });
    await writeFile(join(external, "sentinel"), "keep");
    await symlink(external, join(root, "linked-reservation"));
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report.leaks.some((leak) => leak.includes("symlink"))).toBe(true);
      expect(await readFile(join(external, "sentinel"), "utf8")).toBe("keep");
    } finally {
      await rm(join(root, "linked-reservation"), { force: true });
      await reapOwnedRunRoot(root);
      await rm(parent, { force: true, recursive: true });
    }
  });
});

describe("stale-root preflight", () => {
  test("preserves version-one owner evidence without migration or cleanup", async () => {
    const { parent, root } = await makeRoot("legacy-owner-v1");
    const ownerPath = join(root, OWNER_RECORD_NAME);
    const currentOwner = await readFile(ownerPath, "utf8");
    const parsed = JSON.parse(currentOwner) as {
      owner: { pid: number; startIdentity: string };
      runId: string;
    };
    const legacy = `${JSON.stringify({
      owner: {
        pid: parsed.owner.pid,
        startIdentity: "linux:00000000-0000-4000-8000-000000000000:1",
      },
      protocol: "libtmux-test-run-v1",
      runId: parsed.runId,
    })}\n`;
    await writeFile(ownerPath, legacy, { mode: 0o600 });
    const ownerEntry = journalIdentity(await lstat(ownerPath));
    try {
      await expect(reapStaleRunRoot(root)).rejects.toThrow(/bad magic|protocol/u);
      expect(await readFile(ownerPath, "utf8")).toBe(legacy);
      expect(journalIdentity(await lstat(ownerPath))).toEqual(ownerEntry);
      expect((await stat(root)).isDirectory()).toBe(true);
    } finally {
      await writeFile(ownerPath, currentOwner, { mode: 0o600 }).catch(() => undefined);
      await reapOwnedRunRoot(root).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("preserves a version-two fixture record without normalization or deletion", async () => {
    const { parent, root } = await makeRoot("legacy-fixture-v2");
    const owner = JSON.parse(await readFile(join(root, OWNER_RECORD_NAME), "utf8")) as {
      runId: string;
    };
    const reservationPath = join(root, "t-legacy-00000000-000");
    const recordPath = join(reservationPath, "fixture.json");
    await mkdir(reservationPath, { mode: 0o700 });
    const identity = await readProcessIdentity(process.pid);
    if (identity === undefined) throw new Error("test process identity disappeared");
    const legacy = `${JSON.stringify({
      logicalSocketName: basename(reservationPath),
      owner: identity,
      phase: "reserved",
      protocol: "libtmux-test-fixture-v2",
      runId: owner.runId,
      socketPath: join(reservationPath, "s"),
      tmuxExecutable: "tmux",
    })}\n`;
    await writeFile(recordPath, legacy, { flag: "wx", mode: 0o600 });
    const recordEntry = journalIdentity(await lstat(recordPath));
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report.rootRemoved).toBe(false);
      expect(report.leaks.some((leak) => /bad magic|protocol/u.test(leak))).toBe(true);
      expect(await readFile(recordPath, "utf8")).toBe(legacy);
      expect(journalIdentity(await lstat(recordPath))).toEqual(recordEntry);
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("preserves a version-two cleanup journal and its reservation", async () => {
    const { parent, root } = await makeRoot("legacy-journal-v2");
    const owner = JSON.parse(await readFile(join(root, OWNER_RECORD_NAME), "utf8")) as {
      runId: string;
    };
    const identity = await readProcessIdentity(process.pid);
    if (identity === undefined) throw new Error("test process identity disappeared");
    const logicalSocketName = "t-journal-00000000-000";
    const reservationPath = join(root, logicalSocketName);
    const recordPath = join(reservationPath, "fixture.json");
    const socketPath = join(reservationPath, "s");
    await mkdir(reservationPath, { mode: 0o700 });
    const record = `${JSON.stringify({
      logicalSocketName,
      owner: identity,
      phase: "reserved",
      protocol: "libtmux-test-fixture-v2",
      runId: owner.runId,
      socketPath,
      tmuxExecutable: "tmux",
    })}\n`;
    await writeFile(recordPath, record, { flag: "wx", mode: 0o600 });
    const escrow = join(root, `.fixture-escrow-${logicalSocketName}.${owner.runId}`);
    await mkdir(escrow, { mode: 0o700 });
    const journalPath = join(escrow, "journal.json");
    const journal = `${JSON.stringify({
      logicalSocketName,
      protocol: "libtmux-fixture-escrow-v2",
      record: journalIdentity(await lstat(recordPath)),
      recordDigest: createHash("sha256").update(record).digest("hex"),
      recordPath,
      reservation: journalIdentity(await lstat(reservationPath)),
      reservationPath,
      runId: owner.runId,
      socketPath,
    })}\n`;
    await writeFile(journalPath, journal, { flag: "wx", mode: 0o600 });
    const recordEntry = journalIdentity(await lstat(recordPath));
    const journalEntry = journalIdentity(await lstat(journalPath));
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report.rootRemoved).toBe(false);
      expect(report.leaks.some((leak) => /bad magic|protocol/u.test(leak))).toBe(true);
      expect(await readFile(journalPath, "utf8")).toBe(journal);
      expect(await readFile(recordPath, "utf8")).toBe(record);
      expect(journalIdentity(await lstat(journalPath))).toEqual(journalEntry);
      expect(journalIdentity(await lstat(recordPath))).toEqual(recordEntry);
      expect((await stat(reservationPath)).isDirectory()).toBe(true);
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("preserves a committed live version-two journal without signaling or unlinking", async () => {
    const { parent, root } = await makeRoot("legacy-live-journal-v2");
    const owner = JSON.parse(await readFile(join(root, OWNER_RECORD_NAME), "utf8")) as {
      runId: string;
    };
    const ownerIdentity = await readProcessIdentity(process.pid);
    if (ownerIdentity === undefined) throw new Error("test process identity disappeared");
    const logicalSocketName = "t-live-v2-00000000-000";
    const reservationPath = join(root, logicalSocketName);
    const recordPath = join(reservationPath, "fixture.json");
    const socketPath = join(reservationPath, "s");
    const recoverySocket = join(parent, "live-v2-recovery.sock");
    const escrow = join(root, `.fixture-escrow-${logicalSocketName}.${owner.runId}`);
    const movedReservation = join(escrow, "reservation");
    const movedRecord = join(movedReservation, "fixture.json");
    const movedSocket = join(movedReservation, "s");
    let captured: CapturedTmuxCleanup | undefined;
    await mkdir(reservationPath, { mode: 0o700 });
    const daemonPid = await launchExactTmux(socketPath);
    const daemon = await readDaemonIdentity(daemonPid);
    if (daemon === undefined) throw new Error("legacy live tmux daemon disappeared");
    try {
      captured = await captureTmuxCleanup(daemonPid, socketPath, recoverySocket);
      const socketIdentity = journalIdentity(await lstat(socketPath));
      const record = `${JSON.stringify({
        daemon,
        logicalSocketName,
        owner: ownerIdentity,
        phase: "running",
        protocol: "libtmux-test-fixture-v2",
        runId: owner.runId,
        socketIdentity,
        socketPath,
        tmuxExecutable: daemon.executablePath,
      })}\n`;
      await writeFile(recordPath, record, { flag: "wx", mode: 0o600 });
      const recordEntry = journalIdentity(await lstat(recordPath));
      const reservationEntry = journalIdentity(await lstat(reservationPath));
      await mkdir(escrow, { mode: 0o700 });
      const journalPath = join(escrow, "journal.json");
      const journal = `${JSON.stringify({
        logicalSocketName,
        protocol: "libtmux-fixture-escrow-v2",
        record: recordEntry,
        recordDigest: createHash("sha256").update(record).digest("hex"),
        recordPath,
        reservation: reservationEntry,
        reservationPath,
        runId: owner.runId,
        socket: socketIdentity,
        socketPath,
      })}\n`;
      await writeFile(journalPath, journal, { flag: "wx", mode: 0o600 });
      const journalEntry = journalIdentity(await lstat(journalPath));
      await rename(reservationPath, movedReservation);
      const movedRecordEntry = journalIdentity(await lstat(movedRecord));
      const movedSocketEntry = journalIdentity(await lstat(movedSocket));

      const report = await reapOwnedRunRoot(root);

      expect(report.rootRemoved).toBe(false);
      expect(report.leaks.some((leak) => /bad magic|protocol/u.test(leak))).toBe(true);
      expect(await readDaemonIdentity(daemonPid)).toEqual(daemon);
      expect(await readFile(movedRecord, "utf8")).toBe(record);
      expect(await readFile(journalPath, "utf8")).toBe(journal);
      expect(journalIdentity(await lstat(movedRecord))).toEqual(movedRecordEntry);
      expect(journalIdentity(await lstat(movedSocket))).toEqual(movedSocketEntry);
      expect(journalIdentity(await lstat(journalPath))).toEqual(journalEntry);
    } finally {
      if (captured !== undefined) await terminateCapturedTmux(captured);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("refuses a root owned by the same live process identity", async () => {
    const { parent, root } = await makeRoot("live-owner");
    try {
      await expect(prepareRunRoot(root)).rejects.toThrow("live owner");
    } finally {
      await removeOwnedRoot(parent, root);
    }
  });

  test("reaps a dead owner and republishes the root", async () => {
    const { parent, root } = await makeRoot("dead-owner");
    const ownerPath = join(root, OWNER_RECORD_NAME);
    const owner = JSON.parse(await readFile(ownerPath, "utf8")) as Record<string, unknown>;
    owner.owner = {
      pid: 2_147_483_000,
      startIdentity: "linux:00000000-0000-4000-8000-000000000000:1",
    };
    await writeFile(ownerPath, `${JSON.stringify(owner)}\n`);
    try {
      await prepareRunRoot(root);
      const current = JSON.parse(await readFile(ownerPath, "utf8")) as {
        owner: { pid: number };
      };
      expect(current.owner.pid).toBe(process.pid);
    } finally {
      await removeOwnedRoot(parent, root);
    }
  });

  test("recovers the deterministic owner escrow left by interrupted finalization", async () => {
    const { parent, root } = await makeRoot("owner-escrow-recovery");
    const escrow = `${root}.owner-escrow`;
    await mkdir(escrow, { mode: 0o700 });
    await rename(join(root, OWNER_RECORD_NAME), join(escrow, OWNER_RECORD_NAME));
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report).toEqual({ leaks: [], reservationsFound: 0, rootRemoved: true });
      await expect(access(root)).rejects.toMatchObject({ code: "ENOENT" });
      await expect(access(escrow)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(parent, { force: true, recursive: true });
      await rm(escrow, { force: true, recursive: true });
    }
  });

  test("recovers matching canonical and escrow owner hardlinks", async () => {
    const { parent, root } = await makeRoot("owner-hardlink-recovery");
    const escrow = `${root}.owner-escrow`;
    await mkdir(escrow, { mode: 0o700 });
    await link(join(root, OWNER_RECORD_NAME), join(escrow, OWNER_RECORD_NAME));
    try {
      expect((await reapOwnedRunRoot(root)).rootRemoved).toBe(true);
      await expect(access(escrow)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(parent, { force: true, recursive: true });
      await rm(escrow, { force: true, recursive: true });
    }
  });

  test("preserves conflicting canonical and escrow owner inodes", async () => {
    const { parent, root } = await makeRoot("owner-hardlink-conflict");
    const ownerPath = join(root, OWNER_RECORD_NAME);
    const ownerText = await readFile(ownerPath, "utf8");
    const escrow = `${root}.owner-escrow`;
    const escrowOwner = join(escrow, OWNER_RECORD_NAME);
    await mkdir(escrow, { mode: 0o700 });
    await link(ownerPath, escrowOwner);
    await unlink(ownerPath);
    await writeFile(ownerPath, ownerText, { flag: "wx", mode: 0o600 });
    try {
      await expect(reapOwnedRunRoot(root)).rejects.toThrow(/owner escrow|inode|changed/u);
      expect((await stat(ownerPath)).isFile()).toBe(true);
      expect((await stat(escrowOwner)).isFile()).toBe(true);
    } finally {
      await unlink(ownerPath).catch(() => undefined);
      await link(escrowOwner, ownerPath).catch(() => undefined);
      await unlink(escrowOwner).catch(() => undefined);
      await rmdir(escrow).catch(() => undefined);
      await reapOwnedRunRoot(root).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("removes an empty owner escrow left before the owner record move", async () => {
    const { parent, root } = await makeRoot("empty-owner-escrow");
    const escrow = `${root}.owner-escrow`;
    await mkdir(escrow, { mode: 0o700 });
    try {
      expect((await reapOwnedRunRoot(root)).rootRemoved).toBe(true);
      await expect(access(escrow)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(parent, { force: true, recursive: true });
      await rm(escrow, { force: true, recursive: true });
    }
  });

  test("removes an empty detached owner escrow left after its record unlink", async () => {
    const { parent, root } = await makeRoot("empty-detached-owner-escrow");
    const escrow = `${root}.owner-escrow`;
    await rm(root, { force: true, recursive: true });
    await mkdir(escrow, { mode: 0o700 });
    try {
      expect((await reapStaleRunRoot(root)).rootRemoved).toBe(true);
      await expect(access(escrow)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(parent, { force: true, recursive: true });
      await rm(escrow, { force: true, recursive: true });
    }
  });

  for (const boundary of [
    "empty-before-journal",
    "journal-temp-written",
    "journal-written-before-moves",
    "reservation-moved",
    "record-unlinked",
    "reservation-removed",
    "journal-unlinked",
  ] as const) {
    test(`recovers fixture escrow after ${boundary}`, async () => {
      const { parent, root } = await makeRoot(`fixture-escrow-${boundary}`);
      const reserved = await reserveFixture(root);
      const escrow = join(
        root,
        `.fixture-escrow-${basename(reserved.reservationPath)}.${reserved.record.runId}`,
      );
      await mkdir(escrow, { mode: 0o700 });
      if (boundary === "journal-temp-written") {
        await writeFile(join(escrow, ".journal.tmp"), '{"partial":', {
          flag: "wx",
          mode: 0o600,
        });
      } else if (boundary !== "empty-before-journal") {
        await writeFixtureEscrowJournal(reserved, escrow);
      }
      const movedReservation = join(escrow, "reservation");
      if (
        boundary !== "empty-before-journal" &&
        boundary !== "journal-temp-written" &&
        boundary !== "journal-written-before-moves"
      ) {
        await rename(reserved.reservationPath, movedReservation);
      }
      if (boundary === "record-unlinked") {
        await unlink(join(movedReservation, "fixture.json"));
      }
      if (boundary === "reservation-removed" || boundary === "journal-unlinked") {
        await unlink(join(movedReservation, "fixture.json"));
        await unlink(join(movedReservation, "s")).catch(() => undefined);
        await rmdir(movedReservation);
      }
      if (boundary === "journal-unlinked") {
        await unlink(join(escrow, "journal.json"));
      }
      try {
        const report = await reapOwnedRunRoot(root);
        expect(report.leaks).toEqual([]);
        expect(report.rootRemoved).toBe(true);
        await expect(access(escrow)).rejects.toMatchObject({ code: "ENOENT" });
      } finally {
        await rm(parent, { force: true, recursive: true });
      }
    });
  }

  test("recovers a running fixture escrow after its authenticated socket is removed", async () => {
    const { parent, root } = await makeRoot("fixture-escrow-socket-unlinked");
    const server = await TestServer.create({ runRoot: root });
    const record = await readFixtureRecord(server.reservationPath);
    const escrow = join(root, `.fixture-escrow-${server.logicalSocketName}.${record.runId}`);
    const movedReservation = join(escrow, "reservation");
    const stopped = await closeChild(
      spawn(server.tmuxExecutable, ["-N", "-S", server.socketPath, "kill-server"], {
        stdio: ["ignore", "pipe", "pipe"],
      }),
    );
    if (stopped.code !== 0) throw new Error(`journal fixture stop failed: ${stopped.stderr}`);
    await waitForProcessExit(server.daemonIdentity.pid);
    await mkdir(escrow, { mode: 0o700 });
    await writeFixtureEscrowJournal(
      {
        record,
        recordPath: server.recordPath,
        reservationPath: server.reservationPath,
      },
      escrow,
    );
    await rename(server.reservationPath, movedReservation);
    await unlink(join(movedReservation, "s"));
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report.leaks).toEqual([]);
      expect(report.rootRemoved).toBe(true);
      await expect(access(escrow)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });

  for (const location of ["uncommitted", "committed"] as const) {
    for (const socketState of ["with-socket", "record-only"] as const) {
      test(`preserves a ${location} launching journal ${socketState}`, async () => {
        const { parent, root } = await makeRoot(`launching-journal-${location}-${socketState}`);
        const reserved = await reserveFixture(root);
        const launched = await beginSyntheticLaunch(reserved);
        const launchingReservation = { ...reserved, record: launched.record };
        const escrow = join(
          root,
          `.fixture-escrow-${basename(reserved.reservationPath)}.${reserved.record.runId}`,
        );
        let listener: ClosableServer | undefined;
        try {
          if (socketState === "with-socket") {
            listener = await listenOnUnixSocket(launched.record.socketPath);
          }
          await mkdir(escrow, { mode: 0o700 });
          await writeFixtureEscrowJournal(launchingReservation, escrow);
          const evidenceReservation =
            location === "committed" ? join(escrow, "reservation") : reserved.reservationPath;
          if (location === "committed") {
            await rename(reserved.reservationPath, evidenceReservation);
          }
          const evidenceRecord = join(evidenceReservation, "fixture.json");
          const evidenceSocket = join(evidenceReservation, "s");
          const journalPath = join(escrow, "journal.json");
          const [recordText, journalText] = await Promise.all([
            readFile(evidenceRecord, "utf8"),
            readFile(journalPath, "utf8"),
          ]);

          const report = await reapOwnedRunRoot(root);

          expect(report.leaks.some((leak) => leak.includes("launching"))).toBe(true);
          expect(report.rootRemoved).toBe(false);
          expect(await readFile(journalPath, "utf8")).toBe(journalText);
          expect(await readFile(evidenceRecord, "utf8")).toBe(recordText);
          if (socketState === "with-socket") {
            expect((await lstat(evidenceSocket)).isSocket()).toBe(true);
          }
        } finally {
          await closeNetServer(listener);
          await rm(parent, { force: true, recursive: true });
        }
      });
    }
  }

  for (const location of ["uncommitted", "committed"] as const) {
    test(`preserves a ${location} journal whose fixture controller differs from its owner`, async () => {
      const parent = await mkdtemp(join(tmpdir(), "x4-"));
      const root = join(parent, "r");
      const recoverySocket = join(parent, "recovery.sock");
      await prepareRunRoot(root);
      const server = await TestServer.create({ runRoot: root });
      const record = await readFixtureRecord(server.reservationPath);
      if (record.phase !== "running") throw new Error("fixture did not publish running authority");
      const captured = await captureTmuxCleanup(
        server.daemonIdentity.pid,
        server.socketPath,
        recoverySocket,
      );
      const changedRecord: typeof record = {
        ...record,
        controller: {
          ...record.controller,
          fileIdentity: {
            ...record.controller.fileIdentity,
            inode: String(BigInt(record.controller.fileIdentity.inode) + 1n),
          },
        },
      };
      await writeFile(server.recordPath, `${JSON.stringify(changedRecord)}\n`, { mode: 0o600 });
      const escrow = join(root, `.fixture-escrow-${server.logicalSocketName}.${record.runId}`);
      await mkdir(escrow, { mode: 0o700 });
      await writeFixtureEscrowJournal(
        {
          record: changedRecord,
          recordPath: server.recordPath,
          reservationPath: server.reservationPath,
        },
        escrow,
      );
      const evidenceReservation =
        location === "committed" ? join(escrow, "reservation") : server.reservationPath;
      if (location === "committed") {
        await rename(server.reservationPath, evidenceReservation);
      }
      const evidenceRecord = join(evidenceReservation, "fixture.json");
      const evidenceSocket = join(evidenceReservation, "s");
      const journalPath = join(escrow, "journal.json");
      const [recordBytes, journalBytes] = await Promise.all([
        readFile(evidenceRecord, "utf8"),
        readFile(journalPath, "utf8"),
      ]);
      const [recordEntry, journalEntry, socketEntry] = await Promise.all([
        lstat(evidenceRecord).then(journalIdentity),
        lstat(journalPath).then(journalIdentity),
        lstat(evidenceSocket).then(journalIdentity),
      ]);
      try {
        const report = await reapOwnedRunRoot(root);

        expect(await readDaemonIdentity(server.daemonIdentity.pid)).toEqual(captured.daemon);
        expect(await readFile(evidenceRecord, "utf8")).toBe(recordBytes);
        expect(journalIdentity(await lstat(evidenceRecord))).toEqual(recordEntry);
        expect(await readFile(journalPath, "utf8")).toBe(journalBytes);
        expect(journalIdentity(await lstat(journalPath))).toEqual(journalEntry);
        expect(journalIdentity(await lstat(evidenceSocket))).toEqual(socketEntry);
        expect(report.leaks.some((leak) => leak.includes("controller"))).toBe(true);
        expect(report.rootRemoved).toBe(false);
      } finally {
        if (processExists(server.daemonIdentity.pid)) {
          await terminateCapturedTmux(captured);
          await waitForProcessExit(server.daemonIdentity.pid);
        }
        await rm(parent, { force: true, recursive: true });
      }
    });
  }

  test("preserves an impossible committed socket-only fixture escrow", async () => {
    const parent = await mkdtemp(join(tmpdir(), "x4-"));
    const root = join(parent, "r");
    await prepareRunRoot(root);
    const server = await TestServer.create({ runRoot: root });
    const record = await readFixtureRecord(server.reservationPath);
    const escrow = join(root, `.fixture-escrow-${server.logicalSocketName}.${record.runId}`);
    const movedReservation = join(escrow, "reservation");
    const movedSocket = join(movedReservation, "s");
    const recoverySocket = join(parent, "recovery.sock");
    try {
      const captured = await captureTmuxCleanup(
        server.daemonIdentity.pid,
        server.socketPath,
        recoverySocket,
      );
      await terminateCapturedTmux(captured);
      await unlink(recoverySocket);
      await mkdir(escrow, { mode: 0o700 });
      await writeFixtureEscrowJournal(
        {
          record,
          recordPath: server.recordPath,
          reservationPath: server.reservationPath,
        },
        escrow,
      );
      await rename(server.reservationPath, movedReservation);
      await unlink(join(movedReservation, "fixture.json"));
      const socketIdentity = journalIdentity(await lstat(movedSocket));
      const journalText = await readFile(join(escrow, "journal.json"), "utf8");

      const report = await reapOwnedRunRoot(root);

      expect(report.leaks.some((leak) => leak.includes("socket-only"))).toBe(true);
      expect(report.rootRemoved).toBe(false);
      expect(journalIdentity(await lstat(movedSocket))).toEqual(socketIdentity);
      expect(await readFile(join(escrow, "journal.json"), "utf8")).toBe(journalText);
    } finally {
      await unlink(recoverySocket).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("verifies a committed record before unlinking its journaled socket", async () => {
    const parent = await mkdtemp(join(tmpdir(), "x4-"));
    const root = join(parent, "r");
    await prepareRunRoot(root);
    const server = await TestServer.create({ runRoot: root });
    const record = await readFixtureRecord(server.reservationPath);
    const escrow = join(root, `.fixture-escrow-${server.logicalSocketName}.${record.runId}`);
    const movedReservation = join(escrow, "reservation");
    const movedRecord = join(movedReservation, "fixture.json");
    const movedSocket = join(movedReservation, "s");
    const recoverySocket = join(parent, "recovery.sock");
    await link(server.socketPath, recoverySocket);
    try {
      await mkdir(escrow, { mode: 0o700 });
      await writeFixtureEscrowJournal(
        {
          record,
          recordPath: server.recordPath,
          reservationPath: server.reservationPath,
        },
        escrow,
      );
      await rename(server.reservationPath, movedReservation);
      await writeFile(movedRecord, '{"changed":true}\n', { mode: 0o600 });
      const socketIdentity = journalIdentity(await lstat(movedSocket));
      const journalText = await readFile(join(escrow, "journal.json"), "utf8");

      const report = await reapOwnedRunRoot(root);

      expect(report.leaks.some((leak) => leak.includes("digest changed"))).toBe(true);
      expect(report.rootRemoved).toBe(false);
      expect(journalIdentity(await lstat(movedSocket))).toEqual(socketIdentity);
      expect(await readFile(movedRecord, "utf8")).toBe('{"changed":true}\n');
      expect(await readFile(join(escrow, "journal.json"), "utf8")).toBe(journalText);
    } finally {
      if (processExists(server.daemonIdentity.pid)) {
        await killExactTmux(recoverySocket, server.daemonIdentity.pid);
        await waitForProcessExit(server.daemonIdentity.pid);
      }
      await unlink(recoverySocket).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("preserves unexpected fixture escrow contents", async () => {
    const { parent, root } = await makeRoot("fixture-escrow-unexpected");
    const reserved = await reserveFixture(root);
    const escrow = join(
      root,
      `.fixture-escrow-${basename(reserved.reservationPath)}.${reserved.record.runId}`,
    );
    await mkdir(escrow, { mode: 0o700 });
    await writeFixtureEscrowJournal(reserved, escrow);
    await writeFile(join(escrow, "sentinel"), "keep", { mode: 0o600 });
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report.leaks.some((leak) => leak.includes("unexpected entries"))).toBe(true);
      expect(await readFile(join(escrow, "sentinel"), "utf8")).toBe("keep");
      expect(await readFile(reserved.recordPath, "utf8")).toContain(reserved.record.runId);
    } finally {
      await unlink(join(escrow, "sentinel")).catch(() => undefined);
      await rmdir(escrow).catch(() => undefined);
      await reapOwnedRunRoot(root).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("preserves a fixture escrow whose journal is missing", async () => {
    const { parent, root } = await makeRoot("fixture-escrow-missing-journal");
    const reserved = await reserveFixture(root);
    const escrow = join(
      root,
      `.fixture-escrow-${basename(reserved.reservationPath)}.${reserved.record.runId}`,
    );
    await mkdir(escrow, { mode: 0o700 });
    await rename(reserved.reservationPath, join(escrow, "reservation"));
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report.leaks.some((leak) => leak.includes("journal"))).toBe(true);
      expect((await stat(escrow)).isDirectory()).toBe(true);
      expect(await readFile(join(escrow, "reservation", "fixture.json"), "utf8")).toContain(
        reserved.record.runId,
      );
    } finally {
      await rename(join(escrow, "reservation"), reserved.reservationPath).catch(() => undefined);
      await rmdir(escrow).catch(() => undefined);
      await reapOwnedRunRoot(root).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("removes a partial deterministic record temp after authenticating the canonical record", async () => {
    const { parent, root } = await makeRoot("record-temp-recovery");
    const reserved = await reserveFixture(root);
    const temporary = join(reserved.reservationPath, ".fixture.json.tmp");
    await writeFile(temporary, '{"partial":', { flag: "wx", mode: 0o600 });
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report.leaks).toEqual([]);
      expect(report.rootRemoved).toBe(true);
      await expect(access(temporary)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("removes a prelaunch registration temp without a published record or socket", async () => {
    const { parent, root } = await makeRoot("registration-temp-recovery");
    const reserved = await reserveFixture(root);
    const temporary = join(reserved.reservationPath, ".fixture.json.tmp");
    await rename(reserved.recordPath, temporary);
    try {
      const report = await reapOwnedRunRoot(root);
      expect(report.leaks).toEqual([]);
      expect(report.rootRemoved).toBe(true);
      await expect(access(temporary)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("treats the same PID with a different start identity as stale reuse", async () => {
    const { parent, root } = await makeRoot("pid-reuse");
    const ownerPath = join(root, OWNER_RECORD_NAME);
    const owner = JSON.parse(await readFile(ownerPath, "utf8")) as Record<string, unknown>;
    owner.owner = {
      pid: process.pid,
      startIdentity: "linux:00000000-0000-4000-8000-000000000000:1",
    };
    await writeFile(ownerPath, `${JSON.stringify(owner)}\n`);
    try {
      await prepareRunRoot(root);
      const current = JSON.parse(await readFile(ownerPath, "utf8")) as {
        owner: { startIdentity: string };
      };
      expect(current.owner.startIdentity).toBe(
        (await readProcessIdentity(process.pid))!.startIdentity,
      );
    } finally {
      await removeOwnedRoot(parent, root);
    }
  });

  test("fails closed on a corrupt owner identity and preserves the root", async () => {
    const { parent, root } = await makeRoot("corrupt-owner");
    await writeFile(join(root, OWNER_RECORD_NAME), "not-json\n");
    try {
      await expect(prepareRunRoot(root)).rejects.toThrow("owner record");
      expect((await stat(root)).isDirectory()).toBe(true);
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("rejects a syntactically invalid process identity before liveness checks", async () => {
    const { parent, root } = await makeRoot("invalid-identity");
    const ownerPath = join(root, OWNER_RECORD_NAME);
    const owner = JSON.parse(await readFile(ownerPath, "utf8")) as Record<string, unknown>;
    owner.owner = { pid: 2_147_483_000, startIdentity: "dead" };
    await writeFile(ownerPath, `${JSON.stringify(owner)}\n`, { mode: 0o600 });
    try {
      await expect(prepareRunRoot(root)).rejects.toThrow(/identity.*corrupt/u);
      expect((await stat(root)).isDirectory()).toBe(true);
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });
});

describe("identity-safe inaccessible-socket fallback", () => {
  test("refuses pidfd signaling when the durable launch generation changes", async () => {
    const { parent, root } = await makeRoot("pidfd-generation-mismatch");
    const server = await TestServer.create({ runRoot: root });
    const original = await readFile(server.recordPath, "utf8");
    const record = JSON.parse(original) as {
      generation?: { name: string; value: string };
    };
    const recoverySocket = join(parent, "pidfd-generation-recovery.sock");
    let captured: CapturedTmuxCleanup | undefined;
    let evidenceError: unknown;
    let mutatedRecord: string | undefined;
    let mutatedRecordEntry: ReturnType<typeof journalIdentity> | undefined;
    try {
      captured = await captureTmuxCleanup(
        server.daemonIdentity.pid,
        server.socketPath,
        recoverySocket,
      );
      if (record.generation === undefined) {
        throw new Error("running fixture lacks a durable launch generation");
      }
      const daemonBefore = await readDaemonIdentity(server.daemonIdentity.pid);
      expect(daemonBefore).toEqual(captured.daemon);
      await unlink(server.socketPath);
      mutatedRecord = `${JSON.stringify({
        ...JSON.parse(original),
        generation: {
          ...record.generation,
          value: "11111111-1111-4111-8111-111111111111",
        },
      })}\n`;
      await writeFile(server.recordPath, mutatedRecord, { mode: 0o600 });
      mutatedRecordEntry = journalIdentity(await lstat(server.recordPath));
      await expect(server.dispose()).rejects.toThrow(/generation/u);
      expect(await readDaemonIdentity(server.daemonIdentity.pid)).toEqual(daemonBefore);
      expect(await readFile(server.recordPath, "utf8")).toBe(mutatedRecord);
      expect(journalIdentity(await lstat(server.recordPath))).toEqual(mutatedRecordEntry);
      expect((await stat(server.reservationPath)).isDirectory()).toBe(true);
    } finally {
      if (mutatedRecord !== undefined && mutatedRecordEntry !== undefined) {
        try {
          expect(await readFile(server.recordPath, "utf8")).toBe(mutatedRecord);
          expect(journalIdentity(await lstat(server.recordPath))).toEqual(mutatedRecordEntry);
          await writeFile(server.recordPath, original, { mode: 0o600 });
          expect(journalIdentity(await lstat(server.recordPath))).toEqual(mutatedRecordEntry);
        } catch (error) {
          evidenceError = error;
        }
      }
      if (captured !== undefined) {
        await terminateCapturedTmux(captured);
        expect(await readDaemonIdentity(server.daemonIdentity.pid)).toBeUndefined();
      }
      const report = await reapOwnedRunRoot(root);
      expect(report.leaks).toEqual([]);
      expect(report.rootRemoved).toBe(true);
      await expect(access(root)).rejects.toMatchObject({ code: "ENOENT" });
      if (captured !== undefined) {
        const recovery = await lstat(recoverySocket, { bigint: true });
        expect({ device: recovery.dev, inode: recovery.ino }).toEqual(captured.socketIdentity);
        await unlink(recoverySocket);
      }
      await rmdir(parent);
    }
    if (evidenceError !== undefined) throw evidenceError;
  });

  test("signals through a matching pidfd identity", async () => {
    const { parent, root } = await makeRoot("pidfd-match");
    const server = await TestServer.create({ runRoot: root });
    const daemonPid = server.daemonIdentity.pid;
    try {
      await unlink(server.socketPath);
      await server.dispose();
      expect(processExists(daemonPid)).toBe(false);
    } finally {
      await removeOwnedRoot(parent, root);
    }
  });

  for (const corruption of ["mismatch", "missing", "corrupt"] as const) {
    test(`does not signal an inaccessible daemon with ${corruption} identity`, async () => {
      const { parent, root } = await makeRoot(`pidfd-${corruption}`);
      const server = await TestServer.create({ runRoot: root });
      const recordPath = server.recordPath;
      const original = await readFile(recordPath, "utf8");
      const record = JSON.parse(original) as FixtureRecord;
      if (record.phase !== "running") throw new Error("fixture did not publish running authority");
      try {
        await unlink(server.socketPath);
        if (corruption === "mismatch") {
          await writeFile(
            recordPath,
            `${JSON.stringify({
              ...record,
              daemon: {
                ...record.daemon,
                startIdentity: "linux:00000000-0000-4000-8000-000000000000:1",
              },
            })}\n`,
          );
        } else if (corruption === "missing") {
          await writeFile(recordPath, `${JSON.stringify({ ...record, daemon: undefined })}\n`);
        } else {
          await writeFile(recordPath, "{broken\n");
        }

        await expect(server.dispose()).rejects.toThrow();
        expect(processExists(server.daemonIdentity.pid)).toBe(true);
      } finally {
        await writeFile(recordPath, original);
        await reapOwnedRunRoot(root);
        await removeOwnedRoot(parent, root);
      }
    });
  }

  test("bounds and reaps a pidfd helper that ignores TERM and keeps pipes open", async () => {
    const { parent, root } = await makeRoot("hanging-pidfd-helper");
    const helper = join(parent, "hanging-python");
    const helperMarker = join(parent, "helper.pid");
    await writeFile(
      helper,
      `#!/usr/bin/env node\nconst fs=require("node:fs");fs.writeFileSync(process.env.LIBTMUX_HELPER_MARKER,String(process.pid));process.on("SIGTERM",()=>{});setInterval(()=>{},1000);\n`,
      { mode: 0o700 },
    );
    const server = await TestServer.create({
      environment: {
        ...process.env,
        LIBTMUX_HELPER_MARKER: helperMarker,
        LIBTMUX_TEST_PYTHON: helper,
      },
      runRoot: root,
    });
    let cleanup: Promise<void> | undefined;
    try {
      await unlink(server.socketPath);
      cleanup = server.dispose();
      const outcome = await Promise.race([
        cleanup.then(
          () => ({ kind: "done" as const }),
          (error: unknown) => ({ error, kind: "error" as const }),
        ),
        new Promise<{ kind: "deadline" }>((resolve) =>
          setTimeout(() => resolve({ kind: "deadline" }), 1_500),
        ),
      ]);
      expect(outcome.kind).not.toBe("deadline");
      expect(outcome.kind).toBe("error");
    } finally {
      try {
        const helperPid = Number.parseInt(await readFile(helperMarker, "utf8"), 10);
        if (processExists(helperPid)) process.kill(helperPid, "SIGKILL");
      } catch {
        // A helper that never spawned has nothing to reap.
      }
      await cleanup?.catch(() => undefined);
      await reapOwnedRunRoot(root).catch(() => undefined);
      await removeOwnedRoot(parent, root);
    }
  }, 5_000);
});

describe("supervisor status and signal semantics", () => {
  async function runSupervisorCase(
    name: string,
    workerArgs: readonly string[],
    signal?: "SIGINT" | "SIGTERM",
  ): Promise<{ closed: ClosedChild; parent: string; root: string }> {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-supervised-"));
    const root = join(parent, name);
    const marker = join(parent, "ready.json");
    const child = spawn(
      "bun",
      [
        supervisorPath,
        "--run-root",
        root,
        "--grace-ms",
        "100",
        "--",
        "bun",
        workerPath,
        ...workerArgs,
        "--marker",
        marker,
      ],
      { cwd: tsRoot, stdio: ["ignore", "pipe", "pipe"] },
    );
    if (signal !== undefined) {
      await waitForPath(marker);
      child.kill(signal);
    }
    return { closed: await closeChild(child), parent, root };
  }

  test("removes signal listeners when the supervised executable cannot spawn", async () => {
    const before = {
      sigint: process.listenerCount("SIGINT"),
      sigterm: process.listenerCount("SIGTERM"),
    };
    for (let attempt = 0; attempt < 2; attempt += 1) {
      // eslint-disable-next-line no-await-in-loop -- each completed failure is the baseline for the next listener count.
      const parent = await mkdtemp(join(tmpdir(), "ltx4-supervisor-spawn-error-"));
      const root = join(parent, "root");
      try {
        // eslint-disable-next-line no-await-in-loop -- repeated failure proves listener cleanup is idempotent.
        await expect(
          runSupervisor({ command: [join(parent, "missing-executable")], runRoot: root }),
        ).rejects.toThrow();
      } finally {
        // eslint-disable-next-line no-await-in-loop -- exact-root cleanup must complete before the next attempt.
        await reapStaleRunRoot(root).catch(() => undefined);
        // eslint-disable-next-line no-await-in-loop -- parent cleanup must complete before the next attempt.
        await rm(parent, { force: true, recursive: true });
      }
    }
    expect(process.listenerCount("SIGINT")).toBe(before.sigint);
    expect(process.listenerCount("SIGTERM")).toBe(before.sigterm);
  });

  test("preserves status 7 when the child verifies owner-record cleanup failure", async () => {
    const result = await runSupervisorCase("owner-mode-primary", [
      "--mode",
      "owner-mode-exit",
      "--exit-code",
      "7",
    ]);
    try {
      const evidence = JSON.parse(await readFile(join(result.parent, "ready.json"), "utf8")) as {
        observedMode: number;
        ownerPath: string;
      };
      expect(evidence.observedMode).toBe(0o644);
      expect(result.closed.code).toBe(7);
      expect(result.closed.stderr).toContain("mode 0600");
    } finally {
      const ownerPath = join(result.root, OWNER_RECORD_NAME);
      await chmod(ownerPath, 0o600).catch(() => undefined);
      await reapStaleRunRoot(result.root).catch(() => undefined);
      await rm(result.parent, { force: true, recursive: true });
    }
  });

  test("preserves a normal child exit status", async () => {
    const result = await runSupervisorCase("exit-7", ["--mode", "exit", "--exit-code", "7"]);
    try {
      expect(result.closed.code).toBe(7);
      await expect(stat(result.root)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(result.parent, { force: true, recursive: true });
    }
  });

  test("preserves child signal termination", async () => {
    const result = await runSupervisorCase("child-signal", ["--mode", "self-sigterm"]);
    try {
      expect(result.closed.signal === "SIGTERM" || result.closed.code === 143).toBe(true);
    } finally {
      await rm(result.parent, { force: true, recursive: true });
    }
  });

  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    test(`forwards ${signal}, escalates, reaps, and preserves interrupt status`, async () => {
      const result = await runSupervisorCase(
        `supervisor-${signal}`,
        ["--mode", "ignore-signals"],
        signal,
      );
      try {
        const expected = signal === "SIGINT" ? 130 : 143;
        expect(result.closed.signal === signal || result.closed.code === expected).toBe(true);
        await expect(stat(result.root)).rejects.toMatchObject({ code: "ENOENT" });
      } finally {
        await rm(result.parent, { force: true, recursive: true });
      }
    }, 10_000);
  }

  test("standalone reaper cleans only after a SIGKILLed supervisor owner is dead", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-dead-supervisor-"));
    const root = join(parent, "root");
    const marker = join(parent, "ready.json");
    const supervisor = spawn(
      "bun",
      [
        supervisorPath,
        "--run-root",
        root,
        "--grace-ms",
        "50",
        "--",
        "bun",
        workerPath,
        "--mode",
        "hold",
        "--marker",
        marker,
      ],
      { cwd: tsRoot, stdio: ["ignore", "pipe", "pipe"] },
    );
    let workerPid: number | undefined;
    try {
      await waitForPath(marker);
      const state = JSON.parse(await readFile(marker, "utf8")) as {
        daemonPid: number;
        workerPid: number;
      };
      workerPid = state.workerPid;
      supervisor.kill("SIGKILL");
      await exitChildWithin(supervisor, 2_000);
      expect(processExists(state.daemonPid)).toBe(true);
      const reaper = spawn("bun", [reaperPath, "--run-root", root], {
        cwd: tsRoot,
        stdio: ["ignore", "pipe", "pipe"],
      });
      expect((await closeChild(reaper)).code).toBe(0);
      expect(processExists(state.daemonPid)).toBe(false);
      await expect(stat(root)).rejects.toMatchObject({ code: "ENOENT" });
      if (processExists(state.workerPid)) process.kill(state.workerPid, "SIGKILL");
    } finally {
      if (supervisor.exitCode === null && supervisor.signalCode === null) {
        supervisor.kill("SIGKILL");
      }
      if (workerPid !== undefined && processExists(workerPid)) process.kill(workerPid, "SIGKILL");
      await reapStaleRunRoot(root).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  }, 10_000);

  test("progresses after SIGKILL when a descendant keeps the child pipes open", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-hard-close-"));
    const root = join(parent, "root");
    const marker = join(parent, "ready.json");
    const supervisor = spawn(
      "bun",
      [
        supervisorPath,
        "--run-root",
        root,
        "--grace-ms",
        "50",
        "--",
        "bun",
        workerPath,
        "--mode",
        "inherited-pipe",
        "--marker",
        marker,
      ],
      { cwd: tsRoot, stdio: ["ignore", "pipe", "pipe"] },
    );
    const supervisorClosed = closeChild(supervisor);
    let holderPid: number | undefined;
    try {
      await waitForPath(marker);
      holderPid = (JSON.parse(await readFile(marker, "utf8")) as { holderPid: number }).holderPid;
      supervisor.kill("SIGTERM");
      const result = await exitChildWithin(supervisor, 2_000);
      expect(result.signal === "SIGTERM" || result.code === 143).toBe(true);
      await expect(stat(root)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      if (supervisor.exitCode === null && supervisor.signalCode === null) {
        supervisor.kill("SIGKILL");
        await supervisorClosed.catch(() => undefined);
      }
      if (holderPid !== undefined && processExists(holderPid)) process.kill(holderPid, "SIGKILL");
      await supervisorClosed.catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  }, 5_000);

  for (const exitCode of [0, 23]) {
    test(`cleanup failure ${exitCode === 0 ? "fails success" : "does not replace failure"}`, async () => {
      const result = await runSupervisorCase(`cleanup-${exitCode}`, [
        "--mode",
        "corrupt-record-exit",
        "--exit-code",
        String(exitCode),
      ]);
      try {
        expect(result.closed.code).toBe(exitCode === 0 ? 1 : exitCode);
        const backup = JSON.parse(await readFile(join(result.parent, "ready.json"), "utf8")) as {
          recordPath: string;
          recordText: string;
        };
        await chmod(dirname(backup.recordPath), 0o700);
        await writeFile(backup.recordPath, backup.recordText);
        expect((await reapStaleRunRoot(result.root)).leaks).toEqual([]);
      } finally {
        await rm(result.parent, { force: true, recursive: true });
      }
    }, 10_000);
  }
});

describe("outer test controllers", () => {
  test("differential runner uses the exact root published by its caller", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-ci-root-"));
    const root = join(parent, "published, root");
    const child = spawn("bun", [differentialRunnerPath], {
      cwd: tsRoot,
      env: { ...process.env, LIBTMUX_TEST_RUN_ROOT: root },
      stdio: ["ignore", "pipe", "pipe"],
    });
    try {
      const [rootObserved, reservationObserved] = await Promise.all([
        observePathWhileRunning(root, child),
        observeReservationWhileRunning(root, child),
      ]);
      expect(rootObserved).toBe(true);
      expect(reservationObserved).toEqual({
        distinctOwners: true,
        observed: true,
      });
      expect((await closeChild(child)).code).toBe(0);
      await expect(access(root)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
      await reapStaleRunRoot(root).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  }, 15_000);

  for (const mode of ["after-create", "timeout-after-create"] as const) {
    test(`emitted Node ${mode} failure performs exact cleanup before parent removal`, async () => {
      const parent = await mkdtemp(join(tmpdir(), "ltx4-node-failure-"));
      const root = join(parent, "published-node-root");
      const marker = join(parent, "failure.json");
      const node22 = process.env.LIBTMUX_NODE22;
      if (node22 === undefined)
        throw new Error("LIBTMUX_NODE22 is required for emitted Node tests");
      const child = spawn("bun", [nodeRunnerPath, "--node", node22, "--expect-major", "22"], {
        cwd: tsRoot,
        env: {
          ...process.env,
          LIBTMUX_NODE_FAILURE_MARKER: marker,
          LIBTMUX_NODE_INJECT_FAILURE: mode,
          ...(mode === "timeout-after-create" ? { LIBTMUX_NODE_SCENARIO_TIMEOUT_MS: "7000" } : {}),
          LIBTMUX_TEST_RUN_ROOT: root,
        },
        stdio: ["ignore", "pipe", "pipe"],
      });
      try {
        const result = await closeChild(child);
        expect(result.code).not.toBe(0);
        const state = JSON.parse(await readFile(marker, "utf8")) as { daemonPid: number };
        expect(processExists(state.daemonPid)).toBe(false);
        await expect(access(root)).rejects.toMatchObject({ code: "ENOENT" });
      } finally {
        await reapStaleRunRoot(root).catch(() => undefined);
        await rm(parent, { force: true, recursive: true });
      }
    }, 20_000);
  }
});
