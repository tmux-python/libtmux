import { LibTmuxException } from "../../exc.js";
import { replaceHandleSnapshotFromGraph } from "../graph/materialize.js";
import type { GraphRecord } from "../graph/model.js";
import type { RuntimeContext } from "../runtime/context.js";
import { entityRefForHandle, winlinkRefForHandle } from "../runtime/live_handle.js";
import { acquireServerGraph } from "./acquire.js";
import { selectionOfModel } from "./projections.js";

type Refreshable = Parameters<typeof replaceHandleSnapshotFromGraph>[0];

function sameWinlink(record: GraphRecord, handle: Refreshable): boolean {
  const wanted = winlinkRefForHandle(handle);
  if (wanted === null) return true;
  const found = record.winlink;
  return (
    found !== null &&
    found.sessionId === wanted.sessionId &&
    found.windowId === wanted.windowId &&
    found.windowIndex === wanted.windowIndex
  );
}

/**
 * Re-read one handle at the current instant, in place.
 *
 * This is the deliberate exception to snapshot immutability, and it is scoped
 * to a single receiver: selections stay frozen, and only the handle the caller
 * named advances. A window keeps the placement it was resolved at, so
 * refreshing one placement of a linked window never silently retargets it at
 * the other.
 *
 * Refreshing an object tmux no longer has raises rather than leaving a handle
 * quietly describing something that is gone.
 */
export async function refreshHandle(handle: Refreshable, runtime: RuntimeContext): Promise<void> {
  const graph = await acquireServerGraph(runtime);
  // A refreshed handle reads its relations from the graph it now points at, so
  // that graph's handles must be materialized before the swap.
  await Promise.all([
    selectionOfModel(handle.server, graph, "session"),
    selectionOfModel(handle.server, graph, "window"),
    selectionOfModel(handle.server, graph, "pane"),
  ]);
  const identity = entityRefForHandle(handle);
  const match = graph.records.find(
    (record) => record.entity.id === identity.id && sameWinlink(record, handle),
  );
  if (match === undefined) {
    throw new LibTmuxException(`${String(identity.id)} no longer exists on the server`);
  }
  await replaceHandleSnapshotFromGraph(handle, graph, match.ref);
}
