import { spawn } from "node:child_process";
import {
  access,
  chmod,
  lstat,
  link,
  mkdir,
  mkdtemp,
  open,
  readFile,
  readdir,
  realpath,
  rename,
  rmdir,
  unlink,
} from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import { tmpdir } from "node:os";
import { constants as osConstants } from "node:os";
import { basename, delimiter, dirname, isAbsolute, join, parse, resolve } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { channel } from "node:diagnostics_channel";

import { NodeSpawnTransport } from "../transport/node_spawn_transport.js";

export const RUN_ROOT_ENV = "LIBTMUX_TEST_RUN_ROOT";
export const OWNER_RECORD_NAME = ".owner.json";
export const FIXTURE_RECORD_NAME = "fixture.json";
export const SOCKET_PATH_UTF8_LIMIT = 103;

const fixtureProtocol = "libtmux-test-fixture-v3" as const;
const ownerProtocolV2 = "libtmux-test-run-v2" as const;

export interface ProcessIdentity {
  readonly pid: number;
  readonly startIdentity: string;
}

export interface ControllerFileIdentity {
  readonly device: string;
  readonly inode: string;
  readonly kind: "file";
  readonly mode: string;
  readonly uid: string;
}

export interface ControllerIdentity {
  readonly executablePath: string;
  readonly fileIdentity: ControllerFileIdentity;
}

interface OwnerRecord {
  readonly controller: ControllerIdentity;
  readonly owner: ProcessIdentity;
  readonly protocol: typeof ownerProtocolV2;
  readonly runId: string;
}

export interface DaemonIdentity extends ProcessIdentity {
  readonly comm: string;
  readonly executablePath: string;
}

export interface SocketIdentity {
  readonly device: string;
  readonly inode: string;
  readonly kind: "socket";
  readonly mode: string;
  readonly uid: string;
}

export interface LaunchGeneration {
  readonly name: string;
  readonly value: string;
}

interface FixtureRecordBase {
  readonly controller: ControllerIdentity;
  readonly logicalSocketName: string;
  readonly owner: ProcessIdentity;
  readonly protocol: typeof fixtureProtocol;
  readonly runId: string;
  readonly socketPath: string;
}

export type FixtureRecord =
  | (FixtureRecordBase & { readonly phase: "reserved" })
  | (FixtureRecordBase & {
      readonly bootstrapArgv: readonly string[];
      readonly generation: LaunchGeneration;
      readonly phase: "launching";
    })
  | (FixtureRecordBase & {
      readonly bootstrapArgv: readonly string[];
      readonly daemon: DaemonIdentity;
      readonly generation: LaunchGeneration;
      readonly phase: "running";
      readonly socketIdentity: SocketIdentity;
    });

export interface ReapReport {
  readonly leaks: readonly string[];
  readonly reservationsFound: number;
  readonly rootRemoved: boolean;
}

interface CollectedChild {
  readonly code: number | null;
  readonly signal: NodeJS.Signals | null;
  readonly stderr: Uint8Array;
  readonly stdout: Uint8Array;
}

declare const reservationCapabilityBrand: unique symbol;

export interface ReservationCapability {
  readonly [reservationCapabilityBrand]: true;
  readonly recordPath: string;
  readonly reservationPath: string;
  readonly runId: string;
  readonly runRoot: string;
}

declare const launchAttemptCapabilityBrand: unique symbol;

export interface LaunchAttemptCapability {
  readonly [launchAttemptCapabilityBrand]: true;
  readonly attemptId: string;
  readonly recordPath: string;
  readonly reservationPath: string;
  readonly runId: string;
  readonly runRoot: string;
}

const reservationCapabilities = new WeakSet<object>();
const reservationEnvironments = new WeakMap<object, Readonly<Record<string, string>>>();
const launchAttemptCapabilities = new WeakSet<object>();
const launchAttemptReservations = new WeakMap<object, ReservationCapability>();
const launchAttemptSnapshots = new WeakMap<
  object,
  {
    readonly bootstrapArgv: readonly string[];
    readonly generation: LaunchGeneration;
  }
>();
const reservationMutationTails = new Map<string, Promise<void>>();
const identityPattern =
  /^linux:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}:[0-9]+$/u;
const runIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
const logicalSocketPattern = /^[A-Za-z0-9_-]+$/u;
const generatedLogicalSocketPattern = /^t-[a-z0-9]+-[0-9a-f]{8}-[0-9a-f]{3}$/u;
const fixtureEscrowPrefix = ".fixture-escrow-";
const fixtureRecordTemporaryName = ".fixture.json.tmp";
const generationNamePattern = /^LIBTMUX_TEST_GENERATION_[A-F0-9]{32}$/u;
const generationValuePattern = runIdPattern;

function snapshotEnvironment(
  environment: Readonly<Record<string, string | undefined>>,
): Readonly<Record<string, string>> {
  return Object.freeze(
    Object.fromEntries(
      Object.entries(environment).filter(
        (entry): entry is [string, string] => entry[1] !== undefined,
      ),
    ),
  );
}

function isErrno(error: unknown, code: string): boolean {
  return (error as NodeJS.ErrnoException).code === code;
}

function assertSocketIdentity(value: unknown): SocketIdentity {
  if (typeof value !== "object" || value === null) {
    throw new Error("fixture socket identity is missing");
  }
  const candidate = value as Record<string, unknown>;
  if (
    JSON.stringify(Object.keys(candidate).sort()) !==
      JSON.stringify(["device", "inode", "kind", "mode", "uid"]) ||
    candidate.kind !== "socket" ||
    [candidate.device, candidate.inode, candidate.mode, candidate.uid].some(
      (part) => typeof part !== "string" || !/^\d+$/u.test(part),
    ) ||
    (process.geteuid?.() !== undefined && candidate.uid !== String(process.geteuid?.()))
  ) {
    throw new Error("fixture socket identity is corrupt");
  }
  return candidate as unknown as SocketIdentity;
}

function assertControllerFileIdentity(value: unknown): ControllerFileIdentity {
  if (typeof value !== "object" || value === null) {
    throw new Error("tmux controller file identity is missing");
  }
  const candidate = value as Record<string, unknown>;
  if (
    JSON.stringify(Object.keys(candidate).sort()) !==
      JSON.stringify(["device", "inode", "kind", "mode", "uid"]) ||
    candidate.kind !== "file" ||
    [candidate.device, candidate.inode, candidate.mode, candidate.uid].some(
      (part) => typeof part !== "string" || !/^\d+$/u.test(part),
    )
  ) {
    throw new Error("tmux controller file identity is corrupt");
  }
  return candidate as unknown as ControllerFileIdentity;
}

function assertControllerIdentity(value: unknown): ControllerIdentity {
  if (typeof value !== "object" || value === null) {
    throw new Error("tmux controller identity is missing");
  }
  const candidate = value as Record<string, unknown>;
  if (
    JSON.stringify(Object.keys(candidate).sort()) !==
      JSON.stringify(["executablePath", "fileIdentity"]) ||
    typeof candidate.executablePath !== "string" ||
    !isAbsolute(candidate.executablePath)
  ) {
    throw new Error("tmux controller identity is corrupt");
  }
  return {
    executablePath: candidate.executablePath,
    fileIdentity: assertControllerFileIdentity(candidate.fileIdentity),
  };
}

function assertLaunchGeneration(value: unknown): LaunchGeneration {
  if (typeof value !== "object" || value === null) {
    throw new Error("fixture launch generation is missing");
  }
  const candidate = value as Record<string, unknown>;
  if (
    JSON.stringify(Object.keys(candidate).sort()) !== JSON.stringify(["name", "value"]) ||
    typeof candidate.name !== "string" ||
    !generationNamePattern.test(candidate.name) ||
    typeof candidate.value !== "string" ||
    !generationValuePattern.test(candidate.value)
  ) {
    throw new Error("fixture launch generation is corrupt");
  }
  return { name: candidate.name, value: candidate.value };
}

function commandQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

function isGeneratedNewSessionBranch(
  value: string,
  controller: ControllerIdentity,
  socketPath: string,
  generation: LaunchGeneration,
): boolean {
  const prefix = "new-session -d -P -F '#{socket_path}\t#{pid}\t#{session_id}' -s '";
  if (!value.startsWith(prefix)) return false;
  const sessionEnd = value.indexOf("' ", prefix.length);
  if (sessionEnd < 0) return false;
  const sessionName = value.slice(prefix.length, sessionEnd);
  if (!/^[A-Za-z0-9_-]+$/u.test(sessionName)) return false;
  const pane = value.slice(sessionEnd + 2);
  const panePrefix = commandQuote(
    [
      "env",
      "-u",
      commandQuote(generation.name),
      commandQuote(controller.executablePath),
      "-N",
      "-S",
      commandQuote(socketPath),
      "wait-for",
      "-S",
    ].join(" "),
  ).slice(0, -1);
  if (!pane.startsWith(panePrefix)) return false;
  const suffix = pane.slice(panePrefix.length);
  return /^ '"'"'ready-[0-9a-f-]+'"'"' && exec cat'$/u.test(suffix);
}

function assertBootstrapArgv(
  value: unknown,
  controller: ControllerIdentity,
  socketPath: string,
  generation: LaunchGeneration,
): readonly string[] {
  if (
    !Array.isArray(value) ||
    value.length !== 12 ||
    value.some((part) => typeof part !== "string" || part.includes("\0")) ||
    value[0] !== controller.executablePath ||
    JSON.stringify(value.slice(1, 10)) !==
      JSON.stringify([
        "-f",
        "/dev/null",
        "-S",
        socketPath,
        "start-server",
        ";",
        "if-shell",
        "-F",
        `#{==:#{${generation.name}},${generation.value}}`,
      ]) ||
    value.filter((part) => part === "-S" || part.startsWith("-S")).length !== 1 ||
    value.some((part) => part === "-L" || part.startsWith("-L")) ||
    value.filter((part) => part === ";").length !== 1 ||
    !isGeneratedNewSessionBranch(value[10] ?? "", controller, socketPath, generation) ||
    !/^display-message -p 'generation-mismatch-[0-9a-f-]+'$/u.test(value[11] ?? "")
  ) {
    throw new Error("fixture bootstrap argv or generation is corrupt");
  }
  return Object.freeze([...value]) as readonly string[];
}

function assertIdentity(value: unknown, label: string): ProcessIdentity {
  if (typeof value !== "object" || value === null) throw new Error(`${label} is missing`);
  const candidate = value as Record<string, unknown>;
  if (JSON.stringify(Object.keys(candidate).sort()) !== JSON.stringify(["pid", "startIdentity"])) {
    throw new Error(`${label} is corrupt`);
  }
  if (
    !Number.isSafeInteger(candidate.pid) ||
    (candidate.pid as number) < 1 ||
    typeof candidate.startIdentity !== "string" ||
    !identityPattern.test(candidate.startIdentity)
  ) {
    throw new Error(`${label} is corrupt`);
  }
  return { pid: candidate.pid as number, startIdentity: candidate.startIdentity };
}

function controllerFileIdentity(
  metadata: Awaited<ReturnType<typeof lstat>>,
): ControllerFileIdentity {
  if (!metadata.isFile()) throw new Error("tmux controller must be a regular file");
  return {
    device: String(metadata.dev),
    inode: String(metadata.ino),
    kind: "file",
    mode: String(metadata.mode),
    uid: String(metadata.uid),
  };
}

function sameControllerIdentity(left: ControllerIdentity, right: ControllerIdentity): boolean {
  return (
    left.executablePath === right.executablePath &&
    left.fileIdentity.device === right.fileIdentity.device &&
    left.fileIdentity.inode === right.fileIdentity.inode &&
    left.fileIdentity.kind === right.fileIdentity.kind &&
    left.fileIdentity.mode === right.fileIdentity.mode &&
    left.fileIdentity.uid === right.fileIdentity.uid
  );
}

function assertControllerMatchesOwner(
  record: Pick<FixtureRecord, "controller">,
  ownerController: ControllerIdentity,
): void {
  if (!sameControllerIdentity(record.controller, ownerController)) {
    throw new Error("fixture controller does not match test run owner");
  }
}

