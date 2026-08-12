import { Server, TmuxCommandError, type ServerSnapshot } from "../src/index.js";

/**
 * A runnable tour of the API, driven by the tests so it cannot rot.
 *
 * Every step here appears in README.md.
 */
export async function quickstart(server: Server): Promise<ServerSnapshot> {
  // Nothing is read until you ask. `snapshot()` is the only step that talks to
  // tmux; everything reachable from it resolves locally.
  const session = await server.newSession({ name: "quickstart" });
  const editor = await session.newWindow({ name: "editor" });
  await editor.split();

  const snapshot = await server.snapshot();

  // Declarative filtering, serializable and stable on the wire.
  const found = snapshot.windows.where({ name: "editor" }).one();

  // Relations are plain properties: no await, no tmux command.
  const paneCount = found.panes.length;
  if (paneCount !== 2) throw new Error(`expected two panes, saw ${String(paneCount)}`);

  // A criterion is spelled like the handle accessor it filters.
  if (snapshot.panes.count({ currentCommand: { contains: "" } }) === 0) {
    throw new Error("expected panes to report a current command");
  }
  const first = found.panes.at(0);
  if (first === undefined) throw new Error("expected a pane");
  await first.sendKeys("echo hello-from-libtmux", { literal: true });

  // Failures carry their parts rather than a formatted sentence.
  try {
    await server.setOption("not-a-real-option", "1");
  } catch (error) {
    if (!(error instanceof TmuxCommandError)) throw error;
    if (error.args[0] !== "set-option") throw error;
  }

  return snapshot;
}
