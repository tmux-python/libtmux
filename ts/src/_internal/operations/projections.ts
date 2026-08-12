import type { Selection } from "../../selection.js";
import type { Server } from "../../server.js";
import { materializeProjectionMembers } from "../graph/materialize.js";
import { createGraphSourceId, type GraphSourceId, type NormalizedGraph } from "../graph/model.js";
import type { ModelForKind } from "../runtime/model_kind.js";
import { createProjectedSelection } from "../selection/evaluate.js";
import { hydrateProjection } from "./hydrate.js";

export type ProjectedModel = "pane" | "session" | "window";

/**
 * The listing each model draws its members from.
 *
 * Stated rather than derived from the model name, so renaming a source is a
 * compile error here instead of an empty projection at runtime.
 */
const MEMBER_SOURCES: Readonly<Record<ProjectedModel, GraphSourceId>> = Object.freeze({
  pane: createGraphSourceId("panes"),
  session: createGraphSourceId("sessions"),
  window: createGraphSourceId("windows"),
});

/**
 * A graph is frozen and belongs to one acquisition, so the same graph and model
 * always yield the same handles. Without this, every relation accessor
 * re-hydrates and re-materializes an entire model: reading a session's windows
 * and then its panes costs two full passes, and counting windows across N
 * sessions costs N.
 */
const memo = new WeakMap<
  NormalizedGraph,
  Map<ProjectedModel, Promise<Selection<ModelForKind<ProjectedModel>>>>
>();

async function buildSelection<Model extends ProjectedModel>(
  server: Server,
  graph: NormalizedGraph,
  model: Model,
): Promise<Selection<ModelForKind<Model>>> {
  const projection = hydrateProjection(graph, MEMBER_SOURCES[model]);
  const members = await materializeProjectionMembers(server, projection, graph);
  // The projection's members are exactly this model's records, so every
  // materialized handle is that model; the union materialize returns cannot
  // express that narrowing on its own.
  return createProjectedSelection(model, members as readonly ModelForKind<Model>[], projection);
}

/**
 * Materialize every handle of one model from a graph the caller already holds.
 *
 * Callers that want a subset narrow the result, because a projection draws its
 * members from a whole listing. Narrowing is local, so nothing built on this
 * issues a tmux command.
 */
export function selectionOfModel<Model extends ProjectedModel>(
  server: Server,
  graph: NormalizedGraph,
  model: Model,
): Promise<Selection<ModelForKind<Model>>> {
  const byModel = memo.get(graph) ?? new Map();
  memo.set(graph, byModel);
  const cached = byModel.get(model);
  if (cached !== undefined) return cached as Promise<Selection<ModelForKind<Model>>>;

  const built = buildSelection(server, graph, model);
  byModel.set(model, built as Promise<Selection<ModelForKind<ProjectedModel>>>);
  return built;
}
