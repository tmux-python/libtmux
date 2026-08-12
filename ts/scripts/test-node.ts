import { spawn, spawnSync } from "node:child_process";
import { constants } from "node:fs";
import { access, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { reapStaleRunRoot } from "../src/_internal/test/run_root.js";

interface Arguments {
  readonly expectMajor: number;
  readonly nodeArgument?: string;
}

interface ScenarioReport {
  readonly protocol: "libtmux-node-scenarios-v1";
  readonly scenarios: readonly string[];
  readonly status: "passed";
}

function parseArguments(argv: readonly string[]): Arguments {
  let expectMajor: number | undefined;
  let nodeArgument: string | undefined;
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (value === undefined) throw new Error(`${flag ?? "argument"} requires a value`);
    if (flag === "--node") nodeArgument = value;
    else if (flag === "--expect-major") expectMajor = Number.parseInt(value, 10);
    else throw new Error(`unknown argument: ${flag}`);
  }
  if (expectMajor === undefined || !Number.isSafeInteger(expectMajor) || expectMajor < 1) {
    throw new Error("--expect-major must be a positive integer");
  }
  return nodeArgument === undefined ? { expectMajor } : { expectMajor, nodeArgument };
}

async function executableOnPath(name: string): Promise<string> {
  const entries = (process.env.PATH ?? "").split(delimiter).filter((entry) => entry !== "");
  const candidates = await Promise.all(
    entries.map(async (entry) => {
      const candidate = resolve(entry, name);
      try {
        await access(candidate, constants.X_OK);
        return await realpath(candidate);
      } catch {
        return undefined;
      }
    }),
  );
  const executable = candidates.find((candidate) => candidate !== undefined);
  if (executable !== undefined) return executable;
  throw new Error(`${name} was not found on PATH`);
}

async function resolveNode(nodeArgument: string | undefined): Promise<string> {
  if (nodeArgument !== undefined) {
    if (!isAbsolute(nodeArgument)) throw new Error("--node must be an absolute executable path");
    await access(nodeArgument, constants.X_OK);
    return realpath(nodeArgument);
  }

  const configured = process.env.LIBTMUX_NODE22;
  if (configured !== undefined) {
    const candidate = resolve(configured);
    await access(candidate, constants.X_OK);
    return realpath(candidate);
  }
  return executableOnPath("node");
}

