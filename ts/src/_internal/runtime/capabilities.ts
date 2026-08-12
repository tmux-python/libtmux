import { createHash } from "node:crypto";

import type { ConnectionAlias, DaemonEpoch } from "../../common.js";
import { LibTmuxException } from "../../exc.js";
import { decodeBackslashReplace } from "../codec/backslash_replace.js";
import type { CommandRequest, CommandTransport, RawCommandResult } from "../transport/types.js";
import { snapshotCommandRequest } from "../transport/types.js";
import type { TmuxConnection } from "./connection.js";
import {
  parseTmuxVersion,
  tmuxVersionAtLeast,
  tmuxVersionIsExact,
  type TmuxVersion,
} from "./tmux_version.js";

export interface TmuxCapabilities {
  readonly connectionAlias: ConnectionAlias;
  readonly daemonEpoch: DaemonEpoch;
  readonly fingerprint: string;
  readonly formatFloor: Readonly<{
    pane37: boolean;
    paneDeadExit: boolean;
  }>;
  readonly quirks: Readonly<{
    breakPane37: boolean;
  }>;
  readonly rawVersion: string;
  readonly tmuxVersion: TmuxVersion;
}

export interface CapabilityBinding {
  bind(): Promise<TmuxCapabilities>;
}

export interface DeriveTmuxCapabilitiesOptions {
  readonly connectionAlias: ConnectionAlias;
  readonly daemonEpoch: DaemonEpoch;
  readonly rawVersion: string;
}

export interface LazyCapabilityBindingOptions {
  readonly connection: TmuxConnection;
  readonly connectionAlias: ConnectionAlias;
  readonly getDaemonEpoch: () => DaemonEpoch;
  readonly transport: CommandTransport;
}

function capabilityFingerprint(options: DeriveTmuxCapabilitiesOptions): string {
  return createHash("sha256")
    .update(JSON.stringify([options.connectionAlias, options.daemonEpoch, options.rawVersion]))
    .digest("hex");
}

export function deriveTmuxCapabilities(options: DeriveTmuxCapabilitiesOptions): TmuxCapabilities {
  const tmuxVersion = parseTmuxVersion(options.rawVersion);
  const formatFloor = Object.freeze({
    pane37: tmuxVersionAtLeast(tmuxVersion, parseTmuxVersion("3.7")),
    paneDeadExit: tmuxVersionAtLeast(tmuxVersion, parseTmuxVersion("3.3")),
  });
  const quirks = Object.freeze({
    breakPane37: tmuxVersionIsExact(tmuxVersion, parseTmuxVersion("3.7")),
  });
  return Object.freeze({
    connectionAlias: options.connectionAlias,
    daemonEpoch: options.daemonEpoch,
    fingerprint: capabilityFingerprint(options),
    formatFloor,
    quirks,
    rawVersion: options.rawVersion,
    tmuxVersion,
  });
}

export class LazyCapabilityBinding implements CapabilityBinding {
  readonly #connection: TmuxConnection;
  readonly #connectionAlias: ConnectionAlias;
  readonly #getDaemonEpoch: () => DaemonEpoch;
  readonly #transport: CommandTransport;
  #cached: TmuxCapabilities | undefined;
  #inFlight:
    | Readonly<{
        daemonEpoch: DaemonEpoch;
        promise: Promise<TmuxCapabilities>;
      }>
    | undefined;

  constructor(options: LazyCapabilityBindingOptions) {
    this.#connection = options.connection;
    this.#connectionAlias = options.connectionAlias;
    this.#getDaemonEpoch = options.getDaemonEpoch;
    this.#transport = options.transport;
  }

  async bind(): Promise<TmuxCapabilities> {
    const daemonEpoch = this.#getDaemonEpoch();
    if (this.#cached?.daemonEpoch === daemonEpoch) return this.#cached;
    if (this.#inFlight?.daemonEpoch === daemonEpoch) return this.#inFlight.promise;

    const promise = this.#probe(daemonEpoch);
    const inFlight = Object.freeze({ daemonEpoch, promise });
    this.#inFlight = inFlight;
    try {
      const capabilities = await promise;
      this.#cached = capabilities;
      return capabilities;
    } finally {
      if (this.#inFlight === inFlight) this.#inFlight = undefined;
    }
  }

  #request(): CommandRequest {
    const args = ["-N"];
    if (this.#connection.colors === 256) args.push("-2");
    if (this.#connection.colors === 88) args.push("-8");
    if (this.#connection.configFile !== undefined) args.push(`-f${this.#connection.configFile}`);
    if (this.#connection.socketName !== undefined) args.push(`-L${this.#connection.socketName}`);
    if (this.#connection.socketPath !== undefined) args.push(`-S${this.#connection.socketPath}`);
    args.push("display-message", "-p", "#{version}");
    return snapshotCommandRequest({
      args,
      environment: this.#connection.environment,
      executable: this.#connection.executable,
    });
  }

  async #probe(daemonEpoch: DaemonEpoch): Promise<TmuxCapabilities> {
    let result: RawCommandResult;
    try {
      result = await this.#transport.execute(this.#request());
    } catch (error) {
      const detail = error instanceof Error && error.message !== "" ? `: ${error.message}` : "";
      throw new LibTmuxException(`tmux version probe failed${detail}`, {
        cause: error,
        subcommand: "display-message",
      });
    }

    if (result.returncode !== 0) {
      const stderr = decodeBackslashReplace(result.stderr).trimEnd();
      throw new LibTmuxException(
        stderr === ""
          ? `tmux version probe failed with status ${result.returncode}`
          : `tmux version probe failed: ${stderr}`,
        { subcommand: "display-message" },
      );
    }

    const versions = decodeBackslashReplace(result.stdout).split("\n");
    while (versions.at(-1) === "") versions.pop();
    if (versions.length === 0) {
      throw new LibTmuxException("tmux version probe returned no version", {
        subcommand: "display-message",
      });
    }
    if (versions.length !== 1) {
      throw new LibTmuxException("tmux version probe returned multiple versions", {
        subcommand: "display-message",
      });
    }

    let capabilities: TmuxCapabilities;
    try {
      capabilities = deriveTmuxCapabilities({
        connectionAlias: this.#connectionAlias,
        daemonEpoch,
        rawVersion: versions[0]!,
      });
    } catch (error) {
      throw new LibTmuxException(error instanceof Error ? error.message : "invalid tmux version", {
        cause: error,
        subcommand: "display-message",
      });
    }
    if (this.#getDaemonEpoch() !== daemonEpoch) {
      throw new LibTmuxException("daemon epoch changed while binding capabilities", {
        subcommand: "display-message",
      });
    }
    return capabilities;
  }
}
