import { executeGuardedList } from "../codec/guard_codec.js";
import { createGraphSourceId, type CapturedRowSet, type NormalizedGraph } from "../graph/model.js";
import { normalizeGraph } from "../graph/normalize.js";
import type { RuntimeContext } from "../runtime/context.js";

/**
 * Acquire the server's complete object graph.
 *
 * Every `list-*` row becomes exactly one record whose model the subcommand
 * fixes, so a pane row registers its session and window entities but is not a
 * session or window record. Each model therefore needs its own listing to
 * supply the contextual rows a selection draws its members from.
 *
 * The four listings run concurrently and their count does not vary with the
 * topology, which is what lets relation traversal stay free of I/O. Listing
 * windows and panes with `-a` keeps that true across every session, and both
 * placements of a window linked into two sessions survive as two window
 * records sharing one window entity.
 */
export async function acquireServerGraph(runtime: RuntimeContext): Promise<NormalizedGraph> {
  const query = {
    capabilities: runtime.capabilities,
    connection: runtime.connection,
    transport: runtime.transport,
  };
  const [capabilities, sessions, windows, panes, clients] = await Promise.all([
    runtime.capabilities.bind(),
    executeGuardedList({ ...query, listCommand: "list-sessions" }),
    executeGuardedList({ ...query, listCommand: "list-windows", listExtraArgs: ["-a"] }),
    executeGuardedList({ ...query, listCommand: "list-panes", listExtraArgs: ["-a"] }),
    executeGuardedList({ ...query, listCommand: "list-clients" }),
  ]);

  return normalizeGraph({
    capture: {
      capabilityFingerprint: capabilities.fingerprint,
      connection: capabilities.connectionAlias,
      epoch: capabilities.daemonEpoch,
    },
    sources: [
      { listCommand: "list-sessions", rows: sessions, source: createGraphSourceId("sessions") },
      { listCommand: "list-windows", rows: windows, source: createGraphSourceId("windows") },
      { listCommand: "list-panes", rows: panes, source: createGraphSourceId("panes") },
      { listCommand: "list-clients", rows: clients, source: createGraphSourceId("clients") },
    ] satisfies readonly CapturedRowSet[],
  });
}
