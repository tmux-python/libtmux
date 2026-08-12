import type { MoveWindowOptions, SplitOptions } from "./types.js";
import { WINDOW_ALIASES, type WindowAliasMap } from "./_generated/field_aliases.js";
import type { AliasedFields, RowWithIdentities } from "./_internal/codec/schemas.js";
import {
  linkedSessionsOfWindow,
  panesOfPlacement,
  sessionOf,
} from "./_internal/operations/relations.js";
import { killTarget, splitWindow } from "./_internal/operations/mutations.js";
import { setOption, showOptions, unsetOption } from "./_internal/operations/options.js";
import {
  linkWindow,
  moveWindow,
  renameWindow,
  selectLayout,
  selectTarget,
  swapWindows,
  unlinkWindow,
} from "./_internal/operations/topology.js";
import { runtimeForServer } from "./_internal/runtime/context.js";
import { refreshHandle } from "./_internal/operations/refresh.js";
import { originGraphForHandle } from "./_internal/runtime/live_handle.js";
import type { Pane } from "./pane.js";
import type { Selection } from "./selection.js";
import type { Session } from "./session.js";
import { installLiveHandlePrototype, liveHandlesEqual } from "./_internal/runtime/live_handle.js";
import type { Server } from "./server.js";

// eslint-disable-next-line typescript/no-unsafe-declaration-merging -- CompleteFormatRow declaration merging exposes the frozen scalar snapshot on the nominal handle.
export class Window {
  declare private readonly windowBrand: undefined;
  declare readonly server: Server;

  private constructor() {
    throw new Error("Window cannot be constructed directly");
  }

  /** Panes of this window placement; a linked window keeps each set apart. */
  get panes(): Selection<Pane> {
    return panesOfPlacement(originGraphForHandle(this), this);
  }

  /** The session this placement belongs to. */
  get session(): Session | undefined {
    return sessionOf(originGraphForHandle(this), this.sessionId);
  }

  /** Every session this window is linked into. */
  get linkedSessions(): Selection<Session> {
    return linkedSessionsOfWindow(originGraphForHandle(this), this.id);
  }

  /** Every option this window currently sees, including inherited values. */
  showOptions(): Promise<ReadonlyMap<string, string>> {
    return showOptions(runtimeForServer(this.server), "window", this.id);
  }

  /** Set an option on this window. */
  setOption(name: string, value: string, options?: { readonly append?: boolean }): Promise<void> {
    return setOption(runtimeForServer(this.server), "window", this.id, name, value, options);
  }

  /** Remove an option from this window. */
  unsetOption(name: string): Promise<void> {
    return unsetOption(runtimeForServer(this.server), "window", this.id, name);
  }

  /** Split this window and resolve the created pane. */
  split(options?: SplitOptions): Promise<Pane> {
    return splitWindow(this.server, runtimeForServer(this.server), this.id, options);
  }

  /** Destroy this window, unlinking it from every session it is in. */
  kill(): Promise<void> {
    return killTarget(runtimeForServer(this.server), "kill-window", this.id);
  }

  /** Rename this window. */
  rename(name: string): Promise<void> {
    return renameWindow(runtimeForServer(this.server), this.id, name);
  }

  /** Move this window to another session or index without selecting it. */
  move(options?: MoveWindowOptions): Promise<void> {
    return moveWindow(runtimeForServer(this.server), this.id, options);
  }

  /** Link this window into another session, giving it a second placement. */
  link(options: MoveWindowOptions): Promise<void> {
    return linkWindow(runtimeForServer(this.server), this.id, options);
  }

  /** Remove this placement, leaving the window's other placements intact. */
  unlink(): Promise<void> {
    return unlinkWindow(runtimeForServer(this.server), this.id);
  }

  /** Exchange positions with another window. */
  swapWith(other: Window): Promise<void> {
    return swapWindows(runtimeForServer(this.server), this.id, other.id);
  }

  /** Apply a named or custom layout. */
  selectLayout(layout: string): Promise<void> {
    return selectLayout(runtimeForServer(this.server), this.id, layout);
  }

  /** Make this window active in its session. */
  select(): Promise<void> {
    return selectTarget(runtimeForServer(this.server), "select-window", this.id);
  }

  /** Re-read this window placement at the current instant, in place. */
  refresh(): Promise<void> {
    return refreshHandle(this, runtimeForServer(this.server));
  }

  equals(other: unknown): boolean {
    return liveHandlesEqual(this, other);
  }
}

type WindowRow = RowWithIdentities<"session_id" | "window_id" | "window_index">;

export interface Window extends AliasedFields<WindowRow, WindowAliasMap> {
  /** The raw tmux format row, addressed by tmux's own token names. */
  readonly format: WindowRow;
}

installLiveHandlePrototype(Window.prototype, WINDOW_ALIASES);