export async function resolveControllerIdentity(
  executable: string,
  environment: NodeJS.ProcessEnv = process.env,
): Promise<ControllerIdentity> {
  if (executable === "" || executable.includes("\0")) {
    throw new Error("tmux controller executable is invalid");
  }
  let candidate: string | undefined;
  if (executable.includes("/")) {
    candidate = resolve(executable);
  } else {
    const pathValue = environment.PATH ?? "";
    for (const directory of pathValue.split(delimiter)) {
      if (directory === "") continue;
      const possible = join(directory, executable);
      try {
        // eslint-disable-next-line no-await-in-loop -- PATH order is part of executable resolution.
        await access(possible, fsConstants.X_OK);
        candidate = possible;
        break;
      } catch (error) {
        if (!isErrno(error, "ENOENT") && !isErrno(error, "EACCES")) throw error;
      }
    }
  }
  if (candidate === undefined)
    throw new Error(`tmux controller executable not found: ${executable}`);
  const executablePath = await realpath(candidate);
  await access(executablePath, fsConstants.X_OK);
  const metadata = await lstat(executablePath);
  if (metadata.isSymbolicLink()) throw new Error("resolved tmux controller must not be a symlink");
  return { executablePath, fileIdentity: controllerFileIdentity(metadata) };
}

export async function assertControllerCurrent(controller: ControllerIdentity): Promise<void> {
  const executablePath = await realpath(controller.executablePath).catch((error: unknown) => {
    throw new Error("tmux controller path is missing or replaced", { cause: error });
  });
  const observed: ControllerIdentity = {
    executablePath,
    fileIdentity: controllerFileIdentity(await lstat(executablePath)),
  };
  if (!sameControllerIdentity(observed, controller)) {
    throw new Error("tmux controller identity changed");
  }
}

async function assertSafeAbsoluteRoot(runRoot: string): Promise<void> {
  if (!isAbsolute(runRoot)) throw new Error("test run root must be absolute");
  if (resolve(runRoot) !== runRoot) throw new Error("test run root must be canonical");
  if (runRoot === parse(runRoot).root || runRoot === resolve(tmpdir())) {
    throw new Error(`unsafe run root: ${runRoot}`);
  }
  if (basename(runRoot) === "") throw new Error(`unsafe run root: ${runRoot}`);
  const parsed = parse(runRoot);
  const components = runRoot.slice(parsed.root.length).split("/").filter(Boolean);
  let current = parsed.root;
  for (const component of components) {
    current = join(current, component);
    let metadata;
    try {
      // eslint-disable-next-line no-await-in-loop -- every existing component is an independent trust boundary.
      metadata = await lstat(current);
    } catch (error) {
      if (isErrno(error, "ENOENT")) break;
      throw error;
    }
    if (metadata.isSymbolicLink())
      throw new Error(`test run root has a symlink component: ${current}`);
  }
}

async function assertOwnedDirectory(path: string, label: string): Promise<void> {
  const metadata = await lstat(path);
  if (metadata.isSymbolicLink()) throw new Error(`${label} must not be a symlink`);
  if (!metadata.isDirectory()) throw new Error(`${label} must be a directory`);
  if ((metadata.mode & 0o777) !== 0o700) throw new Error(`${label} must have mode 0700`);
  const uid = process.geteuid?.();
  if (uid !== undefined && metadata.uid !== uid) throw new Error(`${label} has the wrong uid`);
  if ((await realpath(path)) !== path) throw new Error(`${label} must be canonical`);
}

export function validateOwnedRecordMetadata(
  metadata: { readonly isRegularFile: boolean; readonly mode: number; readonly uid: number },
  label: string,
  expectedUid: number | undefined,
): void {
  if (!metadata.isRegularFile) throw new Error(`${label} must be a regular file`);
  if ((metadata.mode & 0o777) !== 0o600) throw new Error(`${label} must have mode 0600`);
  if (expectedUid !== undefined && metadata.uid !== expectedUid) {
    throw new Error(`${label} has the wrong uid`);
  }
}

async function readOwnedRecord(path: string, label: string): Promise<string> {
  let handle;
  try {
    handle = await open(path, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
  } catch (error) {
    if (isErrno(error, "ENOENT")) throw new Error(`${label} is missing`, { cause: error });
    if (isErrno(error, "ELOOP"))
      throw new Error(`${label} must not be a symlink`, { cause: error });
    throw error;
  }
  try {
    const metadata = await handle.stat();
    validateOwnedRecordMetadata(
      { isRegularFile: metadata.isFile(), mode: metadata.mode, uid: metadata.uid },
      label,
      process.geteuid?.(),
    );
    return await handle.readFile("utf8");
  } catch (error) {
    if (isErrno(error, "ELOOP"))
      throw new Error(`${label} must not be a symlink`, { cause: error });
    throw error;
  } finally {
    await handle.close();
  }
}

function parseOwnerRecord(text: string): OwnerRecord {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    throw new Error("test run owner record is corrupt", { cause: error });
  }
  if (typeof value !== "object" || value === null) {
    throw new Error("test run owner record is corrupt");
  }
  const candidate = value as Record<string, unknown>;
  if (candidate.protocol !== ownerProtocolV2) {
    throw new Error("test run owner record has bad magic or protocol");
  }
  if (
    JSON.stringify(Object.keys(candidate).sort()) !==
    JSON.stringify(["controller", "owner", "protocol", "runId"])
  ) {
    throw new Error("test run owner record is corrupt");
  }
  if (typeof candidate.runId !== "string" || !runIdPattern.test(candidate.runId)) {
    throw new Error("test run owner record is corrupt");
  }
  return {
    controller: assertControllerIdentity(candidate.controller),
    owner: assertIdentity(candidate.owner, "test run owner identity"),
    protocol: ownerProtocolV2,
    runId: candidate.runId,
  };
}

function parseFixtureRecord(text: string): FixtureRecord {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    throw new Error("fixture identity record is corrupt", { cause: error });
  }
  if (typeof value !== "object" || value === null)
    throw new Error("fixture identity record is corrupt");
  const candidate = value as Record<string, unknown>;
  if (candidate.protocol !== fixtureProtocol) {
    throw new Error("fixture identity record has bad magic or protocol");
  }
  const commonKeys = [
    "controller",
    "logicalSocketName",
    "owner",
    "phase",
    "protocol",
    "runId",
    "socketPath",
  ];
  const phase = candidate.phase;
  const expectedKeys = [
    ...commonKeys,
    ...(phase === "launching" || phase === "running" ? ["bootstrapArgv", "generation"] : []),
    ...(phase === "running" ? ["daemon", "socketIdentity"] : []),
  ].sort();
  if (JSON.stringify(Object.keys(candidate).sort()) !== JSON.stringify(expectedKeys)) {
    throw new Error("fixture identity record is corrupt");
  }
  if (
    typeof candidate.logicalSocketName !== "string" ||
    candidate.logicalSocketName === "" ||
    typeof candidate.socketPath !== "string" ||
    !isAbsolute(candidate.socketPath) ||
    typeof candidate.runId !== "string" ||
    !runIdPattern.test(candidate.runId)
  ) {
    throw new Error("fixture identity record is corrupt");
  }
  const parsedPhase =
    phase === "reserved" || phase === "launching" || phase === "running"
      ? phase
      : (() => {
          throw new Error("fixture identity record is corrupt");
        })();
  const controller = assertControllerIdentity(candidate.controller);
  const base: FixtureRecordBase = {
    controller,
    logicalSocketName: candidate.logicalSocketName,
    owner: assertIdentity(candidate.owner, "fixture owner identity"),
    protocol: fixtureProtocol,
    runId: candidate.runId,
    socketPath: candidate.socketPath,
  };
  if (parsedPhase === "reserved") return { ...base, phase: "reserved" };
  const generation = assertLaunchGeneration(candidate.generation);
  const bootstrapArgv = assertBootstrapArgv(
    candidate.bootstrapArgv,
    controller,
    candidate.socketPath,
    generation,
  );
  if (parsedPhase === "launching") {
    return { ...base, bootstrapArgv, generation, phase: "launching" };
  }
  return {
    ...base,
    bootstrapArgv,
    daemon: assertDaemonIdentity(candidate.daemon),
    generation,
    phase: "running",
    socketIdentity: assertSocketIdentity(candidate.socketIdentity),
  };
}

function assertDaemonIdentity(value: unknown): DaemonIdentity {
  if (typeof value !== "object" || value === null) throw new Error("daemon identity is missing");
  const candidate = value as Record<string, unknown>;
  if (
    JSON.stringify(Object.keys(candidate).sort()) !==
    JSON.stringify(["comm", "executablePath", "pid", "startIdentity"])
  ) {
    throw new Error("daemon identity is corrupt");
  }
  const identity = assertIdentity(
    { pid: candidate.pid, startIdentity: candidate.startIdentity },
    "daemon identity",
  );
  if (
    typeof candidate.comm !== "string" ||
    candidate.comm !== "tmux: server" ||
    typeof candidate.executablePath !== "string" ||
    !isAbsolute(candidate.executablePath)
  ) {
    throw new Error("daemon identity is corrupt");
  }
  return { ...identity, comm: candidate.comm, executablePath: candidate.executablePath };
}

export function parseProcStatStartTime(line: string): string {
  const closing = line.lastIndexOf(") ");
  if (closing < 0) throw new Error("invalid /proc stat framing");
  const fields = line
    .slice(closing + 2)
    .trim()
    .split(/\s+/u);
  const startTime = fields[19];
  if (startTime === undefined || !/^\d+$/u.test(startTime)) {
    throw new Error("invalid /proc start time");
  }
  return startTime;
}

export async function readProcessIdentity(pid: number): Promise<ProcessIdentity | undefined> {
  if (!Number.isSafeInteger(pid) || pid < 1) throw new TypeError("pid must be a positive integer");
  try {
    const [bootId, statText] = await Promise.all([
      readFile("/proc/sys/kernel/random/boot_id", "utf8"),
      readFile(`/proc/${String(pid)}/stat`, "utf8"),
    ]);
    return {
      pid,
      startIdentity: `linux:${bootId.trim()}:${parseProcStatStartTime(statText)}`,
    };
  } catch (error) {
    if (isErrno(error, "ENOENT") || isErrno(error, "ESRCH")) return undefined;
    throw error;
  }
}

export async function readDaemonIdentity(pid: number): Promise<DaemonIdentity | undefined> {
  const identity = await readProcessIdentity(pid);
  if (identity === undefined) return undefined;
  try {
    const [comm, executablePath] = await Promise.all([
      readFile(`/proc/${String(pid)}/comm`, "utf8"),
      realpath(`/proc/${String(pid)}/exe`),
    ]);
    if (comm.trim() !== "tmux: server") return undefined;
    return { ...identity, comm: comm.trim(), executablePath };
  } catch (error) {
    if (isErrno(error, "ENOENT") || isErrno(error, "ESRCH")) return undefined;
    throw error;
  }
}

function sameDaemonIdentity(left: DaemonIdentity, right: DaemonIdentity): boolean {
  return (
    left.pid === right.pid &&
    left.startIdentity === right.startIdentity &&
    left.comm === right.comm &&
    left.executablePath === right.executablePath
  );
}

class ForeignSocketEvidenceError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ForeignSocketEvidenceError";
  }
}

function socketIdentityFromMetadata(metadata: Awaited<ReturnType<typeof lstat>>): SocketIdentity {
  if (!metadata.isSocket()) throw new ForeignSocketEvidenceError("fixture socket is not a socket");
  const uid = process.geteuid?.();
  if (uid !== undefined && metadata.uid !== uid) {
    throw new ForeignSocketEvidenceError("fixture socket has the wrong uid");
  }
  return {
    device: String(metadata.dev),
    inode: String(metadata.ino),
    kind: "socket",
    mode: String(metadata.mode),
    uid: String(metadata.uid),
  };
}

async function writeExclusiveJson(path: string, value: unknown): Promise<void> {
  const handle = await open(path, "wx", 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(value)}\n`, "utf8");
  } finally {
    await handle.close();
  }
}

async function writeAtomicDurableJson(path: string, value: unknown): Promise<void> {
  const temporary = join(dirname(path), ".journal.tmp");
  const handle = await open(temporary, "wx", 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(value)}\n`, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  await rename(temporary, path);
}

