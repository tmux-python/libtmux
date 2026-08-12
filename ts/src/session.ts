import type { NewWindowOptions, WindowTarget } from "./types.js";
import { SESSION_ALIASES, type SessionAliasMap } from "./_generated/field_aliases.js";
import type { AliasedFields, RowWithIdentities } from "./_internal/codec/schemas.js";
import { readTmuxEnvironment } from "./_internal/operations/env.js";
import { detachClient } from "./_internal/operations/shell.js";
import { panesOfSession, windowsOfSession } from "./_internal/operations/relations.js";
import { LibTmuxException } from "./exc.js";
import { setHook, showHooks, unsetHook } from "./_internal/operations/hooks.js";
import { killTarget, newWindow } from "./_internal/operations/mutations.js";
import { setOption, showOptions, unsetOption } from "./_internal/operations/options.js";
import { renameSession, selectWindowIn } from "./_internal/operations/session_nav.js";
import { runtimeForServer } from "./_internal/runtime/context.js";
import { refreshHandle } from "./_internal/operations/refresh.js";
import { originGraphForHandle } from "./_internal/runtime/live_handle.js";
import type { Pane } from "./pane.js";
import type { Selection } from "./selection.js";
import type { Window } from "./window.js";
import { installLiveHandlePrototype, liveHandlesEqual } from "./_internal/runtime/live_handle.js";
import type { Server } from "./server.js";

// eslint-disable-next-line typescript/no-unsafe-declaration-merging -- CompleteFormatRow declaration merging exposes the frozen scalar snapshot on the nominal handle.
export class Session {
  declare private readonly sessionBrand: undefined;
  declare readonly server: Server;

  private constructor() {
    throw new Error("Session cannot be constructed directly");
  }

  /**
   * Windows placed in this session, in listing order.
   *
   * Resolved from the graph this handle was materialized against, so it issues
   * no tmux command and reports the instant the handle came from.
   */
  get windows(): Selection<Window> {
    return windowsOfSession(originGraphForHandle(this), this.id);
  }

  /** Panes contained by this session's windows. */
  get panes(): Selection<Pane> {
    return panesOfSession(originGraphForHandle(this), this.id);
  }

  /** Every option this session currently sees, including inherited values. */
  showOptions(): Promise<ReadonlyMap<string, string>> {
    return showOptions(runtimeForServer(this.server), "session", this.id);
  }

  /** Set an option on this session. */
  setOption(name: string, value: string, options?: { readonly append?: boolean }): Promise<void> {
    return setOption(runtimeForServer(this.server), "session", this.id, name, value, options);
  }

  /** Remove an option from this session. */
  unsetOption(name: string): Promise<void> {
    return unsetOption(runtimeForServer(this.server), "session", this.id, name);
  }

  /** Every hook this session reports. */
  showHooks(): Promise<ReadonlyMap<string, string>> {
    return showHooks(runtimeForServer(this.server), "session", this.id);
  }

  /** Bind a tmux command to a hook on this session. */
  setHook(name: string, command: string): Promise<void> {
    return setHook(runtimeForServer(this.server), "session", this.id, name, command);
  }

  /** Remove a hook from this session. */
  unsetHook(name: string): Promise<void> {
    return unsetHook(runtimeForServer(this.server), "session", this.id, name);
  }

  /** Create a window in this session and resolve it as a handle. */
  newWindow(options?: NewWindowOptions): Promise<Window> {
    return newWindow(this.server, runtimeForServer(this.server), this.id, options);
  }

  /** Destroy this session. */
  kill(): Promise<void> {
    return killTarget(runtimeForServer(this.server), "kill-session", this.id);
  }

  /** Re-read this session at the current instant, in place. */
  refresh(): Promise<void> {
    return refreshHandle(this, runtimeForServer(this.server));
  }

  /** Rename this session. */
  rename(name: string): Promise<void> {
    return renameSession(runtimeForServer(this.server), this.id, name);
  }

  /** Select the last, next, or previous window, or one named by target. */
  selectWindow(target: WindowTarget): Promise<void> {
    return selectWindowIn(runtimeForServer(this.server), this.id, target);
  }

  /**
   * Resolve the session this process is running inside.
   *
   * The pane is authoritative: `$TMUX`'s exported session id goes stale when a
   * pane is moved, so the session is looked up through `$TMUX_PANE` instead.
   */
  static async fromEnv(
    environment: Readonly<Record<string, string | undefined>> = process.env,
  ): Promise<Session> {
    const { paneId, socketPath } = readTmuxEnvironment(environment);
    const { Server } = await import("./server.js");
    const server = new Server({ environment, socketPath });
    const snapshot = await server.snapshot();
    const pane = snapshot.panes.filter((candidate) => candidate.id === paneId).first();
    if (pane === undefined) {
      throw new LibTmuxException(`${paneId} is not present on ${socketPath}`);
    }
    const session = pane.session;
    if (session === undefined) {
      throw new LibTmuxException(`${paneId} has no session on ${socketPath}`);
    }
    return session;
  }

  /** Detach every client attached to this session. */
  detach(): Promise<void> {
    return detachClient(runtimeForServer(this.server), this.id);
  }

  equals(other: unknown): boolean {
    return liveHandlesEqual(this, other);
  }
}

type SessionRow = RowWithIdentities<"session_id">;

export interface Session extends AliasedFields<SessionRow, SessionAliasMap> {
  /** The raw tmux format row, addressed by tmux's own token names. */
  readonly format: SessionRow;
}

installLiveHandlePrototype(Session.prototype, SESSION_ALIASES);
