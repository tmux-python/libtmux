import type { NewSessionOptions, NewWindowOptions, SplitOptions } from "../../types.js";
import { LibTmuxException } from "../../exc.js";
import type { Pane } from "../../pane.js";
import type { Server } from "../../server.js";
import type { Session } from "../../session.js";
import type { Window } from "../../window.js";
import type { RuntimeContext } from "../runtime/context.js";
import { runCommand } from "./command.js";
import { buildServerSnapshot } from "./snapshot.js";

function requireIdentity(lines: readonly string[], command: string): string {
  const identity = lines[0];
  if (identity === undefined || identity === "") {
    throw new LibTmuxException(`${command} did not report the created object's identity`);
  }
  return identity;
}

export async function newSession(
  server: Server,
  runtime: RuntimeContext,
  options: NewSessionOptions = {},
): Promise<Session> {
  const lines = await runCommand(runtime, [
    "new-session",
    "-d",
    "-P",
    "-F",
    "#{session_id}",
    ...(options.name === undefined ? [] : ["-s", options.name]),
    ...(options.windowName === undefined ? [] : ["-n", options.windowName]),
    ...(options.startDirectory === undefined ? [] : ["-c", options.startDirectory]),
  ]);
  const sessionId = requireIdentity(lines, "new-session");
  const snapshot = await buildServerSnapshot(server, runtime);
  const created = snapshot.sessions.filter((session) => session.session_id === sessionId).first();
  if (created === undefined) {
    throw new LibTmuxException(
      `new-session created ${sessionId} but it was gone before it resolved`,
    );
  }
  return created;
}

export async function newWindow(
  server: Server,
  runtime: RuntimeContext,
  sessionId: string | null,
  options: NewWindowOptions = {},
): Promise<Window> {
  const lines = await runCommand(runtime, [
    "new-window",
    "-d",
    "-P",
    "-F",
    "#{window_id}",
    ...(sessionId == null ? [] : ["-t", sessionId]),
    ...(options.name === undefined ? [] : ["-n", options.name]),
    ...(options.startDirectory === undefined ? [] : ["-c", options.startDirectory]),
  ]);
  const windowId = requireIdentity(lines, "new-window");
  const snapshot = await buildServerSnapshot(server, runtime);
  const created = snapshot.windows
    .filter((window) => window.window_id === windowId && window.session_id === sessionId)
    .first();
  if (created === undefined) {
    throw new LibTmuxException(`new-window created ${windowId} but it was gone before it resolved`);
  }
  return created;
}

export async function splitWindow(
  server: Server,
  runtime: RuntimeContext,
  target: string | null,
  options: SplitOptions = {},
): Promise<Pane> {
  const lines = await runCommand(runtime, [
    "split-window",
    "-d",
    "-P",
    "-F",
    "#{pane_id}",
    // tmux splits horizontally with -h; -v is its default, so only -h is passed.
    ...(options.vertical === false ? ["-h"] : []),
    ...(target == null ? [] : ["-t", target]),
    ...(options.startDirectory === undefined ? [] : ["-c", options.startDirectory]),
  ]);
  const paneId = requireIdentity(lines, "split-window");
  const snapshot = await buildServerSnapshot(server, runtime);
  const created = snapshot.panes.filter((pane) => pane.pane_id === paneId).first();
  if (created === undefined) {
    throw new LibTmuxException(`split-window created ${paneId} but it was gone before it resolved`);
  }
  return created;
}

export async function killTarget(
  runtime: RuntimeContext,
  command: "kill-pane" | "kill-session" | "kill-window",
  target: string | null,
): Promise<void> {
  await runCommand(runtime, [command, ...(target == null ? [] : ["-t", target])]);
}

export async function killServer(runtime: RuntimeContext): Promise<void> {
  await runCommand(runtime, ["kill-server"]);
}