async function writeAtomicJson(
  path: string,
  value: unknown,
  faultInjection?: "partial-write",
): Promise<void> {
  const temporary = join(dirname(path), fixtureRecordTemporaryName);
  try {
    const handle = await open(temporary, "wx", 0o600);
    if (faultInjection === "partial-write") {
      try {
        await handle.writeFile('{"partial":', "utf8");
        await handle.sync();
      } finally {
        await handle.close();
      }
      throw new Error("injected partial identity record write failure");
    }
    try {
      await handle.writeFile(`${JSON.stringify(value)}\n`, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporary, path);
  } catch (error) {
    await unlink(temporary).catch(() => undefined);
    throw error;
  }
}

async function readOwner(runRoot: string): Promise<OwnerRecord> {
  try {
    return parseOwnerRecord(
      await readOwnedRecord(join(runRoot, OWNER_RECORD_NAME), "test run owner record"),
    );
  } catch (error) {
    if (isErrno(error, "ENOENT"))
      throw new Error("test run owner record is missing", { cause: error });
    throw error;
  }
}

export async function readFixtureRecord(reservationPath: string): Promise<FixtureRecord> {
  return parseFixtureRecord(
    await readOwnedRecord(join(reservationPath, FIXTURE_RECORD_NAME), "fixture identity record"),
  );
}

async function publishOwner(runRoot: string, controller: ControllerIdentity): Promise<void> {
  const owner = await readProcessIdentity(process.pid);
  if (owner === undefined) throw new Error("cannot identify test run owner process");
  await writeExclusiveJson(join(runRoot, OWNER_RECORD_NAME), {
    controller,
    owner,
    protocol: ownerProtocolV2,
    runId: randomUUID(),
  });
}

export async function prepareRunRoot(
  runRoot: string,
  tmuxExecutable = "tmux",
  environment: NodeJS.ProcessEnv = process.env,
): Promise<void> {
  const controller = await resolveControllerIdentity(tmuxExecutable, environment);
  await assertSafeAbsoluteRoot(runRoot);
  try {
    await lstat(runRoot);
  } catch (error) {
    if (!isErrno(error, "ENOENT")) throw error;
    await reapDetachedOwnerEscrow(runRoot, "stale");
  }
  try {
    await mkdir(runRoot, { mode: 0o700 });
    await chmod(runRoot, 0o700);
    await publishOwner(runRoot, controller);
    return;
  } catch (error) {
    if (!isErrno(error, "EEXIST")) throw error;
  }

  await assertOwnedDirectory(runRoot, "test run root");
  await restoreEscrowedOwner(runRoot);
  const record = await readOwner(runRoot);
  const observed = await readProcessIdentity(record.owner.pid);
  if (observed?.startIdentity === record.owner.startIdentity) {
    throw new Error(`test run root has a live owner: ${String(record.owner.pid)}`);
  }
  const report = await reapRunRootInternal(runRoot, "stale");
  if (report.leaks.length > 0 || !report.rootRemoved) {
    throw new Error(`stale test run root leaked: ${report.leaks.join("; ")}`);
  }
  await mkdir(runRoot, { mode: 0o700 });
  await chmod(runRoot, 0o700);
  await publishOwner(runRoot, controller);
}

export function validateSocketPath(socketPath: string): void {
  const byteLength = Buffer.byteLength(socketPath, "utf8");
  if (byteLength > SOCKET_PATH_UTF8_LIMIT) {
    throw new Error(
      `Unix socket path exceeds ${String(SOCKET_PATH_UTF8_LIMIT)} UTF-8 bytes: ${String(byteLength)}`,
    );
  }
}

export async function reserveFixture(
  runRoot: string,
  environment: Readonly<Record<string, string | undefined>> = process.env,
): Promise<{
  capability: ReservationCapability;
  record: Extract<FixtureRecord, { readonly phase: "reserved" }>;
  recordPath: string;
  reservationPath: string;
}> {
  await assertSafeAbsoluteRoot(runRoot);
  await assertOwnedDirectory(runRoot, "test run root");
  const rootOwner = await readOwner(runRoot);
  await assertControllerCurrent(rootOwner.controller);
  const owner = await readProcessIdentity(process.pid);
  if (owner === undefined) throw new Error("cannot identify fixture owner process");

  for (let attempt = 0; attempt < 100; attempt += 1) {
    const logicalSocketName = `t-${process.pid.toString(36)}-${randomUUID().slice(0, 12)}`;
    const reservationPath = join(runRoot, logicalSocketName);
    try {
      // eslint-disable-next-line no-await-in-loop -- each retry must win one atomic mkdir before proceeding.
      await mkdir(reservationPath, { mode: 0o700 });
      // eslint-disable-next-line no-await-in-loop -- mode belongs to the reservation won in this iteration.
      await chmod(reservationPath, 0o700);
      const socketPath = join(reservationPath, "s");
      validateSocketPath(socketPath);
      const record: Extract<FixtureRecord, { readonly phase: "reserved" }> = {
        controller: rootOwner.controller,
        logicalSocketName,
        owner,
        phase: "reserved",
        protocol: fixtureProtocol,
        runId: rootOwner.runId,
        socketPath,
      };
      const recordPath = join(reservationPath, FIXTURE_RECORD_NAME);
      // eslint-disable-next-line no-await-in-loop -- registration must complete before returning this reservation.
      await writeAtomicJson(recordPath, record);
      const capability = {
        recordPath,
        reservationPath,
        runId: rootOwner.runId,
        runRoot,
      } as ReservationCapability;
      reservationCapabilities.add(capability);
      reservationEnvironments.set(capability, snapshotEnvironment(environment));
      return { capability, record, recordPath, reservationPath };
    } catch (error) {
      if (isErrno(error, "EEXIST")) continue;
      // eslint-disable-next-line no-await-in-loop -- cleanup is scoped to the failed atomic reservation attempt.
      await unlink(join(reservationPath, FIXTURE_RECORD_NAME)).catch(() => undefined);
      // eslint-disable-next-line no-await-in-loop -- cleanup is scoped to the failed atomic reservation attempt.
      await rmdir(reservationPath).catch(() => undefined);
      throw error;
    }
  }
  throw new Error("could not reserve a unique test socket name");
}

export interface FixtureControllerRequest {
  readonly args: readonly string[];
  readonly environment: Readonly<Record<string, string>>;
  readonly executable: string;
  readonly purpose: "validation";
}

interface PromotionOptions {
  readonly faultInjection?: "partial-write";
  readonly observeRequest?: (request: FixtureControllerRequest) => void;
}

function sameLaunchSnapshot(
  record: Extract<FixtureRecord, { readonly phase: "launching" | "running" }>,
  snapshot: { readonly bootstrapArgv: readonly string[]; readonly generation: LaunchGeneration },
): boolean {
  return (
    record.generation.name === snapshot.generation.name &&
    record.generation.value === snapshot.generation.value &&
    JSON.stringify(record.bootstrapArgv) === JSON.stringify(snapshot.bootstrapArgv)
  );
}

function assertLaunchAttempt(attempt: LaunchAttemptCapability): {
  readonly capability: ReservationCapability;
  readonly snapshot: {
    readonly bootstrapArgv: readonly string[];
    readonly generation: LaunchGeneration;
  };
} {
  if (!launchAttemptCapabilities.has(attempt)) {
    throw new Error("fixture transition requires an authenticated launch-attempt capability");
  }
  const capability = launchAttemptReservations.get(attempt);
  const snapshot = launchAttemptSnapshots.get(attempt);
  if (capability === undefined || snapshot === undefined) {
    throw new Error("fixture launch-attempt capability is incomplete");
  }
  return { capability, snapshot };
}

function readNulFrames(bytes: Uint8Array, label: string): readonly string[] {
  if (bytes.length === 0 || bytes.at(-1) !== 0) throw new Error(`${label} has invalid NUL framing`);
  let values: string[];
  try {
    values = new TextDecoder("utf-8", { fatal: true }).decode(bytes).split("\0");
  } catch (error) {
    throw new Error(`${label} is not valid UTF-8`, { cause: error });
  }
  if (values.at(-1) === "") values.pop();
  if (values.some((value) => value === "")) throw new Error(`${label} has empty entries`);
  return values;
}

function assertExactGenerationEntry(bytes: Uint8Array, generation: LaunchGeneration): void {
  if (bytes.length === 0 || bytes.at(-1) !== 0) {
    throw new Error("daemon environment has invalid NUL framing");
  }
  const expected = Buffer.from(`${generation.name}=${generation.value}`, "ascii");
  const prefix = Buffer.from(`${generation.name}=`, "ascii");
  const matches: Buffer[] = [];
  let start = 0;
  for (let index = 0; index < bytes.length; index += 1) {
    if (bytes[index] !== 0) continue;
    const frame = Buffer.from(bytes.slice(start, index));
    if (frame.length === 0) throw new Error("daemon environment has empty entries");
    if (frame.subarray(0, prefix.length).equals(prefix)) matches.push(frame);
    start = index + 1;
  }
  if (matches.length !== 1 || !matches[0]?.equals(expected)) {
    throw new Error("daemon generation mismatch");
  }
}

async function assertExactProcessLaunch(
  record: Extract<FixtureRecord, { readonly phase: "launching" | "running" }>,
  daemon: DaemonIdentity,
): Promise<void> {
  const observed = await readDaemonIdentity(daemon.pid);
  if (observed === undefined || !sameDaemonIdentity(observed, daemon)) {
    throw new Error(`daemon identity mismatch for PID ${String(daemon.pid)}`);
  }
  if (daemon.executablePath !== record.controller.executablePath) {
    throw new Error(`daemon executable identity mismatch for PID ${String(daemon.pid)}`);
  }
  const arguments_ = readNulFrames(
    await readFile(`/proc/${String(daemon.pid)}/cmdline`),
    "daemon command line",
  );
  if (JSON.stringify(arguments_) !== JSON.stringify(record.bootstrapArgv)) {
    throw new Error(`daemon bootstrap argv mismatch for PID ${String(daemon.pid)}`);
  }
  assertExactGenerationEntry(
    await readFile(`/proc/${String(daemon.pid)}/environ`),
    record.generation,
  );
}

function controllerEnvironment(
  capability: ReservationCapability,
  generationName: string,
): Readonly<Record<string, string>> {
  const base = reservationEnvironments.get(capability);
  if (base === undefined) {
    throw new Error("fixture reservation environment snapshot is missing");
  }
  const copy = { ...base };
  delete copy[generationName];
  return Object.freeze(copy);
}

async function validateGenerationAuthority(
  capability: ReservationCapability,
  record: Extract<FixtureRecord, { readonly phase: "launching" | "running" }>,
  daemonPid: number,
  options: PromotionOptions = {},
): Promise<{ readonly daemon: DaemonIdentity; readonly socketIdentity: SocketIdentity }> {
  await assertControllerCurrent(record.controller);
  const daemon = await readDaemonIdentity(daemonPid);
  if (daemon === undefined) {
    throw new Error("tmux daemon identity is missing after launch");
  }
  await assertExactProcessLaunch(record, daemon);
  let beforeMetadata: Awaited<ReturnType<typeof lstat>>;
  try {
    beforeMetadata = await lstat(record.socketPath);
  } catch (error) {
    if (isErrno(error, "ENOENT"))
      throw new Error("fixture socket is missing during generation validation");
    throw error;
  }
  const before = socketIdentityFromMetadata(beforeMetadata);
  const matchedMarker = `generation-match-${randomUUID()}`;
  const mismatchMarker = `generation-mismatch-${randomUUID()}`;
  const environment = controllerEnvironment(capability, record.generation.name);
  const args = Object.freeze([
    "-N",
    "-S",
    record.socketPath,
    "if-shell",
    "-F",
    `#{&&:#{==:#{pid},${String(daemon.pid)}},#{==:#{${record.generation.name}},${record.generation.value}}}`,
    `show-environment -g ${record.generation.name}`,
    `display-message -p ${mismatchMarker}`,
  ]);
  options.observeRequest?.(
    Object.freeze({
      args,
      environment,
      executable: record.controller.executablePath,
      purpose: "validation" as const,
    }),
  );
  await assertControllerCurrent(record.controller);
  const result = await new NodeSpawnTransport({ terminationGraceMs: 100 }).execute({
    args,
    environment,
    executable: record.controller.executablePath,
    timeoutMs: 1_000,
  });
  const output = new TextDecoder("utf-8", { fatal: true }).decode(result.stdout);
  if (result.returncode !== 0) throw new Error("fixture generation validation request failed");
  if (output === `${mismatchMarker}\n`) {
    throw new ForeignSocketEvidenceError("fixture socket server generation mismatch");
  }
  if (output !== `${record.generation.name}=${record.generation.value}\n`) {
    throw new Error(`fixture generation validation returned an invalid frame: ${matchedMarker}`);
  }
  await assertControllerCurrent(record.controller);
  await assertExactProcessLaunch(record, daemon);
  const after = socketIdentityFromMetadata(await lstat(record.socketPath));
  if (!sameEntry(before, after)) {
    throw new ForeignSocketEvidenceError(
      "fixture socket identity changed during generation validation",
    );
  }
  return { daemon, socketIdentity: before };
}

export async function beginFixtureLaunch(
  capability: ReservationCapability,
  launch: {
    readonly bootstrapArgv: readonly string[];
    readonly generation: LaunchGeneration;
  },
): Promise<LaunchAttemptCapability> {
  return serializeReservationMutation(capability, async () => {
    const current = await preflightReservation(capability);
    if (current.record.phase !== "reserved") {
      throw new Error(`fixture launch requires reserved, received ${current.record.phase}`);
    }
    const generation = assertLaunchGeneration(launch.generation);
    const bootstrapArgv = assertBootstrapArgv(
      launch.bootstrapArgv,
      current.record.controller,
      current.record.socketPath,
      generation,
    );
    const updated: Extract<FixtureRecord, { readonly phase: "launching" }> = {
      ...current.record,
      bootstrapArgv,
      generation,
      phase: "launching",
    };
    await writeAtomicJson(capability.recordPath, updated);
    const attempt = {
      attemptId: randomUUID(),
      recordPath: capability.recordPath,
      reservationPath: capability.reservationPath,
      runId: capability.runId,
      runRoot: capability.runRoot,
    } as LaunchAttemptCapability;
    launchAttemptCapabilities.add(attempt);
    launchAttemptReservations.set(attempt, capability);
    launchAttemptSnapshots.set(attempt, { bootstrapArgv, generation });
    return attempt;
  });
}

export async function rollbackFixtureLaunchNotStarted(
  attempt: LaunchAttemptCapability,
): Promise<Extract<FixtureRecord, { readonly phase: "reserved" }>> {
  const { capability, snapshot } = assertLaunchAttempt(attempt);
  return serializeReservationMutation(capability, async () => {
    const current = await preflightReservation(capability);
    if (current.record.phase !== "launching" || !sameLaunchSnapshot(current.record, snapshot)) {
      throw new Error("fixture launch rollback does not match the durable launch attempt");
    }
    if (current.socketPresent) {
      throw new Error("fixture launch rollback requires an absent socket");
    }
    const updated: Extract<FixtureRecord, { readonly phase: "reserved" }> = {
      controller: current.record.controller,
      logicalSocketName: current.record.logicalSocketName,
      owner: current.record.owner,
      phase: "reserved",
      protocol: fixtureProtocol,
      runId: current.record.runId,
      socketPath: current.record.socketPath,
    };
    await writeAtomicJson(capability.recordPath, updated);
    launchAttemptCapabilities.delete(attempt);
    launchAttemptReservations.delete(attempt);
    launchAttemptSnapshots.delete(attempt);
    return updated;
  });
}

export async function promoteFixtureLaunch(
  attempt: LaunchAttemptCapability,
  daemonPid: number,
  options: PromotionOptions = {},
): Promise<Extract<FixtureRecord, { readonly phase: "running" }>> {
  const { capability, snapshot } = assertLaunchAttempt(attempt);
  return serializeReservationMutation(capability, async () => {
    const current = await preflightReservation(capability);
    if (current.record.phase !== "launching" || !sameLaunchSnapshot(current.record, snapshot)) {
      throw new Error("fixture promotion does not match the durable launch attempt");
    }
    const authority = await validateGenerationAuthority(
      capability,
      current.record,
      daemonPid,
      options,
    );
    const updated: Extract<FixtureRecord, { readonly phase: "running" }> = {
      ...current.record,
      daemon: authority.daemon,
      phase: "running",
      socketIdentity: authority.socketIdentity,
    };
    await writeAtomicJson(capability.recordPath, updated, options.faultInjection);
    launchAttemptCapabilities.delete(attempt);
    launchAttemptReservations.delete(attempt);
    launchAttemptSnapshots.delete(attempt);
    return updated;
  });
}

async function collectChild(
  executable: string,
  args: readonly string[],
  environment: NodeJS.ProcessEnv = process.env,
): Promise<CollectedChild> {
  const child = spawn(executable, [...args], {
    env: environment,
    shell: false,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const stdout: Buffer[] = [];
  const stderr: Buffer[] = [];
  child.stdout.on("data", (chunk: Buffer) => stdout.push(chunk));
  child.stderr.on("data", (chunk: Buffer) => stderr.push(chunk));
  return new Promise((resolveChild, reject) => {
    let settled = false;
    let termTimer: NodeJS.Timeout | undefined;
    let killTimer: NodeJS.Timeout | undefined;
    let closeTimer: NodeJS.Timeout | undefined;
    const finish = (result: CollectedChild): void => {
      if (settled) return;
      settled = true;
      if (termTimer !== undefined) clearTimeout(termTimer);
      if (killTimer !== undefined) clearTimeout(killTimer);
      if (closeTimer !== undefined) clearTimeout(closeTimer);
      resolveChild(result);
    };
    child.once("error", (error) => {
      if (settled) return;
      settled = true;
      reject(error);
    });
    child.once("close", (code, signal) =>
      finish({
        code,
        signal,
        stderr: Buffer.concat(stderr),
        stdout: Buffer.concat(stdout),
      }),
    );
    termTimer = setTimeout(() => child.kill("SIGTERM"), 750);
    killTimer = setTimeout(() => child.kill("SIGKILL"), 1_000);
    closeTimer = setTimeout(() => {
      child.stdout?.destroy();
      child.stderr?.destroy();
      child.unref();
      finish({
        code: null,
        signal: "SIGKILL",
        stderr: Buffer.concat([
          ...stderr,
          Buffer.from("helper close exceeded hard deadline", "utf8"),
        ]),
        stdout: Buffer.concat(stdout),
      });
    }, 1_250);
  });
}

const pidfdHelper = String.raw`
import json, os, select, signal, sys

def identity(pid):
    with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as stream:
        boot = stream.read().strip()
    with open(f"/proc/{pid}/stat", encoding="utf-8") as stream:
        text = stream.read()
    fields = text[text.rfind(") ") + 2:].split()
    return f"linux:{boot}:{fields[19]}"

def daemon_identity(pid):
    with open(f"/proc/{pid}/comm", encoding="utf-8") as stream:
        comm = stream.read().strip()
    executable = os.path.realpath(f"/proc/{pid}/exe")
    return identity(pid), comm, executable

def nul_frames(path):
    with open(path, "rb") as stream:
        raw = stream.read()
    if not raw or raw[-1:] != b"\0":
        return None
    try:
        values = raw.decode("utf-8", errors="strict").split("\0")
    except UnicodeDecodeError:
        return None
    if values and values[-1] == "":
        values.pop()
    if any(value == "" for value in values):
        return None
    return values

def launch_matches(pid, expected_argv, generation_name, generation_value):
    arguments = nul_frames(f"/proc/{pid}/cmdline")
    with open(f"/proc/{pid}/environ", "rb") as stream:
        environment = stream.read()
    expected_generation = f"{generation_name}={generation_value}".encode("ascii")
    generation_prefix = f"{generation_name}=".encode("ascii")
    valid_environment = bool(environment) and environment[-1:] == b"\0"
    frames = environment[:-1].split(b"\0") if valid_environment else []
    return (
        arguments == expected_argv
        and valid_environment
        and all(frame for frame in frames)
        and [entry for entry in frames if entry.startswith(generation_prefix)]
            == [expected_generation]
    )

def matches(pid, expected_identity, expected_comm, expected_executable, expected_argv, generation_name, generation_value):
    return (
        daemon_identity(pid) == (expected_identity, expected_comm, expected_executable)
        and launch_matches(pid, expected_argv, generation_name, generation_value)
    )

pid = int(sys.argv[1])
expected = sys.argv[2]
expected_comm = sys.argv[3]
expected_executable = sys.argv[4]
expected_argv = json.loads(sys.argv[5])
generation_name = sys.argv[6]
generation_value = sys.argv[7]
try:
    if not matches(pid, expected, expected_comm, expected_executable, expected_argv, generation_name, generation_value):
        print(json.dumps({"status": "identity-mismatch"}))
        raise SystemExit(3)
    descriptor = os.pidfd_open(pid, 0)
    try:
        if not matches(pid, expected, expected_comm, expected_executable, expected_argv, generation_name, generation_value):
            print(json.dumps({"status": "identity-mismatch"}))
            raise SystemExit(3)
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        poller = select.poll()
        poller.register(descriptor, select.POLLIN)
        escalated = not bool(poller.poll(500))
        if escalated:
            if not matches(pid, expected, expected_comm, expected_executable, expected_argv, generation_name, generation_value):
                print(json.dumps({"status": "identity-mismatch"}))
                raise SystemExit(3)
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        if not poller.poll(2000):
            print(json.dumps({"status": "still-live"}))
            raise SystemExit(4)
        print(json.dumps({"escalated": escalated, "status": "reaped"}))
    finally:
        os.close(descriptor)
except (ProcessLookupError, FileNotFoundError):
    print(json.dumps({"status": "gone"}))
except (AttributeError, NotImplementedError, OSError) as error:
    print(json.dumps({"status": "unavailable", "error": str(error)}))
    raise SystemExit(5)
`;

const PIDFD_PROBE_SOURCE = "import os, sys; sys.exit(0 if hasattr(os, 'pidfd_open') else 1)";
const PIDFD_INTERPRETER_CANDIDATES: readonly string[] = ["python3", "/usr/bin/python3"];

/**
 * CPython gates `os.pidfd_open` on a build-time capability check, so an
 * interpreter first on `PATH` — a virtualenv, or a free-threading build — can
 * lack it while another on the same machine has it. Reaping a daemon whose
 * socket was already unlinked has no other route, and an interpreter chosen
 * without checking presents that gap as substrate flakiness: the daemon and its
 * reservation survive, and the next run inherits them.
 */
export async function resolvePidfdInterpreter(
  candidates: readonly string[],
  probe: (executable: string) => Promise<boolean>,
): Promise<string | undefined> {
  for (const candidate of candidates) {
    try {
      // eslint-disable-next-line no-await-in-loop -- First match wins, so later candidates must never be spawned.
      if (await probe(candidate)) return candidate;
    } catch {
      // A candidate that cannot be spawned is simply not a usable interpreter.
    }
  }
  return undefined;
}

async function probePidfdInterpreter(executable: string): Promise<boolean> {
  const result = await collectChild(executable, ["-I", "-c", PIDFD_PROBE_SOURCE]);
  return result.code === 0;
}

let resolvedPidfdInterpreter: Promise<string | undefined> | undefined;

function defaultPidfdInterpreter(): Promise<string | undefined> {
  resolvedPidfdInterpreter ??= resolvePidfdInterpreter(
    PIDFD_INTERPRETER_CANDIDATES,
    probePidfdInterpreter,
  );
  return resolvedPidfdInterpreter;
}

async function reapViaPidfd(
  capability: ReservationCapability,
  record: Extract<FixtureRecord, { readonly phase: "launching" | "running" }>,
  identity: DaemonIdentity,
): Promise<string | undefined> {
  const environment = controllerEnvironment(capability, record.generation.name);
  // An explicitly configured interpreter is authoritative and is never probed
  // or substituted; probing it would both override the choice and hang on a
  // helper written to hang.
  const python = environment.LIBTMUX_TEST_PYTHON ?? (await defaultPidfdInterpreter());
  if (python === undefined) {
    return `pidfd cleanup unavailable: no interpreter in ${PIDFD_INTERPRETER_CANDIDATES.join(", ")} exposes os.pidfd_open; set LIBTMUX_TEST_PYTHON to one that does`;
  }
  const result = await collectChild(
    python,
    [
      "-I",
      "-c",
      pidfdHelper,
      String(identity.pid),
      identity.startIdentity,
      identity.comm,
      identity.executablePath,
      JSON.stringify(record.bootstrapArgv),
      record.generation.name,
      record.generation.value,
    ],
    environment,
  ).catch((error: unknown) => ({ error }));
  if ("error" in result) return `pidfd cleanup unavailable: ${String(result.error)}`;
  if (result.code === 0) return undefined;
  const diagnostic = new TextDecoder().decode(result.stdout).trim();
  return `pidfd cleanup refused daemon ${String(identity.pid)}: ${diagnostic || String(result.code)}`;
}

async function socketExists(socketPath: string): Promise<boolean> {
  try {
    const metadata = await lstat(socketPath);
    return metadata.isSocket();
  } catch (error) {
    if (isErrno(error, "ENOENT")) return false;
    throw error;
  }
}

interface EntryIdentity {
  readonly device: string;
  readonly inode: string;
  readonly kind: "directory" | "file" | "other" | "socket";
  readonly mode: string;
  readonly uid: string;
}

const fixtureEscrowProtocol = "libtmux-fixture-escrow-v3" as const;

interface FixtureEscrowJournal {
  readonly logicalSocketName: string;
  readonly protocol: typeof fixtureEscrowProtocol;
  readonly record: EntryIdentity;
  readonly recordDigest: string;
  readonly recordPath: string;
  readonly recordSnapshot: FixtureRecord;
  readonly reservation: EntryIdentity;
  readonly reservationPath: string;
  readonly runId: string;
  readonly socket?: EntryIdentity;
  readonly socketPath: string;
}

function entryIdentity(metadata: Awaited<ReturnType<typeof lstat>>): EntryIdentity {
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

function sameEntry(left: EntryIdentity, right: EntryIdentity): boolean {
  return (
    left.device === right.device &&
    left.inode === right.inode &&
    left.kind === right.kind &&
    left.mode === right.mode &&
    left.uid === right.uid
  );
}

function parseJournalIdentity(value: unknown, expectedKind: EntryIdentity["kind"]): EntryIdentity {
  if (typeof value !== "object" || value === null) {
    throw new Error("fixture escrow journal identity is missing");
  }
  const candidate = value as Record<string, unknown>;
  if (
    JSON.stringify(Object.keys(candidate).sort()) !==
      JSON.stringify(["device", "inode", "kind", "mode", "uid"]) ||
    candidate.kind !== expectedKind ||
    [candidate.device, candidate.inode, candidate.mode, candidate.uid].some(
      (part) => typeof part !== "string" || !/^\d+$/u.test(part),
    )
  ) {
    throw new Error("fixture escrow journal identity is corrupt");
  }
  return candidate as unknown as EntryIdentity;
}

function parseFixtureEscrowJournal(
  value: string,
  ownerController: ControllerIdentity,
): FixtureEscrowJournal {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    throw new Error("fixture escrow journal is corrupt", { cause: error });
  }
  if (typeof parsed !== "object" || parsed === null) {
    throw new Error("fixture escrow journal is corrupt");
  }
  const candidate = parsed as Record<string, unknown>;
  if (candidate.protocol !== fixtureEscrowProtocol) {
    throw new Error("fixture escrow journal has bad magic or protocol");
  }
  const expectedKeys = [
    "logicalSocketName",
    "protocol",
    "record",
    "recordDigest",
    "recordPath",
    "recordSnapshot",
    "reservation",
    "reservationPath",
    "runId",
    ...(candidate.socket === undefined ? [] : ["socket"]),
    "socketPath",
  ].sort();
  if (
    JSON.stringify(Object.keys(candidate).sort()) !== JSON.stringify(expectedKeys) ||
    typeof candidate.logicalSocketName !== "string" ||
    !logicalSocketPattern.test(candidate.logicalSocketName) ||
    typeof candidate.runId !== "string" ||
    !runIdPattern.test(candidate.runId) ||
    typeof candidate.recordDigest !== "string" ||
    !/^[0-9a-f]{64}$/u.test(candidate.recordDigest) ||
    typeof candidate.recordPath !== "string" ||
    !isAbsolute(candidate.recordPath) ||
    typeof candidate.reservationPath !== "string" ||
    !isAbsolute(candidate.reservationPath) ||
    typeof candidate.socketPath !== "string" ||
    !isAbsolute(candidate.socketPath)
  ) {
    throw new Error("fixture escrow journal is corrupt");
  }
  const recordSnapshot = parseFixtureRecord(`${JSON.stringify(candidate.recordSnapshot)}\n`);
  assertControllerMatchesOwner(recordSnapshot, ownerController);
  const socket =
    candidate.socket === undefined ? undefined : parseJournalIdentity(candidate.socket, "socket");
  if (recordSnapshot.phase === "launching") {
    throw new Error("a launching fixture record cannot authorize journal recovery");
  }
  if (
    recordSnapshot.runId !== candidate.runId ||
    recordSnapshot.logicalSocketName !== candidate.logicalSocketName ||
    recordSnapshot.socketPath !== candidate.socketPath ||
    (recordSnapshot.phase === "reserved" && socket !== undefined) ||
    (recordSnapshot.phase === "running" &&
      socket !== undefined &&
      !sameEntry(recordSnapshot.socketIdentity, socket))
  ) {
    throw new Error("fixture escrow journal authority is corrupt");
  }
  return {
    logicalSocketName: candidate.logicalSocketName,
    protocol: fixtureEscrowProtocol,
    record: parseJournalIdentity(candidate.record, "file"),
    recordDigest: candidate.recordDigest,
    recordPath: candidate.recordPath,
    recordSnapshot,
    reservation: parseJournalIdentity(candidate.reservation, "directory"),
    reservationPath: candidate.reservationPath,
    runId: candidate.runId,
    ...(socket === undefined ? {} : { socket }),
    socketPath: candidate.socketPath,
  };
}

function recordDigest(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function assertReservationCapability(capability: ReservationCapability): void {
  if (!reservationCapabilities.has(capability)) {
    throw new Error("fixture cleanup requires an authenticated reservation capability");
  }
}

async function serializeReservationMutation<T>(
  capability: ReservationCapability,
  operation: () => Promise<T>,
): Promise<T> {
  assertReservationCapability(capability);
  const key = capability.reservationPath;
  const previous = reservationMutationTails.get(key) ?? Promise.resolve();
  let release = (): void => undefined;
  const turn = new Promise<void>((resolveTurn) => {
    release = resolveTurn;
  });
  const tail = previous.catch(() => undefined).then(() => turn);
  reservationMutationTails.set(key, tail);
  await previous.catch(() => undefined);
  try {
    return await operation();
  } finally {
    release();
    if (reservationMutationTails.get(key) === tail) reservationMutationTails.delete(key);
  }
}

async function preflightReservation(capability: ReservationCapability): Promise<{
  record: FixtureRecord;
  recordIdentity: EntryIdentity;
  reservationIdentity: EntryIdentity;
  socketIdentity?: EntryIdentity;
  socketPresent: boolean;
}> {
  assertReservationCapability(capability);
  await assertSafeAbsoluteRoot(capability.runRoot);
  await assertOwnedDirectory(capability.runRoot, "test run root");
  await assertOwnedDirectory(capability.reservationPath, "fixture reservation");
  if (
    dirname(capability.reservationPath) !== capability.runRoot ||
    capability.recordPath !== join(capability.reservationPath, FIXTURE_RECORD_NAME)
  ) {
    throw new Error("fixture reservation is not a direct child of its exact run root");
  }
  const owner = await readOwner(capability.runRoot);
  const record = await readFixtureRecord(capability.reservationPath);
  const exactSocketPath = join(capability.reservationPath, "s");
  if (
    owner.runId !== capability.runId ||
    record.runId !== capability.runId ||
    !sameControllerIdentity(owner.controller, record.controller) ||
    record.socketPath !== exactSocketPath ||
    record.logicalSocketName !== basename(capability.reservationPath)
  ) {
    throw new Error("fixture record does not match its exact run-root capability");
  }
  let entries = await readdir(capability.reservationPath, { withFileTypes: true });
  const temporary = entries.find(({ name }) => name === fixtureRecordTemporaryName);
  if (temporary !== undefined) {
    if (temporary.isSymbolicLink() || !temporary.isFile()) {
      throw new Error("fixture identity record temporary must be a regular file");
    }
    const temporaryPath = join(capability.reservationPath, fixtureRecordTemporaryName);
    await readOwnedRecord(temporaryPath, "fixture identity record temporary");
    await unlink(temporaryPath);
    entries = await readdir(capability.reservationPath, { withFileTypes: true });
  }
  for (const entry of entries) {
    if (entry.name !== FIXTURE_RECORD_NAME && entry.name !== "s") {
      throw new Error(`reservation contains unexpected entries: ${entry.name}`);
    }
    if (entry.isSymbolicLink())
      throw new Error(`reservation entry must not be a symlink: ${entry.name}`);
    if (entry.name === FIXTURE_RECORD_NAME && !entry.isFile()) {
      throw new Error("fixture identity record must be a regular file");
    }
  }
  const socketPresent = await socketExists(exactSocketPath);
  if (entries.some((entry) => entry.name === "s") && !socketPresent) {
    throw new Error("fixture socket entry is not a Unix socket");
  }
  return {
    record,
    recordIdentity: entryIdentity(await lstat(capability.recordPath)),
    reservationIdentity: entryIdentity(await lstat(capability.reservationPath)),
    ...(socketPresent ? { socketIdentity: entryIdentity(await lstat(exactSocketPath)) } : {}),
    socketPresent,
  };
}

type SocketEvidenceState = "absent" | "authenticated" | "foreign" | "unauthenticated";

function classifySocketEvidence(
  preflight: Awaited<ReturnType<typeof preflightReservation>>,
  authority: SocketIdentity | undefined,
): SocketEvidenceState {
  if (!preflight.socketPresent) return "absent";
  if (authority === undefined) return "unauthenticated";
  if (preflight.socketIdentity === undefined || !sameEntry(preflight.socketIdentity, authority)) {
    return "foreign";
  }
  return "authenticated";
}

function foreignSocketLeak(state: SocketEvidenceState): string {
  return state === "unauthenticated"
    ? "fixture socket is present without authenticated unlink authority"
    : "foreign socket evidence occupies the fixture socket path";
}

async function removeReservationFiles(
  capability: ReservationCapability,
  expected: Awaited<ReturnType<typeof preflightReservation>>,
  authorizedSocketIdentity: SocketIdentity | undefined,
): Promise<void> {
  const { recordPath, reservationPath, runRoot } = capability;
  const socketPath = join(reservationPath, "s");
  const current = await preflightReservation(capability);
  if (
    !sameEntry(current.reservationIdentity, expected.reservationIdentity) ||
    !sameEntry(current.recordIdentity, expected.recordIdentity) ||
    current.socketPresent !== expected.socketPresent ||
    (current.socketIdentity !== undefined &&
      expected.socketIdentity !== undefined &&
      !sameEntry(current.socketIdentity, expected.socketIdentity))
  ) {
    throw new Error("fixture cleanup evidence changed after preflight");
  }
  const socketState = classifySocketEvidence(current, authorizedSocketIdentity);
  if (socketState === "foreign" || socketState === "unauthenticated") {
    throw new ForeignSocketEvidenceError(foreignSocketLeak(socketState));
  }
  if (current.record.phase === "launching") {
    throw new Error("a launching fixture cannot authorize a cleanup journal");
  }

  const escrow = fixtureEscrowPath(runRoot, current.record.logicalSocketName, current.record.runId);
  await mkdir(escrow, { mode: 0o700 });
  await chmod(escrow, 0o700);
  const journalPath = join(escrow, "journal.json");
  const movedReservation = join(escrow, "reservation");
  let committed = false;
  try {
    const recordText = await readOwnedRecord(recordPath, "fixture identity record");
    await writeAtomicDurableJson(journalPath, {
      logicalSocketName: current.record.logicalSocketName,
      protocol: fixtureEscrowProtocol,
      record: current.recordIdentity,
      recordDigest: recordDigest(recordText),
      recordPath,
      recordSnapshot: current.record,
      reservation: current.reservationIdentity,
      reservationPath,
      runId: current.record.runId,
      ...(current.socketIdentity === undefined ? {} : { socket: current.socketIdentity }),
      socketPath,
    } satisfies FixtureEscrowJournal);
    await rename(reservationPath, movedReservation);
    committed = true;
    if (!sameEntry(entryIdentity(await lstat(movedReservation)), current.reservationIdentity)) {
      throw new Error("fixture reservation changed while being escrowed");
    }
    const movedEntries = await readdir(movedReservation);
    const expectedEntries = [
      FIXTURE_RECORD_NAME,
      ...(current.socketIdentity === undefined ? [] : ["s"]),
    ].sort();
    if (JSON.stringify(movedEntries.sort()) !== JSON.stringify(expectedEntries)) {
      throw new Error(`reservation contains unexpected entries: ${movedEntries.join(", ")}`);
    }
    const movedRecord = join(movedReservation, FIXTURE_RECORD_NAME);
    const movedRecordText = await readOwnedRecord(movedRecord, "escrowed fixture record");
    if (
      !sameEntry(entryIdentity(await lstat(movedRecord)), current.recordIdentity) ||
      recordDigest(movedRecordText) !== recordDigest(recordText)
    ) {
      throw new Error("fixture record changed while its reservation was escrowed");
    }
    if (current.socketIdentity !== undefined) {
      const movedSocket = join(movedReservation, "s");
      if (!sameEntry(entryIdentity(await lstat(movedSocket)), current.socketIdentity)) {
        throw new Error("fixture socket changed while its reservation was escrowed");
      }
      await unlink(movedSocket);
    }
    await unlink(movedRecord);
    await rmdir(movedReservation);
    parseFixtureEscrowJournal(
      await readOwnedRecord(journalPath, "fixture escrow journal"),
      current.record.controller,
    );
    await unlink(journalPath);
    await rmdir(escrow);
  } catch (error) {
    if (!committed) {
      await unlink(join(escrow, ".journal.tmp")).catch(() => undefined);
      await unlink(journalPath).catch(() => undefined);
      await rmdir(escrow).catch(() => undefined);
    }
    throw error;
  }
}

function generationCondition(
  record: Extract<FixtureRecord, { readonly phase: "launching" | "running" }>,
): string {
  return `#{==:#{${record.generation.name}},${record.generation.value}}`;
}

function pidGenerationCondition(
  record: Extract<FixtureRecord, { readonly phase: "launching" | "running" }>,
  pid: number,
): string {
  return `#{&&:#{==:#{pid},${String(pid)}},${generationCondition(record)}}`;
}

async function discoverLaunchingDaemon(
  capability: ReservationCapability,
  current: Awaited<ReturnType<typeof preflightReservation>>,
): Promise<Awaited<ReturnType<typeof preflightReservation>>> {
  if (current.record.phase !== "launching" || !current.socketPresent) {
    throw new Error("fixture daemon identity is missing after launch");
  }
  await assertControllerCurrent(current.record.controller);
  const before = current.socketIdentity;
  if (before === undefined) throw new Error("fixture socket is missing during discovery");
  const success = `generation-discovery-${randomUUID()}`;
  const mismatch = `generation-mismatch-${randomUUID()}`;
  const environment = controllerEnvironment(capability, current.record.generation.name);
  await assertControllerCurrent(current.record.controller);
  const result = await new NodeSpawnTransport({ terminationGraceMs: 100 }).execute({
    args: [
      "-N",
      "-S",
      current.record.socketPath,
      "if-shell",
      "-F",
      generationCondition(current.record),
      `display-message -p '${success}\t#{pid}\t#{${current.record.generation.name}}'`,
      `display-message -p '${mismatch}'`,
    ],
    environment,
    executable: current.record.controller.executablePath,
    timeoutMs: 1_000,
  });
  const output = new TextDecoder("utf-8", { fatal: true }).decode(result.stdout);
  if (result.returncode !== 0) throw new Error("fixture generation discovery failed");
  if (output === `${mismatch}\n`)
    throw new ForeignSocketEvidenceError("fixture generation mismatch");
  const fields = output.endsWith("\n") ? output.slice(0, -1).split("\t") : [];
  const pid =
    fields.length === 3 && /^[1-9]\d*$/u.test(fields[1] ?? "") ? Number(fields[1]) : Number.NaN;
  if (
    fields[0] !== success ||
    fields[2] !== current.record.generation.value ||
    !Number.isSafeInteger(pid) ||
    pid < 1
  ) {
    throw new Error("fixture generation discovery returned an invalid frame");
  }
  const after = socketIdentityFromMetadata(await lstat(current.record.socketPath));
  if (!sameEntry(before, after))
    throw new ForeignSocketEvidenceError("fixture socket changed during discovery");
  const authority = await validateGenerationAuthority(capability, current.record, pid);
  const running: Extract<FixtureRecord, { readonly phase: "running" }> = {
    ...current.record,
    daemon: authority.daemon,
    phase: "running",
    socketIdentity: authority.socketIdentity,
  };
  await writeAtomicJson(capability.recordPath, running);
  return preflightReservation(capability);
}

async function awaitDaemonExit(daemon: DaemonIdentity, deadlineMs = 750): Promise<boolean> {
  const deadline = performance.now() + deadlineMs;
  while (performance.now() < deadline) {
    // eslint-disable-next-line no-await-in-loop -- each observation is bounded by one monotonic deadline.
    const current = await readDaemonIdentity(daemon.pid);
    if (current === undefined || current.startIdentity !== daemon.startIdentity) return true;
    // eslint-disable-next-line no-await-in-loop -- yielding permits the daemon's exit notification to run.
    await new Promise((resolve) => setImmediate(resolve));
  }
  const current = await readDaemonIdentity(daemon.pid);
  return current === undefined || current.startIdentity !== daemon.startIdentity;
}

async function connectedGenerationKill(
  capability: ReservationCapability,
  record: Extract<FixtureRecord, { readonly phase: "running" }>,
): Promise<"killed" | "foreign" | "unavailable"> {
  try {
    await validateGenerationAuthority(capability, record, record.daemon.pid);
  } catch (error) {
    if (error instanceof ForeignSocketEvidenceError) return "foreign";
    throw error;
  }
  const mismatch = `kill-generation-mismatch-${randomUUID()}`;
  const environment = controllerEnvironment(capability, record.generation.name);
  await assertControllerCurrent(record.controller);
  const result = await new NodeSpawnTransport({ terminationGraceMs: 100 })
    .execute({
      args: [
        "-N",
        "-S",
        record.socketPath,
        "if-shell",
        "-F",
        pidGenerationCondition(record, record.daemon.pid),
        "kill-server",
        `display-message -p '${mismatch}'`,
      ],
      environment,
      executable: record.controller.executablePath,
      timeoutMs: 1_000,
    })
    .catch(() => undefined);
  if (result === undefined || result.returncode !== 0) return "unavailable";
  const output = new TextDecoder("utf-8", { fatal: true }).decode(result.stdout);
  if (output === `${mismatch}\n`) return "foreign";
  if (output !== "") throw new Error("guarded fixture cleanup returned an invalid frame");
  return "killed";
}

async function reapReservation(capability: ReservationCapability): Promise<ReapReport> {
  const leak = (message: unknown): ReapReport => ({
    leaks: [String(message)],
    reservationsFound: 1,
    rootRemoved: false,
  });
  let preflight: Awaited<ReturnType<typeof preflightReservation>>;
  try {
    preflight = await preflightReservation(capability);
  } catch (error) {
    if (isErrno(error, "ENOENT")) return { leaks: [], reservationsFound: 0, rootRemoved: false };
    return leak(error);
  }

  try {
    if (preflight.record.phase === "reserved") {
      if (preflight.socketPresent) return leak(foreignSocketLeak("unauthenticated"));
      await removeReservationFiles(capability, preflight, undefined);
      return { leaks: [], reservationsFound: 1, rootRemoved: false };
    }
    if (preflight.record.phase === "launching") {
      if (!preflight.socketPresent) return leak("fixture daemon identity is missing after launch");
      preflight = await discoverLaunchingDaemon(capability, preflight);
    }
    if (preflight.record.phase !== "running")
      return leak("fixture promotion did not publish running authority");
    const record = preflight.record;
    const initialSocketState = classifySocketEvidence(preflight, record.socketIdentity);
    await assertControllerCurrent(record.controller);
    const observed = await readDaemonIdentity(record.daemon.pid);
    if (observed === undefined) {
      const processAtPid = await readProcessIdentity(record.daemon.pid);
      if (processAtPid?.startIdentity === record.daemon.startIdentity) {
        return leak(`daemon executable identity mismatch for PID ${String(record.daemon.pid)}`);
      }
    } else {
      await assertExactProcessLaunch(record, record.daemon);
      if (initialSocketState === "authenticated") {
        const outcome = await connectedGenerationKill(capability, record);
        if (outcome === "foreign") {
          const failure = await reapViaPidfd(capability, record, record.daemon);
          return leak(failure ?? "fixture socket server generation mismatch");
        }
        if (outcome === "unavailable" || !(await awaitDaemonExit(record.daemon))) {
          const failure = await reapViaPidfd(capability, record, record.daemon);
          if (failure !== undefined) return leak(failure);
        }
      } else {
        const failure = await reapViaPidfd(capability, record, record.daemon);
        if (failure !== undefined) return leak(failure);
      }
    }
    if (!(await awaitDaemonExit(record.daemon, 50))) {
      return leak(`daemon ${String(record.daemon.pid)} remained live after cleanup`);
    }
    const finalPreflight = await preflightReservation(capability);
    const finalSocketState = classifySocketEvidence(finalPreflight, record.socketIdentity);
    if (
      initialSocketState === "foreign" ||
      initialSocketState === "unauthenticated" ||
      finalSocketState === "foreign" ||
      finalSocketState === "unauthenticated"
    ) {
      return leak(
        foreignSocketLeak(finalSocketState === "absent" ? initialSocketState : finalSocketState),
      );
    }
    await removeReservationFiles(capability, finalPreflight, record.socketIdentity);
    return { leaks: [], reservationsFound: 1, rootRemoved: false };
  } catch (error) {
    return leak(error);
  }
}

export async function reapFixture(capability: ReservationCapability): Promise<ReapReport> {
  return serializeReservationMutation(capability, () => reapReservation(capability));
}

function ownerEscrowPath(runRoot: string): string {
  return `${runRoot}.owner-escrow`;
}

function fixtureEscrowPath(runRoot: string, logicalSocketName: string, runId: string): string {
  return join(runRoot, `${fixtureEscrowPrefix}${logicalSocketName}.${runId}`);
}

function logicalSocketFromEscrow(name: string, runId: string): string | undefined {
  const suffix = `.${runId}`;
  if (!name.startsWith(fixtureEscrowPrefix) || !name.endsWith(suffix)) return undefined;
  const logicalSocketName = name.slice(fixtureEscrowPrefix.length, -suffix.length);
  return logicalSocketPattern.test(logicalSocketName) ? logicalSocketName : undefined;
}

async function restoreEscrowedOwner(runRoot: string): Promise<void> {
  const ownerPath = join(runRoot, OWNER_RECORD_NAME);
  try {
    await lstat(ownerPath);
    return;
  } catch (error) {
    if (!isErrno(error, "ENOENT")) throw error;
  }
  const escrow = ownerEscrowPath(runRoot);
  try {
    await assertOwnedDirectory(escrow, "owner escrow");
  } catch (error) {
    if (isErrno(error, "ENOENT")) return;
    throw error;
  }
  const entries = await readdir(escrow);
  if (entries.length !== 1 || entries[0] !== OWNER_RECORD_NAME) {
    throw new Error(`owner escrow contains unexpected entries: ${entries.join(", ")}`);
  }
  const escrowOwner = join(escrow, OWNER_RECORD_NAME);
  parseOwnerRecord(await readOwnedRecord(escrowOwner, "escrowed owner record"));
  const escrowIdentity = entryIdentity(await lstat(escrowOwner));
  await link(escrowOwner, ownerPath);
  if (!sameEntry(entryIdentity(await lstat(ownerPath)), escrowIdentity)) {
    throw new Error("restored owner record does not match its escrow hardlink");
  }
}

async function reapDetachedOwnerEscrow(
  runRoot: string,
  authority: "owned" | "stale",
): Promise<ReapReport | undefined> {
  const escrow = ownerEscrowPath(runRoot);
  try {
    await assertOwnedDirectory(escrow, "owner escrow");
  } catch (error) {
    if (isErrno(error, "ENOENT")) return undefined;
    throw error;
  }
  const entries = await readdir(escrow);
  if (entries.length === 0) {
    await rmdir(escrow);
    return { leaks: [], reservationsFound: 0, rootRemoved: true };
  }
  if (entries.length !== 1 || entries[0] !== OWNER_RECORD_NAME) {
    throw new Error(`owner escrow contains unexpected entries: ${entries.join(", ")}`);
  }
  const escrowOwner = join(escrow, OWNER_RECORD_NAME);
  const owner = parseOwnerRecord(await readOwnedRecord(escrowOwner, "escrowed owner record"));
  const observed = await readProcessIdentity(owner.owner.pid);
  const ownerIsLive = observed?.startIdentity === owner.owner.startIdentity;
  if (authority === "stale" && ownerIsLive) {
    throw new Error(`test run root has a live owner: ${String(owner.owner.pid)}`);
  }
  if (authority === "owned") {
    const current = await readProcessIdentity(process.pid);
    if (
      current === undefined ||
      owner.owner.pid !== current.pid ||
      owner.owner.startIdentity !== current.startIdentity
    ) {
      throw new Error("test run root is not owned by this supervisor");
    }
  }
  await unlink(escrowOwner);
  await rmdir(escrow);
  return { leaks: [], reservationsFound: 0, rootRemoved: true };
}

async function recoverOwnedOwnerEscrow(
  runRoot: string,
  ownerIdentity: EntryIdentity,
): Promise<void> {
  const escrow = ownerEscrowPath(runRoot);
  try {
    await assertOwnedDirectory(escrow, "owner escrow");
  } catch (error) {
    if (isErrno(error, "ENOENT")) return;
    throw error;
  }
  const entries = await readdir(escrow);
  if (entries.length !== 0) {
    if (entries.length !== 1 || entries[0] !== OWNER_RECORD_NAME) {
      throw new Error(`owner escrow contains unexpected entries: ${entries.join(", ")}`);
    }
    const escrowOwner = join(escrow, OWNER_RECORD_NAME);
    parseOwnerRecord(await readOwnedRecord(escrowOwner, "escrowed owner record"));
    if (!sameEntry(entryIdentity(await lstat(escrowOwner)), ownerIdentity)) {
      throw new Error("canonical and escrow owner inodes conflict");
    }
    await unlink(escrowOwner);
  }
  await rmdir(escrow);
}

async function lstatIfPresent(path: string) {
  try {
    return await lstat(path);
  } catch (error) {
    if (isErrno(error, "ENOENT")) return undefined;
    throw error;
  }
}

async function verifyJournaledRecord(
  path: string,
  journal: FixtureEscrowJournal,
  ownerController: ControllerIdentity,
): Promise<void> {
  const text = await readOwnedRecord(path, "journaled fixture record");
  if (
    !sameEntry(entryIdentity(await lstat(path)), journal.record) ||
    recordDigest(text) !== journal.recordDigest
  ) {
    throw new Error("journaled fixture record identity or digest changed");
  }
  const record = parseFixtureRecord(text);
  assertControllerMatchesOwner(record, ownerController);
  if (
    JSON.stringify(record) !== JSON.stringify(journal.recordSnapshot) ||
    record.runId !== journal.runId ||
    record.logicalSocketName !== journal.logicalSocketName ||
    record.socketPath !== journal.socketPath
  ) {
    throw new Error("journaled fixture record does not match its reservation");
  }
  if (record.phase === "launching")
    throw new Error("a launching fixture record cannot authorize journal recovery");
  if (record.phase === "reserved" && journal.socket !== undefined) {
    throw new Error("journaled socket authority does not match its fixture record");
  }
  if (
    record.phase === "running" &&
    journal.socket !== undefined &&
    (record.socketIdentity === undefined || !sameEntry(record.socketIdentity, journal.socket))
  ) {
    throw new Error("journaled socket authority does not match its fixture record");
  }
}

async function authenticateCompleteReservation(
  reservationPath: string,
  owner: OwnerRecord,
  logicalSocketName: string,
): Promise<void> {
  await assertOwnedDirectory(reservationPath, "fixture reservation");
  const record = await readFixtureRecord(reservationPath);
  assertControllerMatchesOwner(record, owner.controller);
  if (
    record.runId !== owner.runId ||
    record.logicalSocketName !== logicalSocketName ||
    record.socketPath !== join(reservationPath, "s")
  ) {
    throw new Error("fixture reservation does not authenticate its escrow");
  }
  const entries = await readdir(reservationPath, { withFileTypes: true });
  if (
    entries.some(
      (entry) =>
        entry.isSymbolicLink() ||
        (entry.name !== FIXTURE_RECORD_NAME && entry.name !== "s") ||
        (entry.name === FIXTURE_RECORD_NAME && !entry.isFile()) ||
        (entry.name === "s" && !entry.isSocket()),
    ) ||
    !entries.some(({ name }) => name === FIXTURE_RECORD_NAME)
  ) {
    throw new Error(
      `fixture reservation contains unexpected entries: ${entries.map(({ name }) => name).join(", ")}`,
    );
  }
}

async function recoverFixtureEscrows(runRoot: string, owner: OwnerRecord): Promise<string[]> {
  const leaks: string[] = [];
  const entries = await readdir(runRoot, { withFileTypes: true });
  for (const entry of entries) {
    const logicalSocketName = logicalSocketFromEscrow(entry.name, owner.runId);
    if (logicalSocketName === undefined) continue;
    const escrow = join(runRoot, entry.name);
    try {
      if (entry.isSymbolicLink() || !entry.isDirectory()) {
        throw new Error(`fixture escrow must be a directory: ${entry.name}`);
      }
      // eslint-disable-next-line no-await-in-loop -- every escrow is authenticated and recovered before root enumeration.
      await assertOwnedDirectory(escrow, "fixture escrow");
      // eslint-disable-next-line no-await-in-loop -- exact journal contents determine the crash boundary.
      const escrowEntries = await readdir(escrow, { withFileTypes: true });
      if (escrowEntries.length === 0) {
        const reservationPath = join(runRoot, logicalSocketName);
        // eslint-disable-next-line no-await-in-loop -- an existing reservation authenticates a pre-journal crash.
        const reservation = await lstatIfPresent(reservationPath);
        if (reservation !== undefined) {
          // eslint-disable-next-line no-await-in-loop -- the pre-journal reservation is recovered serially.
          await authenticateCompleteReservation(reservationPath, owner, logicalSocketName);
        }
        // eslint-disable-next-line no-await-in-loop -- rmdir refuses content added after authentication.
        await rmdir(escrow);
        continue;
      }
      const journalEntry = escrowEntries.find(({ name }) => name === "journal.json");
      if (journalEntry === undefined) {
        const temporaryEntry = escrowEntries.find(({ name }) => name === ".journal.tmp");
        if (
          temporaryEntry === undefined ||
          escrowEntries.length !== 1 ||
          temporaryEntry.isSymbolicLink() ||
          !temporaryEntry.isFile()
        ) {
          throw new Error("fixture escrow journal is missing");
        }
        const reservationPath = join(runRoot, logicalSocketName);
        // eslint-disable-next-line no-await-in-loop -- the partial journal belongs to this one authenticated reservation.
        await authenticateCompleteReservation(reservationPath, owner, logicalSocketName);
        const temporary = join(escrow, ".journal.tmp");
        // eslint-disable-next-line no-await-in-loop -- temporary metadata is authenticated before exact removal.
        await readOwnedRecord(temporary, "fixture escrow journal temporary");
        // eslint-disable-next-line no-await-in-loop -- the exact recognized temporary is removed serially.
        await unlink(temporary);
        // eslint-disable-next-line no-await-in-loop -- rmdir refuses late journal entries.
        await rmdir(escrow);
        continue;
      }
      if (
        journalEntry.isSymbolicLink() ||
        !journalEntry.isFile() ||
        escrowEntries.some(({ name }) => name !== "journal.json" && name !== "reservation")
      ) {
        throw new Error(
          `fixture escrow contains unexpected entries: ${escrowEntries.map(({ name }) => name).join(", ")}`,
        );
      }
      const journalPath = join(escrow, "journal.json");
      // eslint-disable-next-line no-await-in-loop -- journal bytes and inode are rechecked before deletion.
      const journalText = await readOwnedRecord(journalPath, "fixture escrow journal");
      const journal = parseFixtureEscrowJournal(journalText, owner.controller);
      // eslint-disable-next-line no-await-in-loop -- journal inode identity is captured before recovery mutation.
      const journalIdentity = entryIdentity(await lstat(journalPath));
      const reservationPath = join(runRoot, logicalSocketName);
      const movedReservation = join(escrow, "reservation");
      if (
        journal.runId !== owner.runId ||
        journal.logicalSocketName !== logicalSocketName ||
        journal.reservationPath !== reservationPath ||
        journal.recordPath !== join(reservationPath, FIXTURE_RECORD_NAME) ||
        journal.socketPath !== join(reservationPath, "s")
      ) {
        throw new Error("fixture escrow journal does not match its exact reservation");
      }
      // eslint-disable-next-line no-await-in-loop -- both locations are compared before any recovery mutation.
      const [reservation, moved] = await Promise.all([
        lstatIfPresent(reservationPath),
        lstatIfPresent(movedReservation),
      ]);
      if (reservation !== undefined && moved !== undefined) {
        throw new Error("fixture escrow has both original and moved reservations");
      }
      if (reservation !== undefined) {
        if (!sameEntry(entryIdentity(reservation), journal.reservation)) {
          throw new Error("fixture reservation identity changed before escrow recovery");
        }
        // eslint-disable-next-line no-await-in-loop -- an uncommitted reservation must retain all journaled evidence.
        const reservationEntries = (await readdir(reservationPath)).sort();
        const expectedEntries = [
          FIXTURE_RECORD_NAME,
          ...(journal.socket === undefined ? [] : ["s"]),
        ].sort();
        if (JSON.stringify(reservationEntries) !== JSON.stringify(expectedEntries)) {
          throw new Error(
            `fixture reservation contains unexpected entries: ${reservationEntries.join(", ")}`,
          );
        }
        // eslint-disable-next-line no-await-in-loop -- the uncommitted record is authenticated serially.
        await verifyJournaledRecord(journal.recordPath, journal, owner.controller);
        if (
          journal.socket !== undefined &&
          // eslint-disable-next-line no-await-in-loop -- the uncommitted socket is authenticated serially.
          !sameEntry(entryIdentity(await lstat(journal.socketPath)), journal.socket)
        ) {
          throw new Error("journaled fixture socket identity changed");
        }
      } else if (moved !== undefined) {
        if (!sameEntry(entryIdentity(moved), journal.reservation)) {
          throw new Error("moved fixture reservation identity changed");
        }
        // eslint-disable-next-line no-await-in-loop -- the committed reservation is recovered serially.
        const movedEntries = (await readdir(movedReservation)).sort();
        if (
          movedEntries.some((name) => name !== FIXTURE_RECORD_NAME && name !== "s") ||
          (journal.socket === undefined && movedEntries.includes("s"))
        ) {
          throw new Error(
            `moved fixture reservation contains unexpected entries: ${movedEntries.join(", ")}`,
          );
        }
        if (movedEntries.length === 1 && movedEntries[0] === "s") {
          throw new Error("fixture escrow has an impossible committed socket-only state");
        }
        const movedRecord = join(movedReservation, FIXTURE_RECORD_NAME);
        if (movedEntries.includes(FIXTURE_RECORD_NAME)) {
          // eslint-disable-next-line no-await-in-loop -- record authority is required before any committed socket mutation.
          await verifyJournaledRecord(movedRecord, journal, owner.controller);
        }
        const movedSocket = join(movedReservation, "s");
        if (movedEntries.includes("s")) {
          if (
            journal.socket === undefined ||
            // eslint-disable-next-line no-await-in-loop -- the committed socket is checked immediately before deletion.
            !sameEntry(entryIdentity(await lstat(movedSocket)), journal.socket)
          ) {
            throw new Error("journaled moved socket identity changed");
          }
          // eslint-disable-next-line no-await-in-loop -- only the verified committed socket is removed.
          await unlink(movedSocket);
        }
        if (movedEntries.includes(FIXTURE_RECORD_NAME)) {
          // eslint-disable-next-line no-await-in-loop -- the committed record is rechecked immediately before deletion.
          await verifyJournaledRecord(movedRecord, journal, owner.controller);
          // eslint-disable-next-line no-await-in-loop -- only the verified committed record is removed.
          await unlink(movedRecord);
        }
        // eslint-disable-next-line no-await-in-loop -- rmdir refuses any late committed-reservation entry.
        await rmdir(movedReservation);
      }
      // eslint-disable-next-line no-await-in-loop -- journal bytes are rechecked after reservation recovery.
      const currentJournalText = await readOwnedRecord(journalPath, "fixture escrow journal");
      if (
        currentJournalText !== journalText ||
        // eslint-disable-next-line no-await-in-loop -- the journal inode is rechecked immediately before deletion.
        !sameEntry(entryIdentity(await lstat(journalPath)), journalIdentity)
      ) {
        throw new Error("fixture escrow journal changed during recovery");
      }
      // eslint-disable-next-line no-await-in-loop -- journal removal is the final serialized recovery mutation.
      await unlink(journalPath);
      // eslint-disable-next-line no-await-in-loop -- rmdir refuses any late escrow entry.
      await rmdir(escrow);
    } catch (error) {
      leaks.push(String(error));
    }
  }
  return leaks;
}

async function recoverUnpublishedReservations(runRoot: string): Promise<string[]> {
  const leaks: string[] = [];
  const entries = await readdir(runRoot, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isDirectory() || !generatedLogicalSocketPattern.test(entry.name)) continue;
    const reservationPath = join(runRoot, entry.name);
    try {
      // eslint-disable-next-line no-await-in-loop -- each unpublished reservation is an independent trust boundary.
      await assertOwnedDirectory(reservationPath, "unpublished fixture reservation");
      // eslint-disable-next-line no-await-in-loop -- only empty or one recognized temp entry proves launch never began.
      const reservationEntries = await readdir(reservationPath, { withFileTypes: true });
      if (reservationEntries.length === 0) {
        // eslint-disable-next-line no-await-in-loop -- rmdir refuses any late registration entry.
        await rmdir(reservationPath);
        continue;
      }
      const temporary = reservationEntries[0];
      if (
        reservationEntries.length !== 1 ||
        temporary === undefined ||
        temporary.name !== fixtureRecordTemporaryName ||
        temporary.isSymbolicLink() ||
        !temporary.isFile()
      ) {
        continue;
      }
      const temporaryPath = join(reservationPath, fixtureRecordTemporaryName);
      // eslint-disable-next-line no-await-in-loop -- metadata authentication precedes removal of the unpublished temp.
      await readOwnedRecord(temporaryPath, "unpublished fixture record temporary");
      // eslint-disable-next-line no-await-in-loop -- launch cannot precede the absent canonical registration record.
      await unlink(temporaryPath);
      // eslint-disable-next-line no-await-in-loop -- rmdir refuses any entry added after temp removal.
      await rmdir(reservationPath);
    } catch (error) {
      leaks.push(String(error));
    }
  }
  return leaks;
}

async function reapRunRootInternal(
  runRoot: string,
  authority: "owned" | "stale",
): Promise<ReapReport> {
  const reaperEnvironment = snapshotEnvironment(process.env);
  await assertSafeAbsoluteRoot(runRoot);
  try {
    await assertOwnedDirectory(runRoot, "test run root");
  } catch (error) {
    if (isErrno(error, "ENOENT")) {
      return (
        (await reapDetachedOwnerEscrow(runRoot, authority)) ?? {
          leaks: [],
          reservationsFound: 0,
          rootRemoved: true,
        }
      );
    }
    throw error;
  }
  await restoreEscrowedOwner(runRoot);
  const ownerPath = join(runRoot, OWNER_RECORD_NAME);
  const ownerText = await readOwnedRecord(ownerPath, "test run owner record");
  const owner = parseOwnerRecord(ownerText);
  const ownerIdentity = entryIdentity(await lstat(ownerPath));
  const rootIdentity = entryIdentity(await lstat(runRoot));
  const observedOwner = await readProcessIdentity(owner.owner.pid);
  const ownerIsLive = observedOwner?.startIdentity === owner.owner.startIdentity;
  if (authority === "stale" && ownerIsLive) {
    throw new Error(`test run root has a live owner: ${String(owner.owner.pid)}`);
  }
  if (authority === "owned") {
    const current = await readProcessIdentity(process.pid);
    if (
      current === undefined ||
      owner.owner.pid !== current.pid ||
      owner.owner.startIdentity !== current.startIdentity
    ) {
      throw new Error("test run root is not owned by this supervisor");
    }
  }

  await recoverOwnedOwnerEscrow(runRoot, ownerIdentity);

  const leaks = await recoverFixtureEscrows(runRoot, owner);
  leaks.push(...(await recoverUnpublishedReservations(runRoot)));
  let reservationsFound = 0;
  const entries = await readdir(runRoot, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.name === OWNER_RECORD_NAME) continue;
    if (entry.isSymbolicLink()) {
      leaks.push(`reservation symlink refused: ${entry.name}`);
      continue;
    }
    if (!entry.isDirectory()) {
      leaks.push(`unexpected run-root entry: ${entry.name}`);
      continue;
    }
  }
  if (leaks.length > 0) return { leaks, reservationsFound, rootRemoved: false };

  for (const entry of entries) {
    if (entry.name === OWNER_RECORD_NAME) continue;
    const entryPath = join(runRoot, entry.name);
    // eslint-disable-next-line no-await-in-loop -- each record is authenticated before any cleanup starts.
    const record = await readFixtureRecord(entryPath).catch((error: unknown) => {
      leaks.push(String(error));
      return undefined;
    });
    if (record === undefined) continue;
    const capability = {
      recordPath: join(entryPath, FIXTURE_RECORD_NAME),
      reservationPath: entryPath,
      runId: owner.runId,
      runRoot,
    } as ReservationCapability;
    reservationCapabilities.add(capability);
    reservationEnvironments.set(capability, reaperEnvironment);
    // eslint-disable-next-line no-await-in-loop -- exact-root cleanup stays serial to preserve deterministic diagnostics.
    const report = await serializeReservationMutation(capability, () =>
      reapReservation(capability),
    );
    reservationsFound += report.reservationsFound;
    leaks.push(...report.leaks);
  }

  if (leaks.length > 0) return { leaks, reservationsFound, rootRemoved: false };

  const finalEntries = await readdir(runRoot);
  if (finalEntries.length !== 1 || finalEntries[0] !== OWNER_RECORD_NAME) {
    return {
      leaks: [`run root contains late entries: ${finalEntries.join(", ")}`],
      reservationsFound,
      rootRemoved: false,
    };
  }
  if (
    !sameEntry(entryIdentity(await lstat(runRoot)), rootIdentity) ||
    !sameEntry(entryIdentity(await lstat(ownerPath)), ownerIdentity)
  ) {
    return {
      leaks: ["run root or owner record changed during cleanup"],
      reservationsFound,
      rootRemoved: false,
    };
  }
  const ownerEscrow = ownerEscrowPath(runRoot);
  const escrowOwner = join(ownerEscrow, OWNER_RECORD_NAME);
  await mkdir(ownerEscrow, { mode: 0o700 });
  await chmod(ownerEscrow, 0o700);
  await link(ownerPath, escrowOwner);
  if (!sameEntry(entryIdentity(await lstat(escrowOwner)), ownerIdentity)) {
    throw new Error("owner record changed while being hard-linked into escrow");
  }
  await unlink(ownerPath);
  try {
    await rmdir(runRoot);
  } catch (error) {
    await link(escrowOwner, ownerPath);
    if (!sameEntry(entryIdentity(await lstat(ownerPath)), ownerIdentity)) {
      throw new Error("restored owner record does not match its escrow hardlink", { cause: error });
    }
    await unlink(escrowOwner);
    await rmdir(ownerEscrow);
    return {
      leaks: [`run root finalization failed: ${String(error)}`],
      reservationsFound,
      rootRemoved: false,
    };
  }
  await unlink(escrowOwner);
  await rmdir(ownerEscrow);
  return { leaks, reservationsFound, rootRemoved: true };
}

export async function reapOwnedRunRoot(runRoot: string): Promise<ReapReport> {
  return reapRunRootInternal(runRoot, "owned");
}

export async function reapStaleRunRoot(runRoot: string): Promise<ReapReport> {
  return reapRunRootInternal(runRoot, "stale");
}

export async function runWithCleanup<T>(
  body: () => Promise<T>,
  cleanup: () => Promise<void>,
): Promise<T> {
  let result: T | undefined;
  let primary: unknown;
  let hasPrimary = false;
  try {
    result = await body();
  } catch (error) {
    hasPrimary = true;
    primary = error;
  }
  try {
    await cleanup();
  } catch (cleanupError) {
    if (!hasPrimary) throw cleanupError;
    reportSecondaryCleanupFailure(primary, cleanupError);
  }
  if (hasPrimary) throw primary;
  return result as T;
}

export function reportSecondaryCleanupFailure(primary: unknown, cleanupError: unknown): void {
  if (typeof primary === "object" && primary !== null) {
    try {
      const descriptor = Object.getOwnPropertyDescriptor(primary, "cleanupError");
      if (
        descriptor?.configurable === true ||
        (descriptor === undefined && Object.isExtensible(primary))
      ) {
        Object.defineProperty(primary, "cleanupError", {
          configurable: true,
          enumerable: false,
          value: cleanupError,
        });
        return;
      }
    } catch {
      // Cleanup reporting falls through to the diagnostics channel.
    }
  }
  channel("libtmux.test.cleanup-failure").publish({ cleanupError, primary });
}

export interface SupervisorOptions {
  readonly command: readonly [string, ...string[]];
  readonly graceMs?: number;
  readonly runRoot?: string;
}

function signalExitCode(signal: NodeJS.Signals): number {
  const number = osConstants.signals[signal];
  if (number === undefined) throw new Error(`unknown signal: ${signal}`);
  return 128 + number;
}

async function terminateSupervisor(signal: "SIGINT" | "SIGTERM"): Promise<never> {
  process.removeAllListeners("SIGINT");
  process.removeAllListeners("SIGTERM");
  const fallback = setTimeout(() => process.exit(signalExitCode(signal)), 250);
  fallback.ref();
  setImmediate(() => {
    process.kill(process.pid, signal);
  });
  return new Promise<never>(() => undefined);
}

export async function runSupervisor(options: SupervisorOptions): Promise<number> {
  const graceMs = options.graceMs ?? 500;
  if (!Number.isSafeInteger(graceMs) || graceMs < 1)
    throw new TypeError("graceMs must be positive");
  const runRoot = options.runRoot ?? (await mkdtemp(join(tmpdir(), "ltx-")));
  if (options.runRoot === undefined) {
    await chmod(runRoot, 0o700);
    const controller = await resolveControllerIdentity("tmux");
    await publishOwner(runRoot, controller);
  } else {
    await prepareRunRoot(runRoot);
  }

  const [executable, ...args] = options.command;
  const child = spawn(executable, args, {
    env: { ...process.env, [RUN_ROOT_ENV]: runRoot },
    shell: false,
    stdio: "inherit",
  });
  let requestedSignal: "SIGINT" | "SIGTERM" | undefined;
  let escalation: NodeJS.Timeout | undefined;
  let hardClose: NodeJS.Timeout | undefined;
  let forceClose: (() => void) | undefined;
  let closeDeadlineExceeded = false;
  const forward = (signal: "SIGINT" | "SIGTERM"): void => {
    if (requestedSignal !== undefined) return;
    requestedSignal = signal;
    child.kill(signal);
    escalation = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    }, graceMs);
    hardClose = setTimeout(() => {
      closeDeadlineExceeded = true;
      child.stdin?.destroy();
      child.stdout?.destroy();
      child.stderr?.destroy();
      child.unref();
      forceClose?.();
    }, graceMs + 750);
  };
  const onSigint = (): void => forward("SIGINT");
  const onSigterm = (): void => forward("SIGTERM");
  process.on("SIGINT", onSigint);
  process.on("SIGTERM", onSigterm);

  try {
    const closed = await new Promise<{ code: number | null; signal: NodeJS.Signals | null }>(
      (resolveChild, reject) => {
        let settled = false;
        const resolveOnce = (value: {
          code: number | null;
          signal: NodeJS.Signals | null;
        }): void => {
          if (settled) return;
          settled = true;
          resolveChild(value);
        };
        forceClose = () => resolveOnce({ code: null, signal: "SIGKILL" });
        child.once("error", reject);
        child.once("close", (code, signal) => resolveOnce({ code, signal }));
      },
    ).catch(async (error: unknown) => {
      try {
        const report = await reapOwnedRunRoot(runRoot);
        if (report.leaks.length > 0) {
          reportSecondaryCleanupFailure(error, new Error(report.leaks.join("; ")));
        }
      } catch (cleanupError) {
        reportSecondaryCleanupFailure(error, cleanupError);
      }
      throw error;
    });
    if (escalation !== undefined) clearTimeout(escalation);
    if (hardClose !== undefined) clearTimeout(hardClose);

    let cleanupFailed = false;
    try {
      const report = await reapOwnedRunRoot(runRoot);
      if (report.leaks.length > 0) throw new Error(report.leaks.join("; "));
    } catch (error) {
      cleanupFailed = true;
      process.stderr.write(`test cleanup failed: ${String(error)}\n`);
    }
    if (closeDeadlineExceeded) {
      cleanupFailed = true;
      process.stderr.write("test child close exceeded hard deadline after SIGKILL\n");
    }

    if (requestedSignal !== undefined) return terminateSupervisor(requestedSignal);

    const childStatus = closed.code ?? (closed.signal === null ? 1 : signalExitCode(closed.signal));
    return childStatus === 0 && cleanupFailed ? 1 : childStatus;
  } finally {
    if (escalation !== undefined) clearTimeout(escalation);
    if (hardClose !== undefined) clearTimeout(hardClose);
    process.removeListener("SIGINT", onSigint);
    process.removeListener("SIGTERM", onSigterm);
  }
}
