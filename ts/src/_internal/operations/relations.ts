import type { Pane } from "../../pane.js";
import type { Selection } from "../../selection.js";
import type { Session } from "../../session.js";
import type { Window } from "../../window.js";
import type { NormalizedGraph } from "../graph/model.js";
import { settledSelectionOfModel } from "./projections.js";

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

/**
 * Relations read the handles materialized when the graph was acquired.
 *
 * Every accessor here is synchronous, because the work happened during
 * acquisition and narrowing is local. A relation returning a promise would
 * imply I/O that this design specifically forbids.
 *
 * Callers wanting a subset narrow the whole model, because a projection draws
 * its members from a whole listing.
 */
export function windowsOfSession(
  graph: NormalizedGraph,
  sessionId: string | null,
): Selection<Window> {
  return settledSelectionOfModel(graph, "window").filter(
    (window) => window.session_id === sessionId,
  );
}

export function panesOfSession(graph: NormalizedGraph, sessionId: string | null): Selection<Pane> {
  return settledSelectionOfModel(graph, "pane").filter((pane) => pane.session_id === sessionId);
}

/** Panes of one window placement, so a linked window keeps its two sets apart. */
export function panesOfPlacement(graph: NormalizedGraph, placement: Placement): Selection<Pane> {
  return settledSelectionOfModel(graph, "pane").filter((pane) => samePlacement(pane, placement));
}

export function sessionOf(graph: NormalizedGraph, sessionId: string | null): Session | undefined {
  return settledSelectionOfModel(graph, "session")
    .filter((session) => session.session_id === sessionId)
    .first();
}

export function windowOfPlacement(
  graph: NormalizedGraph,
  placement: Placement,
): Window | undefined {
  return settledSelectionOfModel(graph, "window")
    .filter((window) => samePlacement(window, placement))
    .first();
}

export function paneById(graph: NormalizedGraph, paneId: string | null): Pane | undefined {
  return settledSelectionOfModel(graph, "pane")
    .filter((pane) => pane.pane_id === paneId)
    .first();
}

/** Every session a window is linked into, deduplicated by session identity. */
export function linkedSessionsOfWindow(
  graph: NormalizedGraph,
  windowId: string | null,
): Selection<Session> {
  const sessionIds = new Set(
    settledSelectionOfModel(graph, "window")
      .filter((window) => window.window_id === windowId)
      .toArray()
      .map(({ session_id }) => session_id),
  );
  return settledSelectionOfModel(graph, "session").filter((session) =>
    sessionIds.has(session.session_id),
  );
}
