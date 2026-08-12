import { ChildProcess, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { channel } from "node:diagnostics_channel";
import { linkSync, lstatSync, readFileSync, renameSync, statSync } from "node:fs";
import {
  access,
  chmod,
  copyFile,
  link,
  lstat,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
  stat,
  unlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { describe, expect, test } from "bun:test";

import { ControlMode } from "../../src/_internal/test/control_mode.js";
import {
  prepareRunRoot,
  readDaemonIdentity,
  readFixtureRecord,
  readProcessIdentity,
  reapOwnedRunRoot,
  runWithCleanup,
  type FixtureRecord,
} from "../../src/_internal/test/run_root.js";
import {
  TestServer,
  type TestServerRequestSnapshot,
} from "../../src/_internal/test/test_server.js";
import { createRegisteredTestServer } from "../support/fixture_registry.js";

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

async function writeLaunchWrapper(
  parent: string,
  mode: "hold-after-launch" | "move-socket-after-launch" | "move-socket-and-hold",
  marker: string,
  recoverySocket?: string,
): Promise<string> {
  const tmux = Bun.which("tmux");
  if (tmux === null) throw new Error("tmux is required");
  const wrapper = join(parent, `tmux-${mode}`);
  const afterLaunch =
    mode === "hold-after-launch"
      ? "while :; do :; done"
      : [
          `socket=$(printf '%s' "$output" | cut -f1)`,
          `session=$(printf '%s' "$output" | cut -f3)`,
          "attempt=0",
          "pane_command=",
          'while [ "$attempt" -lt 1000 ]; do',
          `  pane_command=$(${shellQuote(tmux)} -N -S "$socket" display-message -p -t "$session" '#{pane_current_command}')`,
          '  if [ "$pane_command" = cat ]; then break; fi',
          "  attempt=$((attempt + 1))",
          "done",
          'if [ "$pane_command" != cat ]; then exit 70; fi',
          `mv -- "$socket" ${shellQuote(recoverySocket ?? "")}`,
          ...(mode === "move-socket-and-hold" ? ["while :; do :; done"] : []),
        ].join("\n");
  await writeFile(
    wrapper,
    `#!/bin/sh
case " $* " in
  *" new-session "*)
    output=$(${shellQuote(tmux)} "$@")
    status=$?
    printf '%s\n' "$output"
    printf '%s\n' "$output" > ${shellQuote(marker)}
    ${afterLaunch}
    exit "$status"
    ;;
  *) exec ${shellQuote(tmux)} "$@" ;;
esac
`,
    { mode: 0o700 },
  );
  await chmod(wrapper, 0o700);
  return wrapper;
}

async function writeExitStatusWrapper(parent: string, status: number): Promise<string> {
  const wrapper = join(parent, `tmux-exit-${String(status)}`);
  await writeFile(wrapper, `#!/bin/sh\nexit ${String(status)}\n`, { mode: 0o700 });
  await chmod(wrapper, 0o700);
  return wrapper;
}

async function writeLoggingTmuxWrapper(parent: string, callLog: string): Promise<string> {
  const tmux = Bun.which("tmux");
  if (tmux === null) throw new Error("tmux is required");
  const wrapper = join(parent, "tmux-call-log");
  await writeFile(
    wrapper,
    `#!/bin/sh
printf '%s\\n' "$*" >> ${shellQuote(callLog)}
exec ${shellQuote(tmux)} "$@"
`,
    { mode: 0o700 },
  );
  await chmod(wrapper, 0o700);
  return wrapper;
}

async function writeNonzeroLaunchFrameWrapper(parent: string, marker: string): Promise<string> {
  const tmux = Bun.which("tmux");
  if (tmux === null) throw new Error("tmux is required");
  const wrapper = join(parent, "tmux-nonzero-launch-frame");
  await writeFile(
    wrapper,
    `#!/bin/sh
case " $* " in
  *" new-session "*)
    output=$(${shellQuote(tmux)} "$@")
    printf '%s\n' "$output"
    printf '%s\n' "$output" > ${shellQuote(marker)}
    exit 7
    ;;
  *) exec ${shellQuote(tmux)} "$@" ;;
esac
`,
    { mode: 0o700 },
  );
  await chmod(wrapper, 0o700);
  return wrapper;
}

async function writeGonePidLaunchWrapper(parent: string, exitedPid: number): Promise<string> {
  const wrapper = join(parent, "tmux-gone-launch-pid");
  await writeFile(
    wrapper,
    `#!/bin/sh
socket=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-S" ]; then
    shift
    socket=$1
  fi
  shift
done
printf '%s\\t${String(exitedPid)}\\t%s\\n' "$socket" '$42'
`,
    { mode: 0o700 },
  );
  await chmod(wrapper, 0o700);
  return wrapper;
}

async function writeNoncanonicalPidLaunchWrapper(parent: string): Promise<string> {
  const wrapper = join(parent, "tmux-noncanonical-launch-pid");
  await writeFile(
    wrapper,
    `#!/bin/sh
socket=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-S" ]; then
    shift
    socket=$1
  fi
  shift
done
printf '%s\\t999999999junk\\t%s\\n' "$socket" '$42'
`,
    { mode: 0o700 },
  );
  await chmod(wrapper, 0o700);
  return wrapper;
}

async function writeBootstrapBarrierWrapper(
  parent: string,
  entered: string,
  argumentLog: string,
  environmentLog: string,
  releasePipe: string,
): Promise<string> {
  const tmux = Bun.which("tmux");
  if (tmux === null) throw new Error("tmux is required");
  const wrapper = join(parent, "tmux-bootstrap-barrier");
  await writeFile(
    wrapper,
    `#!/bin/sh
for argument in "$@"; do printf '%s\\0' "$argument"; done > ${shellQuote(argumentLog)}
env | sed -n '/^LIBTMUX_TEST_GENERATION_/p' > ${shellQuote(environmentLog)}
printf 'entered\n' > ${shellQuote(entered)}
IFS= read -r _ < ${shellQuote(releasePipe)}
exec ${shellQuote(tmux)} "$@"
`,
    { mode: 0o700 },
  );
  await chmod(wrapper, 0o700);
  return wrapper;
}

async function writeSnapshotLaunchWrapper(
  parent: string,
  entered: string,
  argumentLog: string,
  environmentLog: string,
  releasePipe: string,
): Promise<string> {
  const tmux = Bun.which("tmux");
  if (tmux === null) throw new Error("tmux is required");
  const wrapper = join(parent, "tmux-snapshot-launch");
  await writeFile(
    wrapper,
    `#!/bin/sh
for argument in "$@"; do printf '%s\\0' "$argument"; done > ${shellQuote(argumentLog)}
{
  printf 'BASE=%s\n' "\${LIBTMUX_ENTRY_SNAPSHOT-unset}"
  env | sed -n '/^LIBTMUX_TEST_GENERATION_/p'
} > ${shellQuote(environmentLog)}
printf 'entered\n' > ${shellQuote(entered)}
IFS= read -r _ < ${shellQuote(releasePipe)}
exec ${shellQuote(tmux)} "$@"
`,
    { mode: 0o700 },
  );
  await chmod(wrapper, 0o700);
  return wrapper;
}

function parseNullFrames(bytes: Uint8Array): readonly string[] {
  if (bytes.length === 0 || bytes.at(-1) !== 0) throw new Error("missing terminal NUL frame");
  const frames = new TextDecoder("utf-8", { fatal: true }).decode(bytes).split("\0");
  frames.pop();
  return frames;
}

async function runTmux(args: readonly string[]): Promise<{
  readonly code: number;
  readonly stderr: string;
  readonly stdout: string;
}> {
  const tmux = Bun.which("tmux");
  if (tmux === null) throw new Error("tmux is required");
  const child = Bun.spawn([tmux, ...args], { stderr: "pipe", stdout: "pipe" });
  const [code, stderr, stdout] = await Promise.all([
    child.exited,
    new Response(child.stderr).text(),
    new Response(child.stdout).text(),
  ]);
  return { code, stderr, stdout };
}

interface CapturedTmuxCleanup {
  readonly commandLine: Buffer;
  readonly daemon: NonNullable<Awaited<ReturnType<typeof readDaemonIdentity>>>;
  readonly recoverySocket: string;
  readonly socketIdentity: { readonly device: bigint; readonly inode: bigint };
}

interface ReplacedControllerCleanup extends CapturedTmuxCleanup {
  readonly cleanupExecutable: string;
  readonly executableIdentity: { readonly device: bigint; readonly inode: bigint };
  readonly recordBytes: string;
  readonly recordIdentity: { readonly device: bigint; readonly inode: bigint };
  readonly recordPath: string;
}

interface ReplaceableControllerHarness {
  readonly cleanupExecutable: string;
  readonly controllerExecutable: string;
  readonly decoyExecutable: string;
  readonly marker: string;
  readonly parent: string;
  readonly recoverySocket: string;
  readonly root: string;
}

async function makeReplaceableControllerHarness(
  name: string,
): Promise<ReplaceableControllerHarness> {
  const tmux = Bun.which("tmux");
  if (tmux === null) throw new Error("tmux is required");
  const parent = await mkdtemp(join(tmpdir(), `ltx4-controller-${name}-`));
  const root = join(parent, "root");
  const controllerExecutable = join(parent, "tmux");
  const cleanupExecutable = join(parent, "tmux-controller-recovery");
  const decoyExecutable = join(parent, "tmux-controller-decoy");
  const marker = join(parent, "decoy-invoked");
  const recoverySocket = join(parent, "recovery.sock");
  await copyFile(await realpath(tmux), controllerExecutable);
  await chmod(controllerExecutable, 0o700);
  await link(controllerExecutable, cleanupExecutable);
  await writeFile(decoyExecutable, `#!/bin/sh\nprintf invoked > ${shellQuote(marker)}\nexit 91\n`, {
    mode: 0o700,
  });
  await prepareRunRoot(root, controllerExecutable);
  return {
    cleanupExecutable,
    controllerExecutable,
    decoyExecutable,
    marker,
    parent,
    recoverySocket,
    root,
  };
}

function captureControllerReplacementSync(
  recordPath: string,
  cleanupExecutable: string,
  recoverySocket: string,
): ReplacedControllerCleanup {
  const recordBytes = readFileSync(recordPath, "utf8");
  const record = JSON.parse(recordBytes) as FixtureRecord;
  if (record.phase !== "running") throw new Error("fixture did not publish running authority");
  const recordEntry = lstatSync(recordPath, { bigint: true });
  const socket = lstatSync(record.socketPath, { bigint: true });
  if (!socket.isSocket()) throw new Error("test-owned tmux path is not a socket");
  linkSync(record.socketPath, recoverySocket);
  const executable = statSync(`/proc/${String(record.daemon.pid)}/exe`, { bigint: true });
  const recoveryExecutable = lstatSync(cleanupExecutable, { bigint: true });
  if (executable.dev !== recoveryExecutable.dev || executable.ino !== recoveryExecutable.ino) {
    throw new Error("test cleanup executable does not match the captured daemon inode");
  }
  return {
    cleanupExecutable,
    commandLine: readFileSync(`/proc/${String(record.daemon.pid)}/cmdline`),
    daemon: record.daemon,
    executableIdentity: { device: executable.dev, inode: executable.ino },
    recordBytes,
    recordIdentity: { device: recordEntry.dev, inode: recordEntry.ino },
    recordPath,
    recoverySocket,
    socketIdentity: { device: socket.dev, inode: socket.ino },
  };
}

async function captureControllerReplacement(
  server: TestServer,
  harness: ReplaceableControllerHarness,
): Promise<ReplacedControllerCleanup> {
  return captureControllerReplacementSync(
    server.recordPath,
    harness.cleanupExecutable,
    harness.recoverySocket,
  );
}

async function assertControllerEvidence(captured: ReplacedControllerCleanup): Promise<void> {
  expect(await readFile(captured.recordPath, "utf8")).toBe(captured.recordBytes);
  const record = await lstat(captured.recordPath, { bigint: true });
  expect({ device: record.dev, inode: record.ino }).toEqual(captured.recordIdentity);
  const socket = await lstat(captured.recoverySocket, { bigint: true });
  expect({ device: socket.dev, inode: socket.ino }).toEqual(captured.socketIdentity);
  const process = await readProcessIdentity(captured.daemon.pid);
  expect(process).toEqual({
    pid: captured.daemon.pid,
    startIdentity: captured.daemon.startIdentity,
  });
  const executable = await stat(`/proc/${String(captured.daemon.pid)}/exe`, { bigint: true });
  expect({ device: executable.dev, inode: executable.ino }).toEqual(captured.executableIdentity);
  expect((await readFile(`/proc/${String(captured.daemon.pid)}/cmdline`)).toString("hex")).toBe(
    captured.commandLine.toString("hex"),
  );
}

async function terminateAfterControllerReplacement(
  captured: ReplacedControllerCleanup,
): Promise<void> {
  await assertControllerEvidence(captured);
  expect((await readFile(`/proc/${String(captured.daemon.pid)}/comm`, "utf8")).trim()).toBe(
    "tmux: server",
  );
  const cleanupExecutable = await lstat(captured.cleanupExecutable, { bigint: true });
  expect({ device: cleanupExecutable.dev, inode: cleanupExecutable.ino }).toEqual(
    captured.executableIdentity,
  );
  const mismatch = `test-cleanup-mismatch-${randomUUID()}`;
  const child = spawn(
    captured.cleanupExecutable,
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
  );
  const stdout: Buffer[] = [];
  const stderr: Buffer[] = [];
  child.stdout?.on("data", (chunk: Buffer) => stdout.push(chunk));
  child.stderr?.on("data", (chunk: Buffer) => stderr.push(chunk));
  const closed = await closeWithin(child, 2_000);
  const stdoutText = Buffer.concat(stdout).toString("utf8");
  const stderrText = Buffer.concat(stderr).toString("utf8");
  if (closed.code !== 0 || stdoutText === `${mismatch}\n`) {
    throw new Error(`test-owned tmux cleanup refused: ${stderrText || stdoutText}`);
  }
  await waitForProcessExit(captured.daemon.pid);
  expect(await readProcessIdentity(captured.daemon.pid)).toBeUndefined();
}

async function restoreAndRemoveControllerHarness(
  harness: ReplaceableControllerHarness,
  captured: ReplacedControllerCleanup | undefined,
): Promise<void> {
  if (captured !== undefined && (await readProcessIdentity(captured.daemon.pid)) !== undefined) {
    await terminateAfterControllerReplacement(captured);
  }
  await unlink(harness.controllerExecutable).catch(() => undefined);
  await link(harness.cleanupExecutable, harness.controllerExecutable);
  const report = await reapOwnedRunRoot(harness.root);
  expect(report.leaks).toEqual([]);
  expect(report.rootRemoved).toBe(true);
  if (captured !== undefined) await unlink(captured.recoverySocket).catch(() => undefined);
  await rm(harness.parent, { force: true, recursive: true });
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
  const child = spawn(
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
  );
  const stdout: Buffer[] = [];
  const stderr: Buffer[] = [];
  child.stdout?.on("data", (chunk: Buffer) => stdout.push(chunk));
  child.stderr?.on("data", (chunk: Buffer) => stderr.push(chunk));
  const closed = await closeWithin(child, 2_000);
  const stdoutText = Buffer.concat(stdout).toString("utf8");
  const stderrText = Buffer.concat(stderr).toString("utf8");
  if (closed.code !== 0 || stdoutText === `${mismatch}\n`) {
    throw new Error(`test-owned tmux cleanup refused: ${stderrText || stdoutText}`);
  }
  await waitForProcessExit(captured.daemon.pid);
  expect(await readDaemonIdentity(captured.daemon.pid)).toBeUndefined();
  const after = await lstat(captured.recoverySocket, { bigint: true });
  expect({ device: after.dev, inode: after.ino }).toEqual(captured.socketIdentity);
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

async function waitForProcessExit(pid: number): Promise<void> {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (!processExists(pid)) return;
    // eslint-disable-next-line no-await-in-loop -- process exit is observed within one fixed test bound.
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(`process ${String(pid)} did not exit within the test bound`);
}

async function reapRedLaunch(socketPath: string): Promise<void> {
  const tmux = Bun.which("tmux");
  if (tmux === null) throw new Error("tmux is required");
  const child = spawn(tmux, ["-S", socketPath, "kill-server"], {
    stdio: ["ignore", "ignore", "ignore"],
  });
  await new Promise<void>((resolve) => child.once("close", () => resolve()));
}

async function withTemporaryRunRoot<T>(
  name: string,
  body: (runRoot: string) => Promise<T>,
): Promise<T> {
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  if (published !== undefined) return body(published);
  const parent = await mkdtemp(join(tmpdir(), "ltx4-it-"));
  const runRoot = join(parent, name);
  await prepareRunRoot(runRoot);
  try {
    return await body(runRoot);
  } finally {
    await reapOwnedRunRoot(runRoot);
    await rm(parent, { force: true, recursive: true });
  }
}

async function expectNoReservations(runRoot: string): Promise<void> {
  expect((await readdir(runRoot)).filter((entry) => entry !== ".owner.json")).toEqual([]);
}

/**
 * Wait for a path to disappear, within the same bound the suite uses elsewhere.
 *
 * Reclaiming a socket follows an abrupt kill, so it completes shortly after the
 * call that triggered it rather than simultaneously with it. Asserting absence
 * the instant a promise settles makes the test a race that a loaded machine
 * loses; the guarantee under test is that the socket is reclaimed, not that it
 * is reclaimed synchronously.
 */
async function waitForPathAbsent(path: string): Promise<void> {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    try {
      // eslint-disable-next-line no-await-in-loop -- absence is observed within one fixed test bound.
      await access(path);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
      throw error;
    }
    // eslint-disable-next-line no-await-in-loop -- absence observation is bounded and sequential.
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(`${path} was not reclaimed within the test bound`);
}

async function waitForMarker(path: string): Promise<void> {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    try {
      // eslint-disable-next-line no-await-in-loop -- the subprocess marker is observed within one fixed bound.
      await access(path);
      return;
    } catch {
      // eslint-disable-next-line no-await-in-loop -- marker observation is bounded and sequential.
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
  }
  throw new Error("timer probe did not publish its completion marker");
}

async function closeWithin(
  child: ReturnType<typeof spawn>,
  timeoutMs: number,
): Promise<{ readonly code: number | null; readonly signal: string | null }> {
  const waitForClose = async (
    boundMs: number,
  ): Promise<{ readonly code: number | null; readonly signal: string | null } | undefined> => {
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

  let closed = await waitForClose(timeoutMs);
  if (closed !== undefined) return closed;
  child.kill("SIGTERM");
  closed = await waitForClose(100);
  if (closed !== undefined) return closed;
  child.kill("SIGKILL");
  closed = await waitForClose(500);
  if (closed !== undefined) return closed;
  child.stdin?.destroy();
  child.stdout?.destroy();
  child.stderr?.destroy();
  child.unref();
  throw new Error("owned child did not close after SIGKILL");
}

async function writeControlTimerProbe(
  parent: string,
  mode: "dispose" | "partial-open",
  marker: string,
): Promise<string> {
  const controlModule = pathToFileURL(
    fileURLToPath(new URL("../../src/_internal/test/control_mode.ts", import.meta.url)),
  ).href;
  const runRootModule = pathToFileURL(
    fileURLToPath(new URL("../../src/_internal/test/run_root.ts", import.meta.url)),
  ).href;
  const testServerModule = pathToFileURL(
    fileURLToPath(new URL("../../src/_internal/test/test_server.ts", import.meta.url)),
  ).href;
  const script = join(parent, `control-timer-${mode}.ts`);
  const wrapper = join(parent, "ignore-control-term.sh");
  const assertedMarker = join(parent, "control-controller-asserted");
  const registrationMarker = join(parent, "control-registration-probed");
  const spawnedMarker = join(parent, "control-child-spawned");
  await writeFile(
    wrapper,
    `#!/bin/sh\nprintf spawned > ${shellQuote(spawnedMarker)}\ntrap '' TERM\nwhile :; do :; done\n`,
    { mode: 0o700 },
  );
  const body =
    mode === "partial-open"
      ? `const fakeServer = {
  assertControllerCurrent: async () => writeFile(${JSON.stringify(assertedMarker)}, "asserted"),
  controllerEnvironment: Object.freeze({ ...process.env }),
  executeText: async () => {
    await writeFile(${JSON.stringify(registrationMarker)}, "probed");
    return new Promise(() => undefined);
  },
  socketPath: "/does/not/matter",
  tmuxExecutable: ${JSON.stringify(wrapper)},
};
let openError: unknown;
try {
  await ControlMode.open({ server: fakeServer, targetSession: "$0" });
} catch (error) {
  openError = error;
}
if (!(openError instanceof Error) || !openError.message.includes("registration timed out")) {
  throw new Error("partial ControlMode open did not reach its registration deadline");
}`
      : `const runRoot = ${JSON.stringify(join(parent, "timer-run"))};
await prepareRunRoot(runRoot);
const server = await TestServer.create({ runRoot });
const control = await ControlMode.open({ server, targetSession: server.sessionId });
await control.dispose();
await server.dispose();
await reapOwnedRunRoot(runRoot);`;
  await writeFile(
    script,
    `import { writeFile } from "node:fs/promises";
import { ControlMode } from ${JSON.stringify(controlModule)};
import { prepareRunRoot, reapOwnedRunRoot } from ${JSON.stringify(runRootModule)};
import { TestServer } from ${JSON.stringify(testServerModule)};
${body}
await writeFile(${JSON.stringify(marker)}, "done");
`,
  );
  return script;
}

describe("supervised TestServer", () => {
  test("publishes owner v2 and a closed running fixture v3 record", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-generation-schema-"));
    const runRoot = join(parent, "root");
    await prepareRunRoot(runRoot);
    let server: TestServer | undefined;
    try {
      const owner = JSON.parse(await readFile(join(runRoot, ".owner.json"), "utf8")) as {
        controller?: {
          executablePath?: string;
          fileIdentity?: { kind?: string };
        };
        protocol?: string;
      };
      expect(owner.protocol).toBe("libtmux-test-run-v2");
      expect(owner.controller?.executablePath).toBeString();
      expect(owner.controller?.fileIdentity?.kind).toBe("file");

      server = await TestServer.create({ runRoot });
      const record = JSON.parse(await readFile(server.recordPath, "utf8")) as {
        bootstrapArgv?: readonly string[];
        controller?: unknown;
        daemon?: unknown;
        generation?: { name?: string; value?: string };
        phase?: string;
        protocol?: string;
        socketIdentity?: unknown;
      };
      expect(record.protocol).toBe("libtmux-test-fixture-v3");
      expect(record.phase).toBe("running");
      expect(record.controller).toEqual(owner.controller);
      expect(record.generation?.name).toMatch(/^LIBTMUX_TEST_GENERATION_[A-F0-9]{32}$/u);
      expect(record.generation?.value).toMatch(/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/u);
      expect(record.bootstrapArgv).toBeArray();
      expect(record.daemon).toBeDefined();
      expect(record.socketIdentity).toBeDefined();
    } finally {
      await server?.dispose().catch(() => undefined);
      await reapOwnedRunRoot(runRoot).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("snapshots entry inputs and authenticates the complete generated bootstrap", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-generation-bootstrap-"));
    const runRoot = join(parent, "root");
    const entered = join(parent, "entered");
    const argumentLog = join(parent, "bootstrap.argv");
    const environmentLog = join(parent, "bootstrap.env");
    const releasePipe = join(parent, "release.fifo");
    const observedRequests: TestServerRequestSnapshot[] = [];
    let replacementObserverCalled = false;
    let preTransport:
      | {
          readonly entry: { readonly device: bigint; readonly inode: bigint };
          readonly record: {
            readonly bootstrapArgv: readonly string[];
            readonly controller: { readonly executablePath: string };
            readonly generation: { readonly name: string; readonly value: string };
          };
          readonly recordBytes: string;
          readonly recordPath: string;
          readonly request: TestServerRequestSnapshot;
        }
      | undefined;
    await prepareRunRoot(runRoot);
    expect(await Bun.spawn(["mkfifo", releasePipe]).exited).toBe(0);
    const wrapper = await writeSnapshotLaunchWrapper(
      parent,
      entered,
      argumentLog,
      environmentLog,
      releasePipe,
    );
    const requestObserver = (request: TestServerRequestSnapshot): void => {
      if (
        !Object.isFrozen(request) ||
        !Object.isFrozen(request.args) ||
        !Object.isFrozen(request.environment)
      ) {
        throw new Error("request observer received a mutable execution snapshot");
      }
      observedRequests.push(request);
      if (request.purpose !== "bootstrap") return;
      if (preTransport !== undefined) throw new Error("bootstrap request was observed twice");
      const selectorIndexes = request.args.flatMap((argument, index) =>
        argument === "-S" ? [index] : [],
      );
      if (selectorIndexes.length !== 1) throw new Error("bootstrap has an invalid socket selector");
      const socketPath = request.args[selectorIndexes[0]! + 1];
      if (socketPath === undefined) throw new Error("bootstrap socket selector has no value");
      const recordPath = join(dirname(socketPath), "fixture.json");
      const recordBytes = readFileSync(recordPath, "utf8");
      const record = JSON.parse(recordBytes) as {
        bootstrapArgv?: readonly string[];
        controller?: { executablePath?: string };
        daemon?: unknown;
        generation?: { name?: string; value?: string };
        phase?: string;
        protocol?: string;
        socketIdentity?: unknown;
        socketPath?: string;
      };
      const entry = lstatSync(recordPath, { bigint: true });
      if (
        record.protocol !== "libtmux-test-fixture-v3" ||
        record.phase !== "launching" ||
        record.socketPath !== socketPath ||
        record.controller?.executablePath === undefined ||
        record.generation?.name === undefined ||
        record.generation.value === undefined ||
        record.bootstrapArgv === undefined ||
        record.daemon !== undefined ||
        record.socketIdentity !== undefined ||
        request.executable !== wrapper ||
        record.controller.executablePath === wrapper ||
        !entry.isFile() ||
        (entry.mode & 0o777n) !== 0o600n ||
        JSON.stringify(record.bootstrapArgv.slice(1)) !== JSON.stringify(request.args) ||
        record.bootstrapArgv[0] !== record.controller.executablePath ||
        request.environment[record.generation.name] !== record.generation.value
      ) {
        throw new Error("bootstrap was observed before complete launching evidence was durable");
      }
      preTransport = {
        entry: { device: entry.dev, inode: entry.ino },
        record: {
          bootstrapArgv: record.bootstrapArgv,
          controller: { executablePath: record.controller.executablePath },
          generation: { name: record.generation.name, value: record.generation.value },
        },
        recordBytes,
        recordPath,
        request,
      };
    };
    const environment = { ...process.env, LIBTMUX_ENTRY_SNAPSHOT: "before" };
    const options = {
      environment,
      launchExecutable: wrapper,
      requestObserver,
      runRoot,
    };
    const creating = TestServer.create(options);
    environment.LIBTMUX_ENTRY_SNAPSHOT = "after";
    options.launchExecutable = join(parent, "missing-after-entry");
    options.requestObserver = () => {
      replacementObserverCalled = true;
    };
    let server: TestServer | undefined;
    let launchEntered = false;
    let launchReleased = false;
    try {
      const launchBoundary = await Promise.race([
        creating.then((created) => ({ created, kind: "created" as const })),
        waitForMarker(entered).then(() => ({ kind: "entered" as const })),
      ]);
      if (launchBoundary.kind === "created") server = launchBoundary.created;
      launchEntered = launchBoundary.kind === "entered";
      expect(launchBoundary.kind).toBe("entered");
      if (preTransport === undefined) {
        throw new Error("bootstrap request was not observed before transport delivery");
      }
      const launchEvidence = preTransport;
      expect(parseNullFrames(await readFile(argumentLog))).toEqual(
        launchEvidence.record.bootstrapArgv.slice(1),
      );
      expect(await readFile(environmentLog, "utf8")).toBe(
        `BASE=before\n${launchEvidence.record.generation.name}=${launchEvidence.record.generation.value}\n`,
      );
      expect(await readFile(launchEvidence.recordPath, "utf8")).toBe(launchEvidence.recordBytes);
      const postSpawnEntry = await lstat(launchEvidence.recordPath, { bigint: true });
      expect({ device: postSpawnEntry.dev, inode: postSpawnEntry.ino }).toEqual(
        launchEvidence.entry,
      );
      await writeFile(releasePipe, "continue\n");
      launchReleased = true;
      server = await creating;
      expect(observedRequests.length).toBeGreaterThan(0);
      expect(replacementObserverCalled).toBe(false);
      expect(observedRequests.every((request) => Object.isFrozen(request))).toBe(true);
      expect(observedRequests.every((request) => Object.isFrozen(request.args))).toBe(true);
      expect(observedRequests.every((request) => Object.isFrozen(request.environment))).toBe(true);
      const record = JSON.parse(await readFile(server.recordPath, "utf8")) as {
        bootstrapArgv: readonly string[];
        daemon: { pid: number };
        generation: { name: string; value: string };
        protocol: string;
      };
      expect(record.protocol).toBe("libtmux-test-fixture-v3");
      expect(record.bootstrapArgv.slice(1, 8)).toEqual([
        "-f",
        "/dev/null",
        "-S",
        server.socketPath,
        "start-server",
        ";",
        "if-shell",
      ]);
      expect(record.bootstrapArgv.filter((argument) => argument === ";")).toEqual([";"]);
      expect(record.bootstrapArgv.some((argument) => argument.startsWith("new-session "))).toBe(
        true,
      );
      expect(parseNullFrames(await readFile(`/proc/${String(record.daemon.pid)}/cmdline`))).toEqual(
        record.bootstrapArgv,
      );

      const processGeneration = parseNullFrames(
        await readFile(`/proc/${String(record.daemon.pid)}/environ`),
      ).filter((entry) => entry.startsWith(`${record.generation.name}=`));
      expect(processGeneration).toEqual([`${record.generation.name}=${record.generation.value}`]);
      const globalGeneration = await server.executeRaw([
        "show-environment",
        "-g",
        record.generation.name,
      ]);
      expect(globalGeneration.returncode).toBe(0);
      expect(new TextDecoder().decode(globalGeneration.stdout)).toBe(
        `${record.generation.name}=${record.generation.value}\n`,
      );
      const ordinary = await server.executeRaw([
        "display-message",
        "-p",
        "ordinary-generation-environment-probe",
      ]);
      expect(ordinary.returncode).toBe(0);
      expect(new TextDecoder().decode(ordinary.stdout)).toBe(
        "ordinary-generation-environment-probe\n",
      );

      const bootstrapRequests = observedRequests.filter(({ purpose }) => purpose === "bootstrap");
      expect(bootstrapRequests).toHaveLength(1);
      expect(bootstrapRequests[0]?.environment[record.generation.name]).toBe(
        record.generation.value,
      );
      expect(observedRequests.some(({ purpose }) => purpose === "validation")).toBe(true);
      expect(observedRequests.some(({ purpose }) => purpose === "readiness")).toBe(true);
      expect(observedRequests.some(({ purpose }) => purpose === "ordinary")).toBe(true);
      expect(
        observedRequests.every(
          ({ environment: requestEnvironment }) =>
            requestEnvironment.LIBTMUX_ENTRY_SNAPSHOT === "before",
        ),
      ).toBe(true);
      expect(
        observedRequests
          .filter(({ purpose }) => purpose !== "bootstrap")
          .every(
            ({ environment: requestEnvironment }) =>
              Object.hasOwn(requestEnvironment, record.generation.name) === false,
          ),
      ).toBe(true);
    } finally {
      if (launchEntered && !launchReleased) await writeFile(releasePipe, "continue\n");
      try {
        server ??= await creating;
      } catch {
        // The rejected create promise is fully observed before fixture cleanup.
      }
      await server?.dispose().catch(() => undefined);
      await reapOwnedRunRoot(runRoot).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("refuses readiness before transport when the trusted controller is replaced", async () => {
    const harness = await makeReplaceableControllerHarness("readiness");
    let captured: ReplacedControllerCleanup | undefined;
    let failure: unknown;
    let replaced = false;
    try {
      await TestServer.create({
        requestObserver: (request) => {
          if (request.purpose !== "readiness" || replaced) return;
          const socketPath = request.args[2];
          if (socketPath === undefined) throw new Error("readiness request has no exact socket");
          captured = captureControllerReplacementSync(
            join(dirname(socketPath), "fixture.json"),
            harness.cleanupExecutable,
            harness.recoverySocket,
          );
          renameSync(harness.decoyExecutable, harness.controllerExecutable);
          replaced = true;
        },
        runRoot: harness.root,
        tmuxExecutable: harness.controllerExecutable,
      }).catch((error: unknown) => {
        failure = error;
      });
      expect(replaced).toBe(true);
      if (captured === undefined)
        throw new Error("readiness replacement did not capture authority");
      await assertControllerEvidence(captured);
      await expect(access(harness.marker)).rejects.toMatchObject({ code: "ENOENT" });
      expect(String(failure)).toMatch(/controller.*(?:changed|replaced)/iu);
    } finally {
      await restoreAndRemoveControllerHarness(harness, captured);
    }
  });

  test("rejects a foreign daemon that wins the socket before bootstrap mutation", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-generation-winner-"));
    const runRoot = join(parent, "root");
    const entered = join(parent, "entered");
    const argumentLog = join(parent, "bootstrap.argv");
    const environmentLog = join(parent, "bootstrap.env");
    const releasePipe = join(parent, "release.fifo");
    await prepareRunRoot(runRoot);
    expect(await Bun.spawn(["mkfifo", releasePipe]).exited).toBe(0);
    const wrapper = await writeBootstrapBarrierWrapper(
      parent,
      entered,
      argumentLog,
      environmentLog,
      releasePipe,
    );
    const creating = TestServer.create({ launchExecutable: wrapper, runRoot });
    let created: TestServer | undefined;
    let captured: CapturedTmuxCleanup | undefined;
    let foreignPid: number | undefined;
    let launchEntered = false;
    let launchReleased = false;
    let socketPath: string | undefined;
    try {
      const launchBoundary = await Promise.race([
        creating.then((server) => ({ kind: "created" as const, server })),
        waitForMarker(entered).then(() => ({ kind: "entered" as const })),
      ]);
      if (launchBoundary.kind === "created") created = launchBoundary.server;
      launchEntered = launchBoundary.kind === "entered";
      expect(launchBoundary.kind).toBe("entered");
      const reservations = (await readdir(runRoot)).filter((entry) => entry !== ".owner.json");
      expect(reservations).toHaveLength(1);
      const reservationPath = join(runRoot, reservations[0]!);
      socketPath = join(reservationPath, "s");
      const recordPath = join(reservationPath, "fixture.json");
      const launchingBytes = await readFile(recordPath, "utf8");
      const launchingEntry = await lstat(recordPath, { bigint: true });
      const launching = JSON.parse(launchingBytes) as {
        bootstrapArgv: readonly string[];
        controller: unknown;
        daemon?: unknown;
        generation: { name: string; value: string };
        phase: string;
        protocol: string;
        socketIdentity?: unknown;
      };
      const owner = JSON.parse(await readFile(join(runRoot, ".owner.json"), "utf8")) as {
        controller: unknown;
      };
      expect(launching.protocol).toBe("libtmux-test-fixture-v3");
      expect(launching.phase).toBe("launching");
      expect(launching.controller).toEqual(owner.controller);
      expect(launching.daemon).toBeUndefined();
      expect(launching.socketIdentity).toBeUndefined();
      expect(parseNullFrames(await readFile(argumentLog))).toEqual(
        launching.bootstrapArgv.slice(1),
      );
      expect(await readFile(environmentLog, "utf8")).toBe(
        `${launching.generation.name}=${launching.generation.value}\n`,
      );

      const foreign = await runTmux([
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
        "foreign",
        "exec cat",
      ]);
      expect(foreign.code).toBe(0);
      foreignPid = Number(foreign.stdout.trim());
      const socketBefore = await lstat(socketPath);
      captured = await captureTmuxCleanup(
        foreignPid,
        socketPath,
        join(parent, "foreign-recovery.sock"),
      );
      const generationBefore = await runTmux([
        "-N",
        "-S",
        socketPath,
        "show-environment",
        "-g",
        launching.generation.name,
      ]);
      expect(generationBefore.code).not.toBe(0);
      expect(generationBefore.stdout).toBe("");
      await writeFile(releasePipe, "continue\n");
      launchReleased = true;

      let failure: unknown;
      try {
        created = await creating;
      } catch (error) {
        failure = error;
      }
      expect(created).toBeUndefined();
      expect(processExists(foreignPid)).toBe(true);
      const sessions = await runTmux([
        "-N",
        "-S",
        socketPath,
        "list-sessions",
        "-F",
        "#{session_name}",
      ]);
      expect(sessions.code).toBe(0);
      expect(sessions.stdout.trim().split("\n")).toEqual(["foreign"]);
      const socketAfter = await lstat(socketPath);
      expect({ dev: socketAfter.dev, ino: socketAfter.ino }).toEqual({
        dev: socketBefore.dev,
        ino: socketBefore.ino,
      });
      expect(await readFile(recordPath, "utf8")).toBe(launchingBytes);
      const recordAfter = await lstat(recordPath, { bigint: true });
      expect({
        device: recordAfter.dev,
        inode: recordAfter.ino,
        mode: recordAfter.mode,
        uid: recordAfter.uid,
      }).toEqual({
        device: launchingEntry.dev,
        inode: launchingEntry.ino,
        mode: launchingEntry.mode,
        uid: launchingEntry.uid,
      });
      const generationAfter = await runTmux([
        "-N",
        "-S",
        socketPath,
        "show-environment",
        "-g",
        launching.generation.name,
      ]);
      expect(generationAfter.code).not.toBe(0);
      expect(generationAfter.stdout).toBe("");
      expect(String(failure)).toContain("generation mismatch");
    } finally {
      if (launchEntered && !launchReleased) {
        await writeFile(releasePipe, "continue\n");
      }
      try {
        created ??= await creating;
      } catch {
        // The rejected create promise is fully observed before fixture cleanup.
      }
      if (captured !== undefined) await terminateCapturedTmux(captured);
      await created?.dispose().catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  }, 10_000);

  test("reaps an indeterminate delegated launch that times out after publishing its frame", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-launch-timeout-"));
    const runRoot = join(parent, "run");
    const marker = join(parent, "launch.frame");
    await prepareRunRoot(runRoot);
    const wrapper = await writeLaunchWrapper(parent, "hold-after-launch", marker);
    try {
      await expect(TestServer.create({ launchExecutable: wrapper, runRoot })).rejects.toThrow(
        /timed out|timeout/u,
      );
      const [socketPath, rawPid] = (await readFile(marker, "utf8")).trim().split("\t");
      await waitForProcessExit(Number(rawPid));
      await waitForPathAbsent(socketPath!);
      expect((await reapOwnedRunRoot(runRoot)).reservationsFound).toBe(0);
    } finally {
      try {
        const [socketPath] = (await readFile(marker, "utf8")).trim().split("\t");
        if (socketPath !== undefined) {
          await reapRedLaunch(socketPath);
          await rm(socketPath, { force: true });
        }
      } catch {
        // A pre-launch failure has no daemon to reap.
      }
      await reapOwnedRunRoot(runRoot).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  }, 10_000);

  test("preserves pre-authority evidence when the launch socket disappears", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-launch-socket-loss-"));
    const runRoot = join(parent, "run");
    const marker = join(parent, "launch.frame");
    const recoverySocket = join(parent, "recovery.sock");
    await prepareRunRoot(runRoot);
    const wrapper = await writeLaunchWrapper(
      parent,
      "move-socket-after-launch",
      marker,
      recoverySocket,
    );
    const sentinel = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
      stdio: "ignore",
    });
    if (sentinel.pid === undefined) throw new Error("sentinel has no PID");
    const sentinelClosed = new Promise<void>((resolve) => sentinel.once("close", () => resolve()));
    try {
      let failure: unknown;
      try {
        await TestServer.create({
          faultInjection: "after-launch",
          runRoot,
          launchExecutable: wrapper,
        });
      } catch (error) {
        failure = error;
      }
      expect(String(failure)).toContain("fixture socket is missing during generation validation");
      expect((failure as Error & { cleanupError?: unknown }).cleanupError).toBeDefined();
      const [socketPath, rawPid] = (await readFile(marker, "utf8")).trim().split("\t");
      expect(processExists(Number(rawPid))).toBe(true);
      expect(processExists(sentinel.pid)).toBe(true);
      await waitForPathAbsent(socketPath!);
      const reservations = (await readdir(runRoot)).filter((entry) => entry !== ".owner.json");
      expect(reservations).toHaveLength(1);
      expect((await readFixtureRecord(join(runRoot, reservations[0]!))).phase).toBe("launching");
    } finally {
      try {
        await reapRedLaunch(recoverySocket);
      } catch {
        // The authenticated cleanup may already have reaped the daemon.
      }
      await rm(recoverySocket, { force: true });
      if (processExists(sentinel.pid)) sentinel.kill("SIGKILL");
      await sentinelClosed;
      await reapOwnedRunRoot(runRoot).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  }, 10_000);

  test("preserves an indeterminate launch whose socket moved before authority", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-launch-partial-timeout-"));
    const runRoot = join(parent, "run");
    const marker = join(parent, "launch.frame");
    const recoverySocket = join(parent, "recovery.sock");
    await prepareRunRoot(runRoot);
    const wrapper = await writeLaunchWrapper(
      parent,
      "move-socket-and-hold",
      marker,
      recoverySocket,
    );
    try {
      await expect(TestServer.create({ launchExecutable: wrapper, runRoot })).rejects.toThrow(
        /timed out/u,
      );
      const [socketPath, rawPid] = (await readFile(marker, "utf8")).trim().split("\t");
      expect(processExists(Number(rawPid))).toBe(true);
      await waitForPathAbsent(socketPath!);
      const reservations = (await readdir(runRoot)).filter((entry) => entry !== ".owner.json");
      expect(reservations).toHaveLength(1);
      expect((await readFixtureRecord(join(runRoot, reservations[0]!))).phase).toBe("launching");
    } finally {
      await reapRedLaunch(recoverySocket).catch(() => undefined);
      await rm(recoverySocket, { force: true });
      await reapOwnedRunRoot(runRoot).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  }, 10_000);

  test("authenticates a valid launch frame from a nonzero result before cleanup", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-nonzero-launch-frame-"));
    const runRoot = join(parent, "run");
    const marker = join(parent, "launch.frame");
    await prepareRunRoot(runRoot);
    const wrapper = await writeNonzeroLaunchFrameWrapper(parent, marker);
    let primary: unknown;
    try {
      await TestServer.create({ launchExecutable: wrapper, runRoot });
    } catch (error) {
      primary = error;
    }
    try {
      expect(String(primary)).toContain("tmux bootstrap failed with status 7");
      expect((primary as Error & { cleanupError?: unknown }).cleanupError).toBeUndefined();
      const [socketPath, rawPid] = (await readFile(marker, "utf8")).trim().split("\t");
      await waitForProcessExit(Number(rawPid));
      await waitForPathAbsent(socketPath!);
      expect(await readdir(runRoot)).toEqual([".owner.json"]);
    } finally {
      try {
        const [socketPath] = (await readFile(marker, "utf8")).trim().split("\t");
        if (socketPath !== undefined) {
          await reapRedLaunch(socketPath).catch(() => undefined);
          await unlink(socketPath).catch(() => undefined);
        }
      } catch {
        // A pre-launch failure has no exact daemon or socket to reap.
      }
      await reapOwnedRunRoot(runRoot).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  }, 10_000);

  test("removes a partial atomic identity temp and recovers from the original launching record", async () => {
    await withTemporaryRunRoot("partial-record-write", async (runRoot) => {
      let unexpected: TestServer | undefined;
      try {
        unexpected = await TestServer.create({
          faultInjection: "partial-identity-record-write",
          runRoot,
        });
      } catch (error) {
        expect(String(error)).toContain("injected partial identity record write failure");
      }
      if (unexpected !== undefined) {
        await unexpected.dispose();
        throw new Error("expected injected partial identity record write failure");
      }
      expect(await readdir(runRoot)).toEqual([".owner.json"]);
    });
  });

  test("preserves a launching reservation when a parsed daemon PID is already gone", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-gone-launch-pid-"));
    const runRoot = join(parent, "run");
    await prepareRunRoot(runRoot);
    const exited = spawn(process.execPath, ["-e", ""], { stdio: "ignore" });
    if (exited.pid === undefined) throw new Error("short-lived child has no PID");
    await new Promise<void>((resolve) => exited.once("close", () => resolve()));
    const wrapper = await writeGonePidLaunchWrapper(parent, exited.pid);
    try {
      await expect(TestServer.create({ launchExecutable: wrapper, runRoot })).rejects.toThrow(
        "tmux daemon identity is missing after launch",
      );
      const reservations = (await readdir(runRoot)).filter((entry) => entry !== ".owner.json");
      expect(reservations).toHaveLength(1);
      expect((await readFixtureRecord(join(runRoot, reservations[0]!))).phase).toBe("launching");
    } finally {
      await reapOwnedRunRoot(runRoot).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("rejects a noncanonical launch PID before attempting recovery", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-bad-launch-pid-"));
    const runRoot = join(parent, "run");
    await prepareRunRoot(runRoot);
    const wrapper = await writeNoncanonicalPidLaunchWrapper(parent);
    try {
      await expect(TestServer.create({ launchExecutable: wrapper, runRoot })).rejects.toThrow(
        "invalid or mismatched socket identity",
      );
      const entries = (await readdir(runRoot)).filter((entry) => entry !== ".owner.json");
      expect(entries).toHaveLength(1);
      expect((await readFixtureRecord(join(runRoot, entries[0]!))).phase).toBe("launching");
    } finally {
      await reapOwnedRunRoot(runRoot).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("reserves eight concurrent exact sockets and consumes pane readiness after signaling", async () => {
    await withTemporaryRunRoot("run, root with space", async (runRoot) => {
      const servers = await Promise.all(
        Array.from({ length: 8 }, () => createRegisteredTestServer({ runRoot })),
      );
      try {
        expect(new Set(servers.map((server) => server.logicalSocketName)).size).toBe(8);
        expect(new Set(servers.map((server) => server.socketPath)).size).toBe(8);

        await Promise.all(
          servers.map(async (server) => {
            expect(server.socketPath).toBe(join(runRoot, server.logicalSocketName, "s"));
            expect(server.observedSocketPath).toBe(server.socketPath);
            expect(server.readinessSignaledBeforeControllerWait).toBe(true);
            expect((await stat(server.reservationPath)).mode & 0o777).toBe(0o700);
            const result = await server.executeRaw([
              "display-message",
              "-p",
              "-t",
              server.sessionName,
              "#{socket_path}",
            ]);
            expect(new TextDecoder().decode(result.stdout).trim()).toBe(server.socketPath);
          }),
        );

        const first = servers[0]!;
        const cleanup = first.dispose();
        expect(first.dispose()).toBe(cleanup);
        await cleanup;
        await expect(stat(first.socketPath)).rejects.toMatchObject({ code: "ENOENT" });
      } finally {
        await Promise.all(servers.map((server) => server.dispose()));
      }

      await expectNoReservations(runRoot);
    });
  }, 20_000);

  test("enters an observed stable local pane hold before create resolves", async () => {
    await withTemporaryRunRoot("observed-readiness", async (runRoot) => {
      const server = await TestServer.create({ runRoot });
      try {
        const state = await server.executeText([
          "display-message",
          "-p",
          "-t",
          server.sessionId,
          "#{pane_current_command}",
        ]);
        expect(state.stdout).toEqual(["cat"]);
      } finally {
        await server.dispose();
      }
    });
  });

  test("publishes the authenticated Unix socket inode in a running fixture record", async () => {
    await withTemporaryRunRoot("durable-socket-identity", async (runRoot) => {
      const server = await TestServer.create({ runRoot });
      try {
        const record = (await readFixtureRecord(server.reservationPath)) as FixtureRecord & {
          readonly socketIdentity?: {
            readonly device: string;
            readonly inode: string;
            readonly kind: "socket";
            readonly mode: string;
            readonly uid: string;
          };
        };
        const socket = await lstat(server.socketPath);
        expect(record.socketIdentity).toEqual({
          device: String(socket.dev),
          inode: String(socket.ino),
          kind: "socket",
          mode: String(socket.mode),
          uid: String(socket.uid),
        });
      } finally {
        await server.dispose();
      }
    });
  });

  test("rejects a bootstrap branch with an appended second tmux command", async () => {
    await withTemporaryRunRoot("compound-bootstrap-grammar", async (runRoot) => {
      const server = await TestServer.create({ runRoot });
      const original = await readFile(server.recordPath, "utf8");
      try {
        const changed = JSON.parse(original) as { bootstrapArgv: string[] };
        changed.bootstrapArgv[10] = `${changed.bootstrapArgv[10] ?? ""} ; kill-server`;
        await writeFile(server.recordPath, `${JSON.stringify(changed)}\n`, { mode: 0o600 });
        await expect(readFixtureRecord(server.reservationPath)).rejects.toThrow("bootstrap argv");
      } finally {
        await writeFile(server.recordPath, original, { mode: 0o600 });
        await server.dispose();
      }
    });
  });

  for (const fault of [
    "after-launch",
    "identity-record-write",
    "after-identity-record",
    "before-readiness",
  ] as const) {
    test(`cleans socket, record, reservation, and daemon after ${fault} failure`, async () => {
      await withTemporaryRunRoot(`fault-${fault}`, async (runRoot) => {
        let unexpected: TestServer | undefined;
        try {
          unexpected = await TestServer.create({ runRoot, faultInjection: fault } as never);
        } catch (error) {
          expect(String(error)).toContain(`injected ${fault} failure`);
        }
        if (unexpected !== undefined) {
          await unexpected.dispose();
          throw new Error(`expected injected ${fault} failure`);
        }
        await expectNoReservations(runRoot);
      });
    });
  }

  test("preserves a body failure when fixture cleanup also reports a leak", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-create-cleanup-primary-"));
    const runRoot = join(parent, "root");
    await prepareRunRoot(runRoot);
    const primary = new Error("body failed before cleanup");
    let unexpected: string | undefined;
    try {
      let received: unknown;
      try {
        await TestServer.run({ runRoot }, async (server) => {
          unexpected = join(server.reservationPath, "unexpected");
          await writeFile(unexpected, "keep", { mode: 0o600 });
          throw primary;
        });
      } catch (error) {
        received = error;
      }
      expect(received).toBe(primary);
      expect(String((primary as Error & { cleanupError: unknown }).cleanupError)).toContain(
        "unexpected",
      );
    } finally {
      if (unexpected !== undefined) await unlink(unexpected).catch(() => undefined);
      await reapOwnedRunRoot(runRoot).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("survives repeated immediate socket unlink cleanup after observed readiness", async () => {
    await withTemporaryRunRoot("unlink-stress", async (runRoot) => {
      for (let iteration = 0; iteration < 20; iteration += 1) {
        // eslint-disable-next-line no-await-in-loop -- each fixture lifecycle is the stress subject.
        const server = await TestServer.create({ runRoot });
        // eslint-disable-next-line no-await-in-loop -- unlink is deliberately immediate after create resolves.
        await rm(server.socketPath);
        // eslint-disable-next-line no-await-in-loop -- exact cleanup must settle before the next lifecycle.
        await server.dispose();
        // eslint-disable-next-line no-await-in-loop -- every iteration proves its reservation is gone.
        await expect(access(server.reservationPath)).rejects.toMatchObject({ code: "ENOENT" });
      }
      await expectNoReservations(runRoot);
    });
  }, 30_000);

  test("uses the authenticated daemon executable for the cleanup PID guard", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-cleanup-executable-"));
    const runRoot = join(parent, "root");
    const callLog = join(parent, "tmux-calls.log");
    await prepareRunRoot(runRoot);
    const wrapper = await writeLoggingTmuxWrapper(parent, callLog);
    let server: TestServer | undefined;
    try {
      server = await TestServer.create({ launchExecutable: wrapper, runRoot });
      const startupCalls = await readFile(callLog, "utf8");
      expect(startupCalls).toContain("new-session");

      await server.dispose();
      server = undefined;

      expect(await readFile(callLog, "utf8")).toBe(startupCalls);
    } finally {
      await server?.dispose().catch(() => undefined);
      await reapOwnedRunRoot(runRoot).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  for (const mutation of ["add-unexpected", "replace-socket"] as const) {
    test(`preserves cleanup evidence after ${mutation}`, async () => {
      const parent = await mkdtemp(join(tmpdir(), "ltx4-cleanup-mutation-"));
      const runRoot = join(parent, "root");
      const recoverySocket = join(parent, "recovery.sock");
      await prepareRunRoot(runRoot);
      const server = await TestServer.create({ runRoot });
      try {
        if (mutation === "add-unexpected") {
          await writeFile(join(server.reservationPath, "unexpected"), "keep", { mode: 0o600 });
        } else {
          await rename(server.socketPath, recoverySocket);
          await writeFile(server.socketPath, "replacement", { mode: 0o600 });
        }
        await expect(server.dispose()).rejects.toThrow();
        expect((await stat(server.recordPath)).isFile()).toBe(true);
        if (mutation === "add-unexpected") {
          expect(await readFile(join(server.reservationPath, "unexpected"), "utf8")).toBe("keep");
          expect((await stat(server.socketPath)).isSocket()).toBe(true);
        } else {
          expect((await stat(server.socketPath)).isFile()).toBe(true);
          expect(await readFile(server.socketPath, "utf8")).toBe("replacement");
        }
      } finally {
        await unlink(join(server.reservationPath, "unexpected")).catch(() => undefined);
        const socket = await stat(server.socketPath).catch(() => undefined);
        if (socket?.isFile() === true) await unlink(server.socketPath);
        if ((await stat(recoverySocket).catch(() => undefined))?.isSocket() === true) {
          await rename(recoverySocket, server.socketPath);
        }
        await reapOwnedRunRoot(runRoot).catch(() => undefined);
        await rm(parent, { force: true, recursive: true });
      }
    });
  }

  test("accepts authenticated socket disappearance after the daemon exits", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-cleanup-socket-move-"));
    const runRoot = join(parent, "root");
    const movedSocket = join(parent, "moved-socket");
    await prepareRunRoot(runRoot);
    const server = await TestServer.create({ runRoot });
    try {
      await reapRedLaunch(server.socketPath);
      await waitForProcessExit(server.daemonIdentity.pid);
      await rename(server.socketPath, movedSocket);
      await server.dispose();
      await expect(stat(server.recordPath)).rejects.toMatchObject({ code: "ENOENT" });
      expect((await stat(movedSocket)).isSocket()).toBe(true);
    } finally {
      await unlink(movedSocket).catch(() => undefined);
      await reapOwnedRunRoot(runRoot).catch(() => undefined);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("cleans a failed startup without a daemon, registry, socket, or reservation", async () => {
    await withTemporaryRunRoot("startup-failure", async (runRoot) => {
      await expect(
        TestServer.create({
          runRoot,
          launchExecutable: join(runRoot, "missing-tmux"),
        }),
      ).rejects.toThrow();

      await expectNoReservations(runRoot);
    });
  });

  for (const status of [1, 7]) {
    test(`preserves a pre-authority launch failure with status ${String(status)}`, async () => {
      const parent = await mkdtemp(join(tmpdir(), "ltx4-launch-status-"));
      const runRoot = join(parent, "run");
      await prepareRunRoot(runRoot);
      const wrapper = await writeExitStatusWrapper(parent, status);
      try {
        let failure: unknown;
        try {
          await TestServer.create({ launchExecutable: wrapper, runRoot });
        } catch (error) {
          failure = error;
        }
        expect(String(failure)).toContain(`status ${String(status)}`);
        expect((failure as Error & { cleanupError?: unknown }).cleanupError).toBeDefined();
        const reservations = (await readdir(runRoot)).filter((entry) => entry !== ".owner.json");
        expect(reservations).toHaveLength(1);
        expect((await readFixtureRecord(join(runRoot, reservations[0]!))).phase).toBe("launching");
      } finally {
        await reapOwnedRunRoot(runRoot).catch(() => undefined);
        await rm(parent, { force: true, recursive: true });
      }
    });
  }

  test("cleans the fixture when its test body throws", async () => {
    await withTemporaryRunRoot("throwing-body", async (runRoot) => {
      const primary = new Error("primary test failure");
      await expect(
        TestServer.run({ runRoot }, async () => {
          throw primary;
        }),
      ).rejects.toBe(primary);

      await expectNoReservations(runRoot);
    });
  });

  test("rejects an overlong Unix socket path before attempting tmux spawn", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-long-"));
    const runRoot = join(parent, "x".repeat(120));
    await prepareRunRoot(runRoot);
    try {
      await expect(
        TestServer.create({
          runRoot,
          launchExecutable: join(runRoot, "also-missing"),
        }),
      ).rejects.toThrow("Unix socket path");
      expect(await readFile(join(runRoot, ".owner.json"), "utf8")).toContain("libtmux-test-run-v2");
      expect((await reapOwnedRunRoot(runRoot)).reservationsFound).toBe(0);
    } finally {
      await reapOwnedRunRoot(runRoot);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("measures the conservative socket limit in UTF-8 bytes before spawn", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-byte-limit-"));
    const runRoot = join(parent, "雪".repeat(40));
    await prepareRunRoot(runRoot);
    try {
      await expect(
        TestServer.create({
          runRoot,
          launchExecutable: join(runRoot, "missing-tmux"),
        }),
      ).rejects.toThrow("103 UTF-8 bytes");
      expect((await reapOwnedRunRoot(runRoot)).reservationsFound).toBe(0);
    } finally {
      await reapOwnedRunRoot(runRoot);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("refuses an ordinary command before transport when the trusted controller is replaced", async () => {
    const harness = await makeReplaceableControllerHarness("ordinary");
    const server = await TestServer.create({
      runRoot: harness.root,
      tmuxExecutable: harness.controllerExecutable,
    });
    const captured = await captureControllerReplacement(server, harness);
    let failure: unknown;
    try {
      await rename(harness.decoyExecutable, harness.controllerExecutable);
      await server.executeRaw(["display-message", "-p", "ordinary"]).catch((error: unknown) => {
        failure = error;
      });
      await assertControllerEvidence(captured);
      await expect(access(harness.marker)).rejects.toMatchObject({ code: "ENOENT" });
      expect(String(failure)).toMatch(/controller.*(?:changed|replaced)/iu);
    } finally {
      await restoreAndRemoveControllerHarness(harness, captured);
    }
  });

  test("refuses ControlMode before spawn when the trusted controller is replaced", async () => {
    const harness = await makeReplaceableControllerHarness("control");
    const server = await TestServer.create({
      runRoot: harness.root,
      tmuxExecutable: harness.controllerExecutable,
    });
    const captured = await captureControllerReplacement(server, harness);
    let failure: unknown;
    try {
      await rename(harness.decoyExecutable, harness.controllerExecutable);
      await ControlMode.open({ server, targetSession: server.sessionId }).catch(
        (error: unknown) => {
          failure = error;
        },
      );
      await assertControllerEvidence(captured);
      await expect(access(harness.marker)).rejects.toMatchObject({ code: "ENOENT" });
      expect(String(failure)).toMatch(/controller.*(?:changed|replaced)/iu);
    } finally {
      await restoreAndRemoveControllerHarness(harness, captured);
    }
  });

  test("keeps ControlMode as an attached client resource", async () => {
    await withTemporaryRunRoot("control-mode", async (runRoot) => {
      const server = await createRegisteredTestServer({ runRoot });
      const control = await ControlMode.open({ server, targetSession: server.sessionId });
      try {
        const listed = await server.executeText([
          "list-clients",
          "-F",
          "#{client_pid}\t#{client_name}",
        ]);
        expect(listed.stdout).toContain(`${String(control.pid)}\t${control.clientName}`);
      } finally {
        await control.dispose();
        const listed = await server.executeText(["list-clients", "-F", "#{client_pid}"]);
        expect(listed.stdout).not.toContain(String(control.pid));
        await server.dispose();
      }
    });
  });

  test("starts ControlMode from the frozen base environment without the daemon generation", async () => {
    await withTemporaryRunRoot("control-environment", async (runRoot) => {
      const environment = { ...process.env, LIBTMUX_CONTROL_BASE: "entry" };
      const server = await createRegisteredTestServer({ environment, runRoot });
      environment.LIBTMUX_CONTROL_BASE = "mutated";
      const record = await readFixtureRecord(server.reservationPath);
      if (record.phase !== "running") throw new Error("fixture did not publish running authority");
      const control = await ControlMode.open({ server, targetSession: server.sessionId });
      try {
        const frames = parseNullFrames(await readFile(`/proc/${String(control.pid)}/environ`));
        expect(frames.filter((frame) => frame.startsWith("LIBTMUX_CONTROL_BASE="))).toEqual([
          "LIBTMUX_CONTROL_BASE=entry",
        ]);
        expect(frames.some((frame) => frame.startsWith(`${record.generation.name}=`))).toBe(false);
      } finally {
        await control.dispose();
        await server.dispose();
      }
    });
  });

  test("owns only its exact attached client and drains non-ASCII control output", async () => {
    await withTemporaryRunRoot("two-control-clients", async (runRoot) => {
      const server = await createRegisteredTestServer({ runRoot });
      const first = await ControlMode.open({ server, targetSession: server.sessionId });
      const second = await ControlMode.open({ server, targetSession: server.sessionId });
      try {
        expect(first.clientName).not.toBe(second.clientName);
        expect(
          await first.sendAndWaitFor("display-message -p '雪'", (line) => line.includes("雪")),
        ).toContain("雪");
        await first.dispose();
        const listed = await server.executeText([
          "list-clients",
          "-F",
          "#{client_pid}\t#{client_name}",
        ]);
        expect(listed.stdout).not.toContain(`${String(first.pid)}\t${first.clientName}`);
        expect(listed.stdout).toContain(`${String(second.pid)}\t${second.clientName}`);
      } finally {
        await Promise.all([first.dispose(), second.dispose()]);
        await server.dispose();
      }
    });
  });

  test("submits every ControlMode line and correlates predicates after a watermark", async () => {
    await withTemporaryRunRoot("control-watermark", async (runRoot) => {
      const server = await createRegisteredTestServer({ runRoot });
      const control = await ControlMode.open({ server, targetSession: server.sessionId });
      try {
        const first = await control.sendAndWaitFor(
          "display-message -p 'same-predicate:first'",
          (line) => line.includes("same-predicate:"),
        );
        const second = await control.sendAndWaitFor(
          "display-message -p 'same-predicate:second'",
          (line) => line.includes("same-predicate:"),
        );
        expect(first).toContain("same-predicate:first");
        expect(second).toContain("same-predicate:second");
      } finally {
        await control.dispose();
        await server.dispose();
      }
    });
  });

  test("settles a missing ControlMode executable within a hard deadline", async () => {
    let controllerAssertionRan = false;
    const fakeServer = {
      assertControllerCurrent: async () => {
        controllerAssertionRan = true;
      },
      controllerEnvironment: Object.freeze({}),
      executeText: async () => ({ stderr: [], stdout: [] }),
      socketPath: "/does/not/exist/s",
      tmuxExecutable: "/does/not/exist/tmux",
    };
    const originalEmit = ChildProcess.prototype.emit;
    let spawnError: { readonly code?: string; readonly path?: string } | undefined;
    ChildProcess.prototype.emit = function (event: string | symbol, ...args: unknown[]): boolean {
      if (event === "error" && this.spawnfile === fakeServer.tmuxExecutable) {
        spawnError = args[0] as typeof spawnError;
      }
      return Reflect.apply(originalEmit, this, [event, ...args]) as boolean;
    };
    const started = performance.now();
    let deadline: ReturnType<typeof setTimeout> | undefined;
    try {
      await expect(
        Promise.race([
          ControlMode.open({ server: fakeServer as never, targetSession: "$0" }),
          new Promise<never>((_, reject) => {
            deadline = setTimeout(
              () => reject(new Error("ControlMode open exceeded hard deadline")),
              1_000,
            );
          }),
        ]),
      ).rejects.toThrow("control-mode client did not spawn");
    } finally {
      if (deadline !== undefined) clearTimeout(deadline);
      ChildProcess.prototype.emit = originalEmit;
    }
    expect(controllerAssertionRan).toBeTrue();
    expect(spawnError?.code).toBe("ENOENT");
    expect(spawnError?.path).toBe(fakeServer.tmuxExecutable);
    expect(performance.now() - started).toBeLessThan(1_000);
  });

  test("bounds ControlMode registration when the server probe never settles", async () => {
    await withTemporaryRunRoot("control-never-settles", async (runRoot) => {
      const server = await TestServer.create({ runRoot });
      const executeText = server.executeText.bind(server);
      let releaseProbe: (() => void) | undefined;
      server.executeText = async () =>
        new Promise((resolve) => {
          releaseProbe = () => resolve({ stderr: [], stdout: [] });
        });
      const opening = ControlMode.open({ server, targetSession: server.sessionId });
      try {
        const started = performance.now();
        await expect(
          Promise.race([
            opening,
            new Promise<never>((_, reject) =>
              setTimeout(() => reject(new Error("registration exceeded wall-clock deadline")), 800),
            ),
          ]),
        ).rejects.toThrow(/registration timed out/u);
        expect(performance.now() - started).toBeLessThan(1_500);
      } finally {
        releaseProbe?.();
        server.executeText = executeText;
        await opening.then((control) => control.dispose()).catch(() => undefined);
        const clients = await server.executeText(["list-clients", "-F", "#{client_pid}"]);
        await Promise.all(
          clients.stdout.map(async (pid) => server.executeText(["kill-client", "-t", pid])),
        );
        await server.dispose();
      }
    });
  }, 3_000);

  test("cleans a partially attached ControlMode and a throwing body", async () => {
    await withTemporaryRunRoot("control-failure", async (runRoot) => {
      const server = await createRegisteredTestServer({ runRoot });
      await expect(
        ControlMode.open({ server, targetSession: "missing-session" }),
      ).rejects.toThrow();
      const primary = new Error("attached body failed");
      await expect(
        ControlMode.run({ server, targetSession: server.sessionId }, async () => {
          throw primary;
        }),
      ).rejects.toBe(primary);
      expect((await server.executeText(["list-clients", "-F", "#{client_pid}"])).stdout).toEqual(
        [],
      );
      await server.dispose();
    });
  });

  for (const mode of ["partial-open", "dispose"] as const) {
    test(`does not retain a Bun process through a losing ControlMode ${mode} timer`, async () => {
      const parent = await mkdtemp(join(tmpdir(), `ltx4-control-timer-${mode}-`));
      const marker = join(parent, "done");
      const script = await writeControlTimerProbe(parent, mode, marker);
      const child = spawn("bun", [script], {
        cwd: fileURLToPath(new URL("../..", import.meta.url)),
        stdio: ["ignore", "pipe", "pipe"],
      });
      const stderr: Buffer[] = [];
      child.stderr?.on("data", (chunk: Buffer) => stderr.push(chunk));
      try {
        await waitForMarker(marker);
        if (mode === "partial-open") {
          await access(join(parent, "control-controller-asserted"));
          await access(join(parent, "control-registration-probed"));
          await access(join(parent, "control-child-spawned"));
        }
        const completedAt = performance.now();
        const closed = await closeWithin(child, 300);
        expect(closed).toEqual({ code: 0, signal: null });
        expect(performance.now() - completedAt).toBeLessThan(300);
      } finally {
        if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
        await new Promise<void>((resolve) => {
          if (child.exitCode !== null || child.signalCode !== null) resolve();
          else child.once("close", () => resolve());
        });
        await rm(parent, { force: true, recursive: true });
      }
      expect(Buffer.concat(stderr).toString("utf8")).toBe("");
    }, 5_000);
  }

  test("cleanup failure replaces success but remains secondary to a primary failure", async () => {
    const cleanup = new Error("cleanup failed");
    await expect(
      runWithCleanup(
        async () => "passed",
        async () => {
          throw cleanup;
        },
      ),
    ).rejects.toBe(cleanup);

    const primary = new Error("test failed");
    try {
      await runWithCleanup(
        async () => {
          throw primary;
        },
        async () => {
          throw cleanup;
        },
      );
      throw new Error("expected primary failure");
    } catch (error) {
      expect(error).toBe(primary);
      expect((error as Error & { cleanupError?: unknown }).cleanupError).toBe(cleanup);
    }
  });

  test("preserves frozen and primitive primary failures while reporting cleanup failure", async () => {
    const cleanup = new Error("secondary cleanup failure");
    const reports: unknown[] = [];
    const cleanupChannel = channel("libtmux.test.cleanup-failure");
    const listener = (message: unknown): void => {
      reports.push(message);
    };
    cleanupChannel.subscribe(listener);
    try {
      const frozen = Object.freeze(new Error("frozen primary"));
      await expect(
        runWithCleanup(
          async () => {
            throw frozen;
          },
          async () => {
            throw cleanup;
          },
        ),
      ).rejects.toBe(frozen);
      await expect(
        runWithCleanup(
          async () => {
            throw "primitive primary";
          },
          async () => {
            throw cleanup;
          },
        ),
      ).rejects.toBe("primitive primary");
      let caughtUndefined = false;
      try {
        await runWithCleanup(
          async () => {
            throw undefined;
          },
          async () => {
            throw cleanup;
          },
        );
      } catch (error) {
        caughtUndefined = true;
        expect(error).toBeUndefined();
      }
      expect(caughtUndefined).toBe(true);
      expect(reports).toEqual([
        { cleanupError: cleanup, primary: frozen },
        { cleanupError: cleanup, primary: "primitive primary" },
        { cleanupError: cleanup, primary: undefined },
      ]);
    } finally {
      cleanupChannel.unsubscribe(listener);
    }
  });

  test("preserves a primary with a non-configurable cleanupError property", async () => {
    const primary = new Error("primary with reserved cleanup property");
    const existingCleanup = new Error("existing cleanup evidence");
    Object.defineProperty(primary, "cleanupError", {
      configurable: false,
      enumerable: false,
      value: existingCleanup,
      writable: false,
    });
    const cleanup = new Error("secondary cleanup failure");
    const reports: unknown[] = [];
    const cleanupChannel = channel("libtmux.test.cleanup-failure");
    const listener = (message: unknown): void => {
      reports.push(message);
    };
    cleanupChannel.subscribe(listener);
    try {
      await expect(
        runWithCleanup(
          async () => {
            throw primary;
          },
          async () => {
            throw cleanup;
          },
        ),
      ).rejects.toBe(primary);
      expect((primary as Error & { cleanupError: unknown }).cleanupError).toBe(existingCleanup);
      expect(reports).toEqual([{ cleanupError: cleanup, primary }]);
    } finally {
      cleanupChannel.unsubscribe(listener);
    }
  });

  test("preserves a hostile proxy primary when cleanup reporting reflects on it", async () => {
    const target = new Error("hostile proxy primary");
    const primary = new Proxy(target, {
      getOwnPropertyDescriptor(): PropertyDescriptor | undefined {
        throw new Error("primary reflection failed");
      },
      isExtensible(): boolean {
        throw new Error("primary extensibility failed");
      },
    });
    const cleanup = new Error("secondary cleanup failure");

    await expect(
      runWithCleanup(
        async () => {
          throw primary;
        },
        async () => {
          throw cleanup;
        },
      ),
    ).rejects.toBe(primary);
  });
});