function queryMajor(executable: string, expected: number): string {
  const result = spawnSync(executable, ["--version"], { encoding: "utf8" });
  if (result.error !== undefined) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Node version query failed with status ${String(result.status)}`);
  }
  const version = result.stdout.trim();
  const match = /^v(\d+)(?:\.|$)/.exec(version);
  if (match === null) throw new Error(`unrecognized Node version: ${version}`);
  const actual = Number.parseInt(match[1]!, 10);
  if (actual !== expected) {
    throw new Error(`expected Node major ${expected}, received ${actual} (${version})`);
  }
  return version;
}

function scenarioSource(tsRoot: string, executable: string): string {
  const moduleUrl = (relativePath: string): string =>
    JSON.stringify(pathToFileURL(join(tsRoot, relativePath)).href);
  const executableLiteral = JSON.stringify(executable);
  const echoFixture = moduleUrl("tests/fixtures/echo_argv.mjs");
  const ignoreFixture = moduleUrl("tests/fixtures/ignore_sigterm.mjs");
  const malformedFixture = moduleUrl("tests/fixtures/malformed_utf8.mjs");
  const runRootModule = moduleUrl("dist/_internal/test/run_root.js");
  const controlModeModule = moduleUrl("dist/_internal/test/control_mode.js");

  return `import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { channel } from "node:diagnostics_channel";
import { access, readFile, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { decodeBackslashReplace } from ${moduleUrl("dist/_internal/codec/backslash_replace.js")};
import { FormatProtocolError, GuardCodec } from ${moduleUrl("dist/_internal/codec/guard_codec.js")};
import { adaptRawResult, executeBatch, prepareCommandRequest } from ${moduleUrl("dist/_internal/operations/request.js")};
import { deriveTmuxCapabilities } from ${moduleUrl("dist/_internal/runtime/capabilities.js")};
import { TmuxConnection } from ${moduleUrl("dist/_internal/runtime/connection.js")};
import { ControlMode } from ${controlModeModule};
import { NodeSpawnTransport } from ${moduleUrl("dist/_internal/transport/node_spawn_transport.js")};
import { TransportError } from ${moduleUrl("dist/_internal/transport/types.js")};
import { prepareRunRoot, readProcessIdentity, reapOwnedRunRoot, reapStaleRunRoot, runWithCleanup } from ${runRootModule};
import { TestServer } from ${moduleUrl("dist/_internal/test/test_server.js")};
import { FORMAT_SEPARATOR } from ${moduleUrl("dist/formats.js")};
import { Obj, getOutputFormat, parseOutput } from ${moduleUrl("dist/neo.js")};

const executable = ${executableLiteral};
const echoFixture = fileURLToPath(${echoFixture});
const ignoreFixture = fileURLToPath(${ignoreFixture});
const malformedFixture = fileURLToPath(${malformedFixture});
const transport = new NodeSpawnTransport({ terminationGraceMs: 30 });
assert.equal(FORMAT_SEPARATOR, "NODE_FORMAT_SEPARATOR");
const nodeFormatCodec = new GuardCodec({
  capabilities: deriveTmuxCapabilities({
    connectionAlias: "node-format-scenario",
    daemonEpoch: 1,
    rawVersion: "3.7b",
  }),
  listCommand: "list-sessions",
});
const nodeFormatRequest = nodeFormatCodec.prepare();
assert.equal(nodeFormatRequest.format.includes(FORMAT_SEPARATOR), false);
const publicPlan = getOutputFormat("list-sessions", "3.2a");
const publicValues = publicPlan.fields.map(({ token }) => {
  if (token === "session_id") return "$1";
  if (token === "session_group") return "";
  if (token === "window_id") return "@2";
  if (token === "pane_id") return "%3";
  return "node:" + token;
});
const publicFrame = new TextEncoder().encode(
  publicPlan.guards.recordStart +
    publicValues.join(publicPlan.guards.field) +
    publicPlan.guards.recordEnd +
    "\\n",
);
const publicRows = parseOutput(publicPlan, publicFrame);
assert.equal(publicRows.length, 1);
assert.ok(publicRows[0] instanceof Obj);
assert.equal(Object.keys(publicRows[0]).length, 178);
assert.equal(publicRows[0].session_group, "");
assert.equal(publicRows[0].pane_x, null);
assert.equal(Object.isFrozen(publicRows), true);
assert.equal(Object.isFrozen(publicRows[0]), true);
assert.throws(
  () => nodeFormatCodec.decode(nodeFormatRequest, new TextEncoder().encode("not a frame")),
  (error) => error instanceof FormatProtocolError,
);
async function waitForFile(path, attempts = 100) {
  try {
    await readFile(path);
  } catch {
    if (attempts === 1) throw new Error("readiness marker was not created: " + path);
    await new Promise((resolve) => setTimeout(resolve, 5));
    await waitForFile(path, attempts - 1);
  }
}
async function readHolderIdentity(path) {
  const rawPid = (await readFile(path, "utf8")).trim();
  assert.match(rawPid, /^[1-9]\\d*$/u);
  const identity = await readProcessIdentity(Number(rawPid));
  assert.notEqual(identity, undefined);
  return identity;
}
function sameIdentity(left, right) {
  return left?.pid === right.pid && left.startIdentity === right.startIdentity;
}
async function holderExited(identity) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (!sameIdentity(await readProcessIdentity(identity.pid), identity)) return true;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  return false;
}
async function stopHolder(identity) {
  if (!sameIdentity(await readProcessIdentity(identity.pid), identity)) return;
  try {
    process.kill(identity.pid, "SIGTERM");
  } catch (error) {
    if (error?.code !== "ESRCH") throw error;
    return;
  }
  if (await holderExited(identity)) return;
  if (!sameIdentity(await readProcessIdentity(identity.pid), identity)) return;
  process.kill(identity.pid, "SIGKILL");
  assert.equal(await holderExited(identity), true);
}
async function settleWithin(promise, milliseconds) {
  let timer;
  try {
    return await Promise.race([
      promise.then(
        (value) => ({ kind: "value", value }),
        (error) => ({ error, kind: "error" }),
      ),
      new Promise((resolve) => {
        timer = setTimeout(() => resolve({ kind: "deadline" }), milliseconds);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
const values = ["with space", "-leading", 'a"quote', "a\\\\backslash", "雪", ";"];
const literal = await transport.execute({ executable, args: [echoFixture, ...values] });
assert.deepEqual(JSON.parse(decodeBackslashReplace(literal.stdout)), values);

const stdin = Uint8Array.of(0x61, 0x62);
const immutableInput = transport.execute({
  executable,
  args: [echoFixture, "--echo-stdin"],
  stdin,
});
stdin[0] = 0x7a;
assert.deepEqual([...((await immutableInput).stdout)], [0x61, 0x62]);

const submittedArgs = [echoFixture, "submitted"];
const correlatedExecution = transport.execute({ executable, args: submittedArgs });
submittedArgs[1] = "mutated-after-spawn";
const correlated = await correlatedExecution;
assert.deepEqual(JSON.parse(decodeBackslashReplace(correlated.stdout)), ["submitted"]);
assert.deepEqual(correlated.cmd, [executable, echoFixture, "submitted"]);

const prepared = prepareCommandRequest(
  new TmuxConnection({ executable }),
  ["load-buffer", "-"],
  { stdin: Uint8Array.of(0x61, 0x62) },
);
prepared.stdin[0] = 0x7a;
await Promise.resolve();
assert.deepEqual([...prepared.stdin], [0x61, 0x62]);

const nonzero = await transport.execute({ executable, args: [echoFixture, "--exit-code=7"] });
assert.equal(nonzero.returncode, 7);
assert.ok(nonzero.stdout instanceof Uint8Array);
assert.ok(nonzero.stderr instanceof Uint8Array);

const malformed = await transport.execute({ executable, args: [malformedFixture] });
assert.deepEqual(adaptRawResult(malformed).stdout, ["valid:€", "bad:\\\\xff\\\\xc3("]);

const requests = [0, 5, 0].map((code, index) => ({
  executable,
  args: [echoFixture, \`--exit-code=\${code}\`, \`node-request-\${index}\`],
}));
const batch = await executeBatch(transport, requests);
assert.deepEqual(batch.map(({ delivery, index, status }) => ({ delivery, index, status })), [
  { delivery: "replied", index: 0, status: "complete" },
  { delivery: "replied", index: 1, status: "failed" },
  { delivery: "replied", index: 2, status: "complete" },
]);

const laterArgs = [echoFixture, "second-original"];
const laterStdin = Uint8Array.of(0x61, 0x62);
const mutableBatchExecution = executeBatch(transport, [
  { executable, args: [echoFixture, "first"] },
  { executable, args: laterArgs },
  { executable, args: [echoFixture, "--echo-stdin"], stdin: laterStdin },
]);
laterArgs[1] = "second-mutated";
laterStdin[0] = 0x7a;
const immutableBatch = await mutableBatchExecution;
assert.deepEqual(JSON.parse(decodeBackslashReplace(immutableBatch[1].rawResult.stdout)), [
  "second-original",
]);
assert.deepEqual(immutableBatch[1].rawResult.cmd, [executable, echoFixture, "second-original"]);
assert.deepEqual([...immutableBatch[2].rawResult.stdout], [0x61, 0x62]);

const controller = new AbortController();
const markerPath = fileURLToPath(new URL("./sigterm-ready", import.meta.url));
const cancelled = transport.execute({
  executable,
  args: [ignoreFixture, markerPath],
  signal: controller.signal,
  stdin: new Uint8Array(8 * 1024 * 1024),
});
await waitForFile(markerPath);
controller.abort();
await assert.rejects(cancelled, (error) => {
  assert.ok(error instanceof TransportError);
  assert.equal(error.delivery, "indeterminate");
  assert.equal(error.kind, "cancelled");
  assert.equal(error.signal, "SIGKILL");
  return true;
});

const timedOut = transport.execute({
  executable,
  args: [ignoreFixture, "--exit-after=2000"],
  timeoutMs: 500,
});
await assert.rejects(timedOut, (error) => {
  assert.ok(error instanceof TransportError);
  assert.equal(error.delivery, "indeterminate");
  assert.equal(error.kind, "timeout");
  assert.equal(error.signal, "SIGKILL");
  return true;
});

const partialPipeMarker = fileURLToPath(new URL("./partial-pipe-holder", import.meta.url));
const partialController = new AbortController();
const partialExecution = transport.execute({
  executable,
  args: [ignoreFixture, "--inherit-pipes=" + partialPipeMarker],
  signal: partialController.signal,
});
await waitForFile(partialPipeMarker);
const partialHolder = await readHolderIdentity(partialPipeMarker);
partialController.abort();
try {
  const partialOutcome = await settleWithin(partialExecution, 800);
  assert.equal(partialOutcome.kind, "error");
  assert.ok(partialOutcome.error instanceof TransportError);
  assert.equal(partialOutcome.error.kind, "cancelled");
  assert.equal(new TextDecoder().decode(partialOutcome.error.stdout), "launch-frame\\n");
  assert.equal(new TextDecoder().decode(partialOutcome.error.stderr), "launch-diagnostic\\n");
  partialOutcome.error.stdout[0] = 0;
  partialOutcome.error.stderr[0] = 0;
  assert.equal(new TextDecoder().decode(partialOutcome.error.stdout), "launch-frame\\n");
  assert.equal(new TextDecoder().decode(partialOutcome.error.stderr), "launch-diagnostic\\n");
} finally {
  await stopHolder(partialHolder);
  await partialExecution.catch(() => undefined);
}

const timeoutPipeMarker = fileURLToPath(new URL("./timeout-pipe-holder", import.meta.url));
const heldPipeTimeout = transport.execute({
  executable,
  args: [ignoreFixture, "--inherit-pipes=" + timeoutPipeMarker],
  timeoutMs: 500,
});
await waitForFile(timeoutPipeMarker);
const timeoutHolder = await readHolderIdentity(timeoutPipeMarker);
try {
  const timeoutOutcome = await settleWithin(heldPipeTimeout, 1400);
  assert.equal(timeoutOutcome.kind, "error");
  assert.ok(timeoutOutcome.error instanceof TransportError);
  assert.equal(timeoutOutcome.error.kind, "timeout");
  assert.equal(new TextDecoder().decode(timeoutOutcome.error.stdout), "launch-frame\\n");
  assert.equal(new TextDecoder().decode(timeoutOutcome.error.stderr), "launch-diagnostic\\n");
} finally {
  await stopHolder(timeoutHolder);
  await heldPipeTimeout.catch(() => undefined);
}

const exitCancelController = new AbortController();
const exitCancelMarker = fileURLToPath(new URL("./exit-cancel", import.meta.url));
const exitCancelled = transport.execute({
  executable,
  args: [echoFixture, "--exit-with-inherited-pipe", exitCancelMarker, "1500"],
  signal: exitCancelController.signal,
});
await waitForFile(exitCancelMarker);
const exitCancelHolder = await readHolderIdentity(exitCancelMarker);
await new Promise((resolve) => setTimeout(resolve, 25));
const cancelledAfterExitAt = performance.now();
exitCancelController.abort();
try {
  const exited = await exitCancelled;
  assert.equal(exited.returncode, 0);
  assert.equal(exited.signal, null);
  assert.ok(performance.now() - cancelledAfterExitAt < 900);
} finally {
  await exitCancelled.catch(() => undefined);
  await stopHolder(exitCancelHolder);
}

const exitTimeoutMarker = fileURLToPath(new URL("./exit-timeout", import.meta.url));
const exitTimeoutAt = performance.now();
const exitTimed = transport.execute({
  executable,
  args: [echoFixture, "--exit-with-inherited-pipe", exitTimeoutMarker, "1500"],
  timeoutMs: 300,
});
await waitForFile(exitTimeoutMarker);
const exitTimeoutHolder = await readHolderIdentity(exitTimeoutMarker);
try {
  const exited = await exitTimed;
  assert.equal(exited.returncode, 0);
  assert.equal(exited.signal, null);
  assert.ok(performance.now() - exitTimeoutAt < 900);
} finally {
  await exitTimed.catch(() => undefined);
  await stopHolder(exitTimeoutHolder);
}

const cleanup = new Error("secondary cleanup failure");
const cleanupPrimary = new Error("primary with reserved cleanup property");
const existingCleanup = new Error("existing cleanup evidence");
Object.defineProperty(cleanupPrimary, "cleanupError", {
  configurable: false,
  value: existingCleanup,
  writable: false,
});
const cleanupReports = [];
const cleanupChannel = channel("libtmux.test.cleanup-failure");
const cleanupListener = (message) => cleanupReports.push(message);
cleanupChannel.subscribe(cleanupListener);
try {
  await assert.rejects(
    runWithCleanup(
      async () => { throw cleanupPrimary; },
      async () => { throw cleanup; },
    ),
    (error) => error === cleanupPrimary,
  );
  assert.equal(cleanupPrimary.cleanupError, existingCleanup);
  assert.deepEqual(cleanupReports, [{ cleanupError: cleanup, primary: cleanupPrimary }]);
} finally {
  cleanupChannel.unsubscribe(cleanupListener);
}

const task4Root = process.env.LIBTMUX_TEST_RUN_ROOT ?? fileURLToPath(new URL("./node, task4 root", import.meta.url));
await prepareRunRoot(task4Root);
let task4Server;
try {
  task4Server = await TestServer.create({ runRoot: task4Root, sessionName: "node-smoke" });
  if (process.env.LIBTMUX_NODE_FAILURE_MARKER) {
    await writeFile(
      process.env.LIBTMUX_NODE_FAILURE_MARKER,
      JSON.stringify({ daemonPid: task4Server.daemonIdentity.pid, root: task4Root }) + "\\n",
    );
  }
  if (process.env.LIBTMUX_NODE_INJECT_FAILURE === "after-create") {
    throw new Error("injected Node assertion failure after fixture creation");
  }
  if (process.env.LIBTMUX_NODE_INJECT_FAILURE === "timeout-after-create") {
    setInterval(() => undefined, 1_000);
    await new Promise(() => {});
  }
  assert.equal(task4Server.observedSocketPath, task4Server.socketPath);
  assert.equal(
    (await task4Server.executeText(["display-message", "-p", "#{socket_path}"])).stdout[0],
    task4Server.socketPath,
  );
} finally {
  await task4Server?.dispose();
  assert.equal((await reapOwnedRunRoot(task4Root)).rootRemoved, true);
}

async function runLateRootSiblingProbe() {
  const probeScript = fileURLToPath(new URL("./late-root-sibling.mjs", import.meta.url));
  const probeRoot = fileURLToPath(new URL("./late-root-sibling.root", import.meta.url));
  const sibling = probeRoot + "/late-sibling";
  const source = [
    'import assert from "node:assert/strict";',
    'import fs from "node:fs";',
    'import { syncBuiltinESMExports } from "node:module";',
    'const runRoot = ' + JSON.stringify(probeRoot) + ';',
    'const sibling = ' + JSON.stringify(sibling) + ';',
    'const ownerPath = runRoot + "/.owner.json";',
    'const ownerEscrow = runRoot + ".owner-escrow";',
    'const realRmdir = fs.promises.rmdir;',
    'let injected = false;',
    'fs.promises.rmdir = async function(path, ...args) {',
    '  if (!injected && path === runRoot) {',
    '    injected = true;',
    '    await fs.promises.mkdir(sibling, { mode: 0o700 });',
    '  }',
    '  return realRmdir.call(fs.promises, path, ...args);',
    '};',
    'syncBuiltinESMExports();',
    'const { prepareRunRoot, reapOwnedRunRoot } = await import(' + JSON.stringify(${runRootModule}) + ');',
    'await prepareRunRoot(runRoot);',
    'const ownerText = await fs.promises.readFile(ownerPath, "utf8");',
    'const ownerBefore = await fs.promises.lstat(ownerPath);',
    'try {',
    '  const report = await reapOwnedRunRoot(runRoot);',
    '  assert.equal(injected, true);',
    '  assert.equal(report.rootRemoved, false);',
    '  assert.ok(report.leaks.some((leak) => leak.includes("ENOTEMPTY")));',
    '  assert.equal((await fs.promises.lstat(sibling)).isDirectory(), true);',
    '  assert.equal(await fs.promises.readFile(ownerPath, "utf8"), ownerText);',
    '  const ownerAfter = await fs.promises.lstat(ownerPath);',
    '  assert.equal(ownerAfter.dev, ownerBefore.dev);',
    '  assert.equal(ownerAfter.ino, ownerBefore.ino);',
    '  await assert.rejects(fs.promises.access(ownerEscrow), (error) => error?.code === "ENOENT");',
    '} finally {',
    '  fs.promises.rmdir = realRmdir;',
    '  syncBuiltinESMExports();',
    '  await fs.promises.rm(sibling, { force: true, recursive: true });',
    '  const cleanup = await reapOwnedRunRoot(runRoot);',
    '  assert.deepEqual(cleanup, { leaks: [], reservationsFound: 0, rootRemoved: true });',
    '}',
    '',
  ].join(String.fromCharCode(10));
  await writeFile(probeScript, source);
  const child = spawn(executable, [probeScript], { stdio: ["ignore", "pipe", "pipe"] });
  const stdout = [];
  const stderr = [];
  child.stdout.on("data", (chunk) => stdout.push(chunk));
  child.stderr.on("data", (chunk) => stderr.push(chunk));
  const closed = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code, signal) => resolve({ code, signal }));
  });
  let outcome;
  try {
    outcome = await settleWithin(closed, 2_000);
    if (outcome.kind === "deadline") {
      child.kill("SIGTERM");
      outcome = await settleWithin(closed, 250);
    }
    if (outcome.kind === "deadline") {
      child.kill("SIGKILL");
      outcome = await settleWithin(closed, 500);
    }
    assert.equal(outcome.kind, "value");
    const stdoutText = Buffer.concat(stdout).toString("utf8");
    const stderrText = Buffer.concat(stderr).toString("utf8");
    if (outcome.value.code !== 0 || outcome.value.signal !== null || stderrText !== "") {
      throw new Error(
        (
          "late-root-sibling probe failed with status " +
          String(outcome.value.code ?? outcome.value.signal) +
          ":\\n" +
          stderrText +
          stdoutText
        ).trim(),
      );
    }
    assert.equal(stdoutText, "");
  } finally {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    await settleWithin(closed, 500);
    await rm(sibling, { force: true, recursive: true });
    const cleanup = await reapStaleRunRoot(probeRoot);
    assert.equal(cleanup.leaks.length, 0);
    assert.equal(cleanup.rootRemoved, true);
  }
}

await runLateRootSiblingProbe();

async function runControlTimerProbe(mode) {
  const probeScript = fileURLToPath(new URL("./control-timer-" + mode + ".mjs", import.meta.url));
  const marker = fileURLToPath(new URL("./control-timer-" + mode + ".done", import.meta.url));
  const wrapper = fileURLToPath(new URL("./control-timer-" + mode + ".sh", import.meta.url));
  const assertedMarker = fileURLToPath(
    new URL("./control-timer-" + mode + ".asserted", import.meta.url),
  );
  const registrationMarker = fileURLToPath(
    new URL("./control-timer-" + mode + ".registration", import.meta.url),
  );
  const spawnedMarker = fileURLToPath(
    new URL("./control-timer-" + mode + ".spawned", import.meta.url),
  );
  const timerRoot = fileURLToPath(new URL("./control-timer-" + mode + ".root", import.meta.url));
  const newline = String.fromCharCode(10);
  await writeFile(
    wrapper,
    [
      "#!/bin/sh",
      "printf spawned > " + JSON.stringify(spawnedMarker),
      "trap '' TERM",
      "while :; do :; done",
      "",
    ].join(newline),
    { mode: 0o700 },
  );
  const body = mode === "partial-open"
    ? [
        'const fakeServer = {',
        '  assertControllerCurrent: async () => writeFile(' + JSON.stringify(assertedMarker) + ', "asserted"),',
        '  controllerEnvironment: Object.freeze({ ...process.env }),',
        '  executeText: async () => {',
        '    await writeFile(' + JSON.stringify(registrationMarker) + ', "probed");',
        '    return new Promise(() => undefined);',
        '  },',
        '  socketPath: "/unused",',
        '  tmuxExecutable: ' + JSON.stringify(wrapper) + ',',
        '};',
        'let openError;',
        'try {',
        '  await ControlMode.open({ server: fakeServer, targetSession: "$0" });',
        '} catch (error) {',
        '  openError = error;',
        '}',
        'if (!(openError instanceof Error) || !openError.message.includes("registration timed out")) {',
        '  throw new Error("partial ControlMode open did not reach its registration deadline");',
        '}',
      ]
    : [
        'await prepareRunRoot(' + JSON.stringify(timerRoot) + ');',
        'let server;',
        'let control;',
        'try {',
        '  server = await TestServer.create({ runRoot: ' + JSON.stringify(timerRoot) + ' });',
        '  control = await ControlMode.open({ server, targetSession: server.sessionId });',
        '} finally {',
        '  await control?.dispose();',
        '  await server?.dispose();',
        '  await reapOwnedRunRoot(' + JSON.stringify(timerRoot) + ');',
        '}',
      ];
  const source = [
    'import { writeFile } from "node:fs/promises";',
    'import { ControlMode } from ' + JSON.stringify(${controlModeModule}) + ';',
    'import { prepareRunRoot, reapOwnedRunRoot } from ' + JSON.stringify(${runRootModule}) + ';',
    'import { TestServer } from ' + JSON.stringify(${moduleUrl("dist/_internal/test/test_server.js")}) + ';',
    ...body,
    'await writeFile(' + JSON.stringify(marker) + ', "done");',
    '',
  ].join(newline);
  await writeFile(probeScript, source);
  const child = spawn(executable, [probeScript], { stdio: ["ignore", "pipe", "pipe"] });
  const stderr = [];
  child.stderr.on("data", (chunk) => stderr.push(chunk));
  const closed = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code, signal) => resolve({ code, signal }));
  });
  await waitForFile(marker, 400);
  if (mode === "partial-open") {
    await access(assertedMarker);
    await access(registrationMarker);
    await access(spawnedMarker);
  }
  const completedAt = performance.now();
  let outcome;
  try {
    outcome = await settleWithin(closed, 300);
  } finally {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    await closed;
  }
  assert.equal(outcome.kind, "value");
  assert.deepEqual(outcome.value, { code: 0, signal: null });
  assert.ok(performance.now() - completedAt < 300);
  assert.equal(Buffer.concat(stderr).toString("utf8"), "");
}

await runControlTimerProbe("partial-open");
await runControlTimerProbe("dispose");

const supervisorRoot = fileURLToPath(new URL("./node-supervisor-root", import.meta.url));
const supervisorMarker = fileURLToPath(new URL("./node-supervisor-ready", import.meta.url));
const holderPath = fileURLToPath(new URL("./node-holder.mjs", import.meta.url));
const supervisorPath = fileURLToPath(new URL("./node-supervisor.mjs", import.meta.url));
await writeFile(
  holderPath,
  \`import { writeFile } from "node:fs/promises";
process.on("SIGTERM", () => undefined);
await writeFile(\${JSON.stringify(supervisorMarker)}, "ready");
setInterval(() => undefined, 1000);\`,
);
await writeFile(
  supervisorPath,
  \`import { runSupervisor } from ${runRootModule};
process.exitCode = await runSupervisor({
  command: [\${JSON.stringify(executable)}, \${JSON.stringify(holderPath)}],
  graceMs: 100,
  runRoot: \${JSON.stringify(supervisorRoot)},
});\`,
);
const supervised = spawn(executable, [supervisorPath], { stdio: ["ignore", "pipe", "pipe"] });
const supervisedClosed = new Promise((resolve, reject) => {
  supervised.once("error", reject);
  supervised.once("close", (code, signal) => resolve({ code, signal }));
});
await waitForFile(supervisorMarker);
supervised.kill("SIGTERM");
const supervisorResult = await supervisedClosed;
assert.ok(supervisorResult.signal === "SIGTERM" || supervisorResult.code === 143);
await assert.rejects(access(supervisorRoot), (error) => error?.code === "ENOENT");

console.log(JSON.stringify({
  protocol: "libtmux-node-scenarios-v1",
  scenarios: [
    "literal-argv",
    "immutable-input",
    "correlated-request",
    "immutable-prepared-input",
    "raw-results",
    "decoding",
    "format-separator-override",
    "public-neo-codec",
    "format-protocol-error",
    "batch",
    "immutable-batch",
    "cancellation",
    "timeout",
    "immutable-partial-output",
    "held-pipe-timeout",
    "post-exit-cancellation",
    "post-exit-timeout",
    "cleanup-precedence",
    "real-tmux-fixture",
    "late-root-sibling-precedence",
    "control-partial-timer",
    "control-dispose-timer",
    "supervisor-sigterm",
  ],
  status: "passed",
}));
`;
}

const args = parseArguments(process.argv.slice(2));
const executable = await resolveNode(args.nodeArgument);
const version = queryMajor(executable, args.expectMajor);
const tsRoot = fileURLToPath(new URL("..", import.meta.url));
const temporaryRoot = await mkdtemp(join(tmpdir(), "libtmux-node-scenarios-"));
const scenarioRunRoot =
  process.env.LIBTMUX_TEST_RUN_ROOT ?? join(temporaryRoot, "node, task4 root");
const scenarioTimeoutMs = Number.parseInt(
  process.env.LIBTMUX_NODE_SCENARIO_TIMEOUT_MS ?? "10000",
  10,
);
if (!Number.isSafeInteger(scenarioTimeoutMs) || scenarioTimeoutMs < 100) {
  throw new Error("LIBTMUX_NODE_SCENARIO_TIMEOUT_MS must be at least 100");
}
let exactCleanupComplete = false;

try {
  const scenarioPath = join(temporaryRoot, "scenarios.mjs");
  await writeFile(scenarioPath, scenarioSource(tsRoot, executable));
  const child = spawn(executable, [scenarioPath], {
    cwd: tsRoot,
    env: {
      ...process.env,
      LIBTMUX_TEST_RUN_ROOT: scenarioRunRoot,
      LIBTMUX_TMUX_FORMAT_SEPARATOR: "NODE_FORMAT_SEPARATOR",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const stdout: Buffer[] = [];
  const stderr: Buffer[] = [];
  child.stdout.on("data", (chunk: Buffer) => stdout.push(chunk));
  child.stderr.on("data", (chunk: Buffer) => stderr.push(chunk));
  const result = await new Promise<{ code: number | null; signal: string | null }>(
    (resolveResult, reject) => {
      let settled = false;
      const finish = (value: { code: number | null; signal: string | null }): void => {
        if (settled) return;
        settled = true;
        clearTimeout(term);
        clearTimeout(kill);
        clearTimeout(hard);
        resolveResult(value);
      };
      child.once("error", reject);
      child.once("close", (code, signal) => finish({ code, signal }));
      const term = setTimeout(() => child.kill("SIGTERM"), scenarioTimeoutMs);
      const kill = setTimeout(() => child.kill("SIGKILL"), scenarioTimeoutMs + 500);
      const hard = setTimeout(() => {
        child.stdout.destroy();
        child.stderr.destroy();
        child.unref();
        finish({ code: null, signal: "SIGKILL" });
      }, scenarioTimeoutMs + 1_000);
    },
  );
  const stdoutText = Buffer.concat(stdout).toString("utf8");
  const stderrText = Buffer.concat(stderr).toString("utf8");
  try {
    await access(scenarioRunRoot);
    const cleanup = await reapStaleRunRoot(scenarioRunRoot);
    if (cleanup.leaks.length > 0 || !cleanup.rootRemoved) {
      throw new Error(`Node scenario cleanup leaked: ${cleanup.leaks.join("; ")}`);
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  exactCleanupComplete = true;
  if (result.code !== 0 || result.signal !== null || stderrText !== "") {
    throw new Error(
      `Node scenarios failed with status ${String(result.code ?? result.signal)}:\n${stderrText}${stdoutText}`.trim(),
    );
  }
  const report = JSON.parse(stdoutText) as ScenarioReport;
  if (
    report.protocol !== "libtmux-node-scenarios-v1" ||
    report.status !== "passed" ||
    report.scenarios.length !== 23
  ) {
    throw new Error(`invalid Node scenario report: ${stdoutText.trim()}`);
  }
  console.log(`${version} runtime scenarios passed: ${report.scenarios.join(", ")}`);
} finally {
  if (exactCleanupComplete) await rm(temporaryRoot, { force: true, recursive: true });
}
