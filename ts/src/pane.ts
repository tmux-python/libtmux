import type { CompleteFormatRow } from "./_internal/codec/schemas.js";
import {
  chooseBuffer,
  chooseTree,
  customizeMode,
  displayMenu,
  displayPopup,
  findWindow,
  sendPrefix,
  type ChooseTreeOptions,
  type MenuItem,
  type PopupOptions,
} from "./_internal/operations/interactive.js";
import { sessionOf, windowOfPlacement } from "./_internal/operations/relations.js";
import { killTarget, splitWindow, type SplitOptions } from "./_internal/operations/mutations.js";
import {
  capturePane,
  clearHistory,
  sendKeys,
  type CaptureOptions,
  type SendKeysOptions,
} from "./_internal/operations/pane_io.js";
import { setOption, showOptions, unsetOption } from "./_internal/operations/options.js";
import {
  breakPane,
  displayMessage,
  joinPane,
  respawnPane,
  setCopyMode,
  type RespawnOptions,
} from "./_internal/operations/shell.js";
import {
  resizePane,
  selectTarget,
  swapPanes,
  type ResizeOptions,
} from "./_internal/operations/topology.js";
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
  window(): Promise<Window | undefined> {
    return windowOfPlacement(this.server, originGraphForHandle(this), this);
  }

  /** The session containing this pane. */
  session(): Promise<Session | undefined> {
    return sessionOf(this.server, originGraphForHandle(this), this.session_id);
  }

  /** Every option this pane currently sees, including inherited values. */
  showOptions(): Promise<ReadonlyMap<string, string>> {
    return showOptions(runtimeForServer(this.server), "pane", this.pane_id);
  }

  /** Set an option on this pane. */
  setOption(name: string, value: string, options?: { readonly append?: boolean }): Promise<void> {
    return setOption(runtimeForServer(this.server), "pane", this.pane_id, name, value, options);
  }

  /** Remove an option from this pane. */
  unsetOption(name: string): Promise<void> {
    return unsetOption(runtimeForServer(this.server), "pane", this.pane_id, name);
  }

  /** Split this pane and resolve the created pane. */
  split(options?: SplitOptions): Promise<Pane> {
    return splitWindow(this.server, runtimeForServer(this.server), this.pane_id, options);
  }

  /** Destroy this pane. */
  kill(): Promise<void> {
    return killTarget(runtimeForServer(this.server), "kill-pane", this.pane_id);
  }

  /** Send keys to this pane, following them with Enter unless told not to. */
  sendKeys(keys: string, options?: SendKeysOptions): Promise<void> {
    return sendKeys(runtimeForServer(this.server), this.pane_id, keys, options);
  }

  /** Capture this pane's contents as lines. */
  capture(options?: CaptureOptions): Promise<readonly string[]> {
    return capturePane(runtimeForServer(this.server), this.pane_id, options);
  }

  /** Discard this pane's scrollback history. */
  clearHistory(): Promise<void> {
    return clearHistory(runtimeForServer(this.server), this.pane_id);
  }

  /** Resize this pane; tmux ignores a dimension its layout cannot honour. */
  resize(options: ResizeOptions): Promise<void> {
    return resizePane(runtimeForServer(this.server), this.pane_id, options);
  }

  /** Exchange positions with another pane. */
  swapWith(other: Pane): Promise<void> {
    return swapPanes(runtimeForServer(this.server), this.pane_id, other.pane_id);
  }

  /** Make this pane active in its window. */
  select(): Promise<void> {
    return selectTarget(runtimeForServer(this.server), "select-pane", this.pane_id);
  }

  /** Re-read this pane at the current instant, in place. */
  refresh(): Promise<void> {
    return refreshHandle(this, runtimeForServer(this.server));
  }

  /** Expand a tmux format string against this pane. */
  displayMessage(message: string): Promise<readonly string[]> {
    return displayMessage(runtimeForServer(this.server), message, this.pane_id);
  }

  /** Restart this pane's command in place. */
  respawn(command?: string, options?: RespawnOptions): Promise<void> {
    return respawnPane(runtimeForServer(this.server), this.pane_id, command, options);
  }

  /** Move this pane out into a window of its own. */
  breakOut(windowName?: string): Promise<void> {
    return breakPane(runtimeForServer(this.server), this.pane_id, windowName);
  }

  /** Move this pane into another window as a split. */
  joinTo(target: string, options?: { readonly vertical?: boolean }): Promise<void> {
    return joinPane(runtimeForServer(this.server), this.pane_id, target, options);
  }

  /** Enter this pane's copy mode. */
  enterCopyMode(): Promise<void> {
    return setCopyMode(runtimeForServer(this.server), this.pane_id, true);
  }

  /** Leave this pane's copy mode. */
  exitCopyMode(): Promise<void> {
    return setCopyMode(runtimeForServer(this.server), this.pane_id, false);
  }

  /** Open a popup over the client showing this pane. */
  displayPopup(command?: string, options?: PopupOptions): Promise<void> {
    return displayPopup(runtimeForServer(this.server), this.pane_id, command, options);
  }

  /** Show a menu over the client showing this pane. */
  displayMenu(title: string, items: readonly MenuItem[]): Promise<void> {
    return displayMenu(runtimeForServer(this.server), this.pane_id, title, items);
  }

  /** Open the interactive session and window chooser in this pane. */
  chooseTree(options?: ChooseTreeOptions): Promise<void> {
    return chooseTree(runtimeForServer(this.server), this.pane_id, options);
  }

  /** Open the interactive buffer chooser in this pane. */
  chooseBuffer(): Promise<void> {
    return chooseBuffer(runtimeForServer(this.server), this.pane_id);
  }

  /** Search windows interactively from this pane. */
  findWindow(pattern: string): Promise<void> {
    return findWindow(runtimeForServer(this.server), this.pane_id, pattern);
  }

  /** Send the configured prefix key to this pane. */
  sendPrefix(): Promise<void> {
    return sendPrefix(runtimeForServer(this.server), this.pane_id);
  }

  /** Open tmux's interactive option editor in this pane. */
  customizeMode(): Promise<void> {
    return customizeMode(runtimeForServer(this.server), this.pane_id);
  }

  equals(other: unknown): boolean {
    return liveHandlesEqual(this, other);
  }
}

export interface Pane extends CompleteFormatRow {}

installLiveHandlePrototype(Pane.prototype);
