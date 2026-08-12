import type {
  ConnectionAlias,
  DaemonEpoch,
  LogicalRef,
  TmuxLogger,
  TmuxWarningSink,
} from "../../common.js";
import { LibTmuxException } from "../../exc.js";
import { Server } from "../../server.js";
import { decodeLogicalRef } from "../graph/refs.js";
import type { CommandTransport } from "../transport/types.js";
import { LazyCapabilityBinding } from "./capabilities.js";
import type { TmuxConnection } from "./connection.js";

interface RuntimeEpochState {
  daemonEpoch: DaemonEpoch;
}

const runtimeEpochStates = new WeakMap<RuntimeContext, RuntimeEpochState>();
const serverRuntimes = new WeakMap<object, RuntimeContext>();

const noopLogger: TmuxLogger = Object.freeze({
  debug: () => undefined,
  error: () => undefined,
  info: () => undefined,
  warn: () => undefined,
});
const noopWarnings: TmuxWarningSink = Object.freeze({
  warn: () => undefined,
});

export interface RuntimeContextOptions {
  readonly connection: TmuxConnection;
  readonly connectionAlias: ConnectionAlias;
  readonly daemonEpoch: DaemonEpoch;
  readonly logger?: TmuxLogger;
  readonly transport: CommandTransport;
  readonly warnings?: TmuxWarningSink;
}

export interface RuntimeContext {
  readonly capabilities: LazyCapabilityBinding;
  readonly connection: TmuxConnection;
  readonly connectionAlias: ConnectionAlias;
  readonly daemonEpoch: DaemonEpoch;
  readonly logger: TmuxLogger;
  readonly transport: CommandTransport;
  readonly warnings: TmuxWarningSink;
}

function epochStateFor(runtime: RuntimeContext): RuntimeEpochState {
  const state = runtimeEpochStates.get(runtime);
  if (state === undefined) throw new LibTmuxException("runtime context is not authentic");
  return state;
}

function assertLogicalRefRuntime(runtime: RuntimeContext, ref: LogicalRef): void {
  const daemonEpoch = epochStateFor(runtime).daemonEpoch;
  if (ref.connection !== runtime.connectionAlias) {
    throw new LibTmuxException("logical reference belongs to another runtime");
  }
  if (ref.epoch !== daemonEpoch) {
    throw new LibTmuxException("logical reference daemon epoch is stale");
  }
}

export function createRuntimeContext(options: RuntimeContextOptions): RuntimeContext {
  const state: RuntimeEpochState = { daemonEpoch: options.daemonEpoch };
  const capabilities = new LazyCapabilityBinding({
    connection: options.connection,
    connectionAlias: options.connectionAlias,
    getDaemonEpoch: (): DaemonEpoch => state.daemonEpoch,
    transport: options.transport,
  });
  const runtime: RuntimeContext = Object.freeze({
    capabilities,
    connection: options.connection,
    connectionAlias: options.connectionAlias,
    get daemonEpoch(): DaemonEpoch {
      return state.daemonEpoch;
    },
    logger: options.logger ?? noopLogger,
    transport: options.transport,
    warnings: options.warnings ?? noopWarnings,
  });
  runtimeEpochStates.set(runtime, state);
  return runtime;
}

export function registerServerRuntime(server: Server, runtime: RuntimeContext): void {
  epochStateFor(runtime);
  if (serverRuntimes.has(server)) {
    throw new LibTmuxException("Server already has a runtime context");
  }
  serverRuntimes.set(server, runtime);
}

export function runtimeForServerValue(value: unknown): RuntimeContext | undefined {
  if ((typeof value !== "object" && typeof value !== "function") || value === null) {
    return undefined;
  }
  return serverRuntimes.get(value);
}

export function createServerWithRuntime(runtime: RuntimeContext): Server {
  epochStateFor(runtime);
  const server = Object.create(Server.prototype) as Server;
  registerServerRuntime(server, runtime);
  return server;
}

export function invalidateRuntimeEpoch(runtime: RuntimeContext): DaemonEpoch {
  const state = epochStateFor(runtime);
  const daemonEpoch = state.daemonEpoch + 1;
  if (!Number.isSafeInteger(daemonEpoch)) {
    throw new LibTmuxException("daemon epoch cannot exceed the safe integer range");
  }
  state.daemonEpoch = daemonEpoch as DaemonEpoch;
  return state.daemonEpoch;
}

export function runtimeForServer(server: Server): RuntimeContext {
  const runtime = runtimeForServerValue(server);
  if (runtime === undefined) throw new LibTmuxException("Server has no runtime context");
  return runtime;
}

export async function bindLogicalRef(runtime: RuntimeContext, value: unknown): Promise<LogicalRef> {
  const ref = decodeLogicalRef(value);
  assertLogicalRefRuntime(runtime, ref);

  const capabilities = await runtime.capabilities.bind();

  assertLogicalRefRuntime(runtime, ref);
  if (
    capabilities.connectionAlias !== runtime.connectionAlias ||
    capabilities.daemonEpoch !== runtime.daemonEpoch
  ) {
    throw new LibTmuxException("capability binding belongs to another runtime epoch");
  }
  return ref;
}
