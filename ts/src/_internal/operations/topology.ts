import type { RuntimeContext } from "../runtime/context.js";
import { runCommand } from "./command.js";

export interface MoveWindowOptions {
  /** Destination index; tmux picks the next free one when omitted. */
  readonly index?: number;
  /** Destination session; the window stays in its own session when omitted. */
  readonly session?: string;
}

function destination(options: MoveWindowOptions): readonly string[] {
  if (options.session === undefined && options.index === undefined) return [];
  const session = options.session ?? "";
  return ["-t", `${session}:${options.index === undefined ? "" : String(options.index)}`];
}

export async function renameWindow(
  runtime: RuntimeContext,
  windowId: string | null,
  name: string,
): Promise<void> {
  await runCommand(runtime, ["rename-window", ...target(windowId), name]);
}

/**
 * Move a window placement elsewhere.
 *
 * `-d` keeps the destination session from being selected as a side effect, so
 * moving a window never silently changes which session a client is looking at.
 */
export async function moveWindow(
  runtime: RuntimeContext,
  windowId: string | null,
  options: MoveWindowOptions = {},
): Promise<void> {
  await runCommand(runtime, [
    "move-window",
    "-d",
    ...(windowId == null ? [] : ["-s", windowId]),
    ...destination(options),
  ]);
}

/** Link a window into another session, giving it a second placement. */
export async function linkWindow(
  runtime: RuntimeContext,
  windowId: string | null,
  options: MoveWindowOptions,
): Promise<void> {
  await runCommand(runtime, [
    "link-window",
    "-d",
    ...(windowId == null ? [] : ["-s", windowId]),
    ...destination(options),
  ]);
}

/** Remove one placement of a window, leaving its other placements intact. */
export async function unlinkWindow(
  runtime: RuntimeContext,
  windowId: string | null,
): Promise<void> {
  await runCommand(runtime, ["unlink-window", ...target(windowId)]);
}

/** Exchange the positions of two windows. */
export async function swapWindows(
  runtime: RuntimeContext,
  source: string | null,
  destinationWindow: string | null,
): Promise<void> {
  await runCommand(runtime, [
    "swap-window",
    "-d",
    ...(source == null ? [] : ["-s", source]),
    ...(destinationWindow == null ? [] : ["-t", destinationWindow]),
  ]);
}

/** Apply a named or custom layout to a window. */
export async function selectLayout(
  runtime: RuntimeContext,
  windowId: string | null,
  layout: string,
): Promise<void> {
  await runCommand(runtime, ["select-layout", ...target(windowId), layout]);
}

export interface ResizeOptions {
  readonly height?: number;
  readonly width?: number;
}

/** Resize a pane; tmux ignores a dimension its layout cannot honour. */
export async function resizePane(
  runtime: RuntimeContext,
  paneId: string | null,
  options: ResizeOptions,
): Promise<void> {
  await runCommand(runtime, [
    "resize-pane",
    ...target(paneId),
    ...(options.width === undefined ? [] : ["-x", String(options.width)]),
    ...(options.height === undefined ? [] : ["-y", String(options.height)]),
  ]);
}

/** Exchange the positions of two panes. */
export async function swapPanes(
  runtime: RuntimeContext,
  source: string | null,
  destinationPane: string | null,
): Promise<void> {
  await runCommand(runtime, [
    "swap-pane",
    "-d",
    ...(source == null ? [] : ["-s", source]),
    ...(destinationPane == null ? [] : ["-t", destinationPane]),
  ]);
}

/** Make a window or pane the active one in its parent. */
export async function selectTarget(
  runtime: RuntimeContext,
  command: "select-pane" | "select-window",
  id: string | null,
): Promise<void> {
  await runCommand(runtime, [command, ...target(id)]);
}

function target(id: string | null): readonly string[] {
  return id == null ? [] : ["-t", id];
}
