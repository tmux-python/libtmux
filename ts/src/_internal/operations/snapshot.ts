import type { Client } from "../../client.js";
import type { Pane } from "../../pane.js";
import type { Selection } from "../../selection.js";
import type { Server } from "../../server.js";
import type { Session } from "../../session.js";
import type { Window } from "../../window.js";
import { materializeClientRecord } from "../graph/materialize.js";
import type { NormalizedGraph } from "../graph/model.js";
import type { RuntimeContext } from "../runtime/context.js";
import { createClientSelection } from "../selection/evaluate.js";
import { acquireServerGraph } from "./acquire.js";
import { selectionOfModel } from "./projections.js";

/** An immutable view of the server at one instant. */
export interface ServerSnapshot {
  readonly clients: Selection<Client>;
  readonly panes: Selection<Pane>;
  readonly sessions: Selection<Session>;
  readonly windows: Selection<Window>;
}

async function clientSelection(server: Server, graph: NormalizedGraph): Promise<Selection<Client>> {
  const clients = await Promise.all(
    graph.records
      .filter((record) => record.model === "client")
      .map((record) => materializeClientRecord(server, graph, record.ref)),
  );
  return createClientSelection(clients);
}

/**
 * Build every selection from one acquisition.
 *
 * Each model needs its own projection because a projection's members come from
 * a single listing, but all four share the graph that acquisition produced, so
 * the whole snapshot still costs one round of tmux commands.
 */
export async function buildServerSnapshot(
  server: Server,
  runtime: RuntimeContext,
): Promise<ServerSnapshot> {
  const graph = await acquireServerGraph(runtime);
  const [sessions, windows, panes, clients] = await Promise.all([
    selectionOfModel(server, graph, "session"),
    selectionOfModel(server, graph, "window"),
    selectionOfModel(server, graph, "pane"),
    clientSelection(server, graph),
  ]);

  return Object.freeze({ clients, panes, sessions, windows });
}
