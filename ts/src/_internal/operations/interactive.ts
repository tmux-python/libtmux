import type { ChooseTreeOptions, MenuItem, PopupOptions } from "../../types.js";
import { runCommand } from "./command.js";
import type { RuntimeContext } from "../runtime/context.js";

const target = (id: string | null): readonly string[] => (id == null ? [] : ["-t", id]);

/**
 * Open a popup over a client.
 *
 * Popups are client-owned, so this needs an attached client; tmux rejects it
 * otherwise rather than opening one invisibly.
 */
export async function displayPopup(
  runtime: RuntimeContext,
  clientOrPane: string | null,
  command: string | undefined,
  options: PopupOptions = {},
): Promise<void> {
  await runCommand(runtime, [
    "display-popup",
    ...(options.closeOnExit === false ? [] : ["-E"]),
    ...(options.width === undefined ? [] : ["-w", options.width]),
    ...(options.height === undefined ? [] : ["-h", options.height]),
    ...(options.directory === undefined ? [] : ["-d", options.directory]),
    ...target(clientOrPane),
    ...(command === undefined ? [] : [command]),
  ]);
}

/**
 * Show a menu over a client.
 *
 * This resolves only once the menu is dismissed, because tmux keeps the
 * client's menu open until someone chooses an entry or cancels. Callers driving
 * tmux non-interactively should not await it before sending the key that closes
 * it, or they will wait forever.
 */
export async function displayMenu(
  runtime: RuntimeContext,
  paneId: string | null,
  title: string,
  items: readonly MenuItem[],
): Promise<void> {
  await runCommand(runtime, [
    "display-menu",
    "-T",
    title,
    ...target(paneId),
    ...items.flatMap((item) => (item === "separator" ? [""] : [item.name, item.key, item.command])),
  ]);
}

/** Open tmux's interactive session and window chooser on a pane. */
export async function chooseTree(
  runtime: RuntimeContext,
  paneId: string | null,
  options: ChooseTreeOptions = {},
): Promise<void> {
  await runCommand(runtime, [
    "choose-tree",
    ...(options.sessionsOnly === true ? ["-s"] : []),
    ...(options.windowsOnly === true ? ["-w"] : []),
    ...target(paneId),
  ]);
}

/** Open the interactive buffer chooser on a pane. */
export async function chooseBuffer(runtime: RuntimeContext, paneId: string | null): Promise<void> {
  await runCommand(runtime, ["choose-buffer", ...target(paneId)]);
}

/** Search windows interactively, seeding the prompt with a pattern. */
export async function findWindow(
  runtime: RuntimeContext,
  paneId: string | null,
  pattern: string,
): Promise<void> {
  await runCommand(runtime, ["find-window", ...target(paneId), pattern]);
}

/** Send the configured prefix key to a pane. */
export async function sendPrefix(runtime: RuntimeContext, paneId: string | null): Promise<void> {
  await runCommand(runtime, ["send-prefix", ...target(paneId)]);
}

/** Open tmux's interactive option editor on a pane. */
export async function customizeMode(runtime: RuntimeContext, paneId: string | null): Promise<void> {
  await runCommand(runtime, ["customize-mode", ...target(paneId)]);
}
