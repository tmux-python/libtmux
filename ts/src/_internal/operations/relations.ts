import type { Pane } from "../../pane.js";
import type { Selection } from "../../selection.js";
import type { Server } from "../../server.js";
import type { Session } from "../../session.js";
import type { Window } from "../../window.js";
import type { NormalizedGraph } from "../graph/model.js";
import { selectionOfModel } from "./projections.js";

/** The contextual placement a window occupies in a session. */
interface Placement {
  readonly session_id: string | null;
  readonly window_id: string | null;
  readonly window_index: string | null;
}

const samePlacement = (left: Placement, right: Placement): boolean =>
  left.session_id === right.session_id &&
  left.window_id === right.window_id &&
  left.window_index === right.window_index;

export async function windowsOfSession(
  server: Server,
  graph: NormalizedGraph,
  sessionId: string | null,
): Promise<Selection<Window>> {
  const windows = await selectionOfModel(server, graph, "window");
  return windows.filter((window) => window.session_id === sessionId);
}

export async function panesOfSession(
  server: Server,
  graph: NormalizedGraph,
  sessionId: string | null,
): Promise<Selection<Pane>> {
  const panes = await selectionOfModel(server, graph, "pane");
  return panes.filter((pane) => pane.session_id === sessionId);
}

/** Panes of one window placement, so a linked window keeps its two sets apart. */
export async function panesOfPlacement(
  server: Server,
  graph: NormalizedGraph,
  placement: Placement,
): Promise<Selection<Pane>> {
  const panes = await selectionOfModel(server, graph, "pane");
  return panes.filter((pane) => samePlacement(pane, placement));
}

export async function sessionOf(
  server: Server,
  graph: NormalizedGraph,
  sessionId: string | null,
): Promise<Session | undefined> {
  const sessions = await selectionOfModel(server, graph, "session");
  return sessions.filter((session) => session.session_id === sessionId).first();
}

export async function windowOfPlacement(
  server: Server,
  graph: NormalizedGraph,
  placement: Placement,
): Promise<Window | undefined> {
  const windows = await selectionOfModel(server, graph, "window");
  return windows.filter((window) => samePlacement(window, placement)).first();
}

export async function paneById(
  server: Server,
  graph: NormalizedGraph,
  paneId: string | null,
): Promise<Pane | undefined> {
  const panes = await selectionOfModel(server, graph, "pane");
  return panes.filter((pane) => pane.pane_id === paneId).first();
}

/** Every session a window is linked into, deduplicated by session identity. */
export async function linkedSessionsOfWindow(
  server: Server,
  graph: NormalizedGraph,
  windowId: string | null,
): Promise<Selection<Session>> {
  const windows = await selectionOfModel(server, graph, "window");
  const sessionIds = new Set(
    windows
      .filter((window) => window.window_id === windowId)
      .toArray()
      .map(({ session_id }) => session_id),
  );
  const sessions = await selectionOfModel(server, graph, "session");
  return sessions.filter((session) => sessionIds.has(session.session_id));
}
