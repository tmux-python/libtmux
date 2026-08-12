import { randomUUID } from "node:crypto";

import type { Client } from "./client.js";
import type { ConnectionAlias, DaemonEpoch } from "./common.js";
import type { Pane } from "./pane.js";
import type { Selection } from "./selection.js";
import type { Session } from "./session.js";
import type { Window } from "./window.js";
import { setHook, showHooks, unsetHook } from "./_internal/operations/hooks.js";
import {
  killServer,
  newSession,
  type NewSessionOptions,
} from "./_internal/operations/mutations.js";
import { setOption, showOptions, unsetOption } from "./_internal/operations/options.js";
import {
  ifShell,
  runShell,
  type IfShellOptions,
  type RunShellOptions,
} from "./_internal/operations/shell.js";
import {
  deleteBuffer,
  hasSession,
  listBuffers,
  listCommands,
  setBuffer,
  showBuffer,
  sourceFile,
} from "./_internal/operations/server_utils.js";
import { buildServerSnapshot, type ServerSnapshot } from "./_internal/operations/snapshot.js";
import {
  createRuntimeContext,
  registerServerRuntime,
  runtimeForServer,
  runtimeForServerValue,
} from "./_internal/runtime/context.js";
import { TmuxConnection } from "./_internal/runtime/connection.js";
import { NodeSpawnTransport } from "./_internal/transport/node_spawn_transport.js";

export interface ServerOptions {
  readonly colors?: 88 | 256;
  readonly configFile?: string;
  readonly environment?: Readonly<Record<string, string | undefined>>;
  readonly socketName?: string;
  readonly socketPath?: string;
  readonly tmuxBin?: string;
}

export class Server {
  declare private readonly serverBrand: undefined;

  constructor(...[options]: [options?: ServerOptions]) {
    if (!(this instanceof Server)) {
      throw new TypeError("Server constructor requires a Server instance");
    }
    if (options?.socketName !== undefined && options.socketPath !== undefined) {
      throw new TypeError("socketName and socketPath are mutually exclusive");
    }

    const connection = new TmuxConnection({
      executable: options?.tmuxBin ?? "tmux",
      environment: options?.environment ?? process.env,
      ...(options?.colors === undefined ? {} : { colors: options.colors }),
      ...(options?.configFile === undefined ? {} : { configFile: options.configFile }),
      ...(options?.socketName === undefined ? {} : { socketName: options.socketName }),
      ...(options?.socketPath === undefined ? {} : { socketPath: options.socketPath }),
    });
    const runtime = createRuntimeContext({
      connection,
      connectionAlias: randomUUID() as ConnectionAlias,
      daemonEpoch: 0 as DaemonEpoch,
      transport: new NodeSpawnTransport(),
    });
    registerServerRuntime(this, runtime);
  }

  get colors(): 88 | 256 | undefined {
    return runtimeForServerValue(this)?.connection.colors;
  }

  get configFile(): string | undefined {
    return runtimeForServerValue(this)?.connection.configFile;
  }

  get socketName(): string | undefined {
    return runtimeForServerValue(this)?.connection.socketName;
  }

  get socketPath(): string | undefined {
    return runtimeForServerValue(this)?.connection.socketPath;
  }

  get tmuxBin(): string {
    return runtimeForServerValue(this)?.connection.executable ?? "tmux";
  }

  /**
   * Acquire an immutable view of the server at this instant.
   *
   * Acquisition is the only step that talks to tmux. Everything reachable from
   * the returned value resolves locally, so traversal and filtering issue no
   * commands and an earlier snapshot keeps reporting its own instant.
   */
  snapshot(): Promise<ServerSnapshot> {
    return buildServerSnapshot(this, runtimeForServer(this));
  }

  /**
   * Every session on the server, newest acquisition first.
   *
   * Each accessor acquires its own snapshot, mirroring Python's re-querying
   * properties. Callers needing several collections from one instant should
   * take a {@link snapshot} instead of calling these in sequence.
   */
  async sessions(): Promise<Selection<Session>> {
    return (await this.snapshot()).sessions;
  }

  /** Every window on the server, including each placement of a linked window. */
  async windows(): Promise<Selection<Window>> {
    return (await this.snapshot()).windows;
  }

  /** Every pane on the server. */
  async panes(): Promise<Selection<Pane>> {
    return (await this.snapshot()).panes;
  }

  /** Every client attached to the server. */
  async clients(): Promise<Selection<Client>> {
    return (await this.snapshot()).clients;
  }

  /** Every server-scope option tmux currently reports. */
  showOptions(): Promise<ReadonlyMap<string, string>> {
    return showOptions(runtimeForServer(this), "server");
  }

  /** Set a server-scope option. */
  setOption(name: string, value: string, options?: { readonly append?: boolean }): Promise<void> {
    return setOption(runtimeForServer(this), "server", null, name, value, options);
  }

  /** Remove a server-scope option. */
  unsetOption(name: string): Promise<void> {
    return unsetOption(runtimeForServer(this), "server", null, name);
  }

  /** Every global hook tmux currently reports. */
  showHooks(): Promise<ReadonlyMap<string, string>> {
    return showHooks(runtimeForServer(this), "server");
  }

  /** Bind a tmux command to a global hook. */
  setHook(name: string, command: string): Promise<void> {
    return setHook(runtimeForServer(this), "server", null, name, command);
  }

  /** Remove a global hook. */
  unsetHook(name: string): Promise<void> {
    return unsetHook(runtimeForServer(this), "server", null, name);
  }

  /** Create a detached session and resolve it as a handle. */
  newSession(options?: NewSessionOptions): Promise<Session> {
    return newSession(this, runtimeForServer(this), options);
  }

  /** Terminate the tmux server and every session on it. */
  kill(): Promise<void> {
    return killServer(runtimeForServer(this));
  }

  /** Whether a session with this name exists. */
  hasSession(name: string): Promise<boolean> {
    return hasSession(runtimeForServer(this), name);
  }

  /** Run a tmux config file against this server. */
  sourceFile(path: string): Promise<void> {
    return sourceFile(runtimeForServer(this), path);
  }

  /** Every command name the running tmux understands. */
  listCommands(): Promise<readonly string[]> {
    return listCommands(runtimeForServer(this));
  }

  /** Store a named paste buffer. */
  setBuffer(name: string, data: string): Promise<void> {
    return setBuffer(runtimeForServer(this), name, data);
  }

  /** Read a named paste buffer's contents. */
  showBuffer(name: string): Promise<readonly string[]> {
    return showBuffer(runtimeForServer(this), name);
  }

  /** Every buffer name this server holds. */
  listBuffers(): Promise<readonly string[]> {
    return listBuffers(runtimeForServer(this));
  }

  /** Discard a named paste buffer. */
  deleteBuffer(name: string): Promise<void> {
    return deleteBuffer(runtimeForServer(this), name);
  }

  /** Run a shell command through tmux and return whatever it printed. */
  runShell(command: string, options?: RunShellOptions): Promise<readonly string[]> {
    return runShell(runtimeForServer(this), command, options);
  }

  /** Run one command or another depending on a condition. */
  ifShell(condition: string, command: string, options?: IfShellOptions): Promise<void> {
    return ifShell(runtimeForServer(this), condition, command, options);
  }

  equals(other: unknown): boolean {
    const runtime = runtimeForServerValue(this);
    const otherRuntime = runtimeForServerValue(other);
    return (
      runtime !== undefined &&
      otherRuntime !== undefined &&
      runtime.connection.socketName === otherRuntime.connection.socketName &&
      runtime.connection.socketPath === otherRuntime.connection.socketPath
    );
  }
}
