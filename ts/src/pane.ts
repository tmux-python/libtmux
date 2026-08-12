import type {
  CaptureOptions,
  ChooseTreeOptions,
  MenuItem,
  PopupOptions,
  ResizeOptions,
  RespawnOptions,
  SendKeysOptions,
  SplitOptions,
} from "./types.js";
import { PANE_ALIASES, type PaneAliasMap } from "./_generated/field_aliases.js";
import type { AliasedFields, RowWithIdentities } from "./_internal/codec/schemas.js";
import {
  chooseBuffer,
  chooseTree,
  customizeMode,
  displayMenu,
  displayPopup,
  findWindow,
  sendPrefix,
} from "./_internal/operations/interactive.js";
import { sessionOf, windowOfPlacement } from "./_internal/operations/relations.js";
import { killTarget, splitWindow } from "./_internal/operations/mutations.js";
import { capturePane, clearHistory, sendKeys } from "./_internal/operations/pane_io.js";
import { setOption, showOptions, unsetOption } from "./_internal/operations/options.js";
import {
  breakPane,
  displayMessage,
  joinPane,
  respawnPane,
  setCopyMode,
} from "./_internal/operations/shell.js";
import { resizePane, selectTarget, swapPanes } from "./_internal/operations/topology.js";
import { runtimeForServer } from "./_internal/runtime/context.js";
import { refreshHandle } from "./_internal/operations/refresh.js";
import { originGraphForHandle } from "./_internal/runtime/live_handle.js";
import type { Session } from "./session.js";
import type { Window } from "./window.js";
import { installLiveHandlePrototype, liveHandlesEqual } from "./_internal/runtime/live_handle.js";
import type { Server } from "./server.js";

// eslint-disable-next-line typescript/no-unsafe-declaration-merging -- CompleteFormatRow declaration merging exposes the frozen scalar snapshot on the nominal handle.
export class Pane {
  declare private readonly paneBrand: undefined;
  declare readonly server: Server;

  private constructor() {
    throw new Error("Pane cannot be constructed directly");
  }

  /** The window placement containing this pane. */
  get window(): Window | undefined {
    return windowOfPlacement(originGraphForHandle(this), this);
  }

  /** The session containing this pane. */
  get session(): Session | undefined {
    return sessionOf(originGraphForHandle(this), this.sessionId);
  }

  /** Every option this pane currently sees, including inherited values. */
  showOptions(): Promise<ReadonlyMap<string, string>> {
    return showOptions(runtimeForServer(this.server), "pane", this.id);
  }

  /** Set an option on this pane. */
  setOption(name: string, value: string, options?: { readonly append?: boolean }): Promise<void> {
    return setOption(runtimeForServer(this.server), "pane", this.id, name, value, options);
  }

  /** Remove an option from this pane. */
  unsetOption(name: string): Promise<void> {
    return unsetOption(runtimeForServer(this.server), "pane", this.id, name);
  }

  /** Split this pane and resolve the created pane. */
  split(options?: SplitOptions): Promise<Pane> {
    return splitWindow(this.server, runtimeForServer(this.server), this.id, options);
  }

  /** Destroy this pane. */
  kill(): Promise<void> {
    return killTarget(runtimeForServer(this.server), "kill-pane", this.id);
  }

  /** Send keys to this pane, following them with Enter unless told not to. */
  sendKeys(keys: string, options?: SendKeysOptions): Promise<void> {
    return sendKeys(runtimeForServer(this.server), this.id, keys, options);
  }

  /** Capture this pane's contents as lines. */
  capture(options?: CaptureOptions): Promise<readonly string[]> {
    return capturePane(runtimeForServer(this.server), this.id, options);
  }

  /** Discard this pane's scrollback history. */
  clearHistory(): Promise<void> {
    return clearHistory(runtimeForServer(this.server), this.id);
  }

  /** Resize this pane; tmux ignores a dimension its layout cannot honour. */
  resize(options: ResizeOptions): Promise<void> {
    return resizePane(runtimeForServer(this.server), this.id, options);
  }

  /** Exchange positions with another pane. */
  swapWith(other: Pane): Promise<void> {
    return swapPanes(runtimeForServer(this.server), this.id, other.id);
  }

  /** Make this pane active in its window. */
  select(): Promise<void> {
    return selectTarget(runtimeForServer(this.server), "select-pane", this.id);
  }

  /** Re-read this pane at the current instant, in place. */
  refresh(): Promise<void> {
    return refreshHandle(this, runtimeForServer(this.server));
  }

  /** Expand a tmux format string against this pane. */
  displayMessage(message: string): Promise<readonly string[]> {
    return displayMessage(runtimeForServer(this.server), message, this.id);
  }

  /** Restart this pane's command in place. */
  respawn(command?: string, options?: RespawnOptions): Promise<void> {
    return respawnPane(runtimeForServer(this.server), this.id, command, options);
  }

  /** Move this pane out into a window of its own. */
  breakOut(windowName?: string): Promise<void> {
    return breakPane(runtimeForServer(this.server), this.id, windowName);
  }

  /** Move this pane into another window as a split. */
  joinTo(target: string, options?: { readonly vertical?: boolean }): Promise<void> {
    return joinPane(runtimeForServer(this.server), this.id, target, options);
  }

  /** Enter this pane's copy mode. */
  enterCopyMode(): Promise<void> {
    return setCopyMode(runtimeForServer(this.server), this.id, true);
  }

  /** Leave this pane's copy mode. */
  exitCopyMode(): Promise<void> {
    return setCopyMode(runtimeForServer(this.server), this.id, false);
  }

  /** Open a popup over the client showing this pane. */
  displayPopup(command?: string, options?: PopupOptions): Promise<void> {
    return displayPopup(runtimeForServer(this.server), this.id, command, options);
  }

  /** Show a menu over the client showing this pane. */
  displayMenu(title: string, items: readonly MenuItem[]): Promise<void> {
    return displayMenu(runtimeForServer(this.server), this.id, title, items);
  }

  /** Open the interactive session and window chooser in this pane. */
  chooseTree(options?: ChooseTreeOptions): Promise<void> {
    return chooseTree(runtimeForServer(this.server), this.id, options);
  }

  /** Open the interactive buffer chooser in this pane. */
  chooseBuffer(): Promise<void> {
    return chooseBuffer(runtimeForServer(this.server), this.id);
  }

  /** Search windows interactively from this pane. */
  findWindow(pattern: string): Promise<void> {
    return findWindow(runtimeForServer(this.server), this.id, pattern);
  }

  /** Send the configured prefix key to this pane. */
  sendPrefix(): Promise<void> {
    return sendPrefix(runtimeForServer(this.server), this.id);
  }

  /** Open tmux's interactive option editor in this pane. */
  customizeMode(): Promise<void> {
    return customizeMode(runtimeForServer(this.server), this.id);
  }

  equals(other: unknown): boolean {
    return liveHandlesEqual(this, other);
  }
}

type PaneRow = RowWithIdentities<"pane_id" | "session_id" | "window_id" | "window_index">;

export interface Pane extends AliasedFields<PaneRow, PaneAliasMap> {
  /** The raw tmux format row, addressed by tmux's own token names. */
  readonly format: PaneRow;
}

installLiveHandlePrototype(Pane.prototype, PANE_ALIASES);
