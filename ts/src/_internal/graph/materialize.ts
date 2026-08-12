import { Client } from "../../client.js";
import { LibTmuxException, QueryValidationError } from "../../exc.js";
import { Pane } from "../../pane.js";
import type { Server } from "../../server.js";
import { Session } from "../../session.js";
import { Window } from "../../window.js";
import { runtimeForServer, type RuntimeContext } from "../runtime/context.js";
import {
  compareAndSwapLiveHandleState,
  initializeLiveHandle,
  liveHandleStateForReplacement,
  type LiveHandleInitialization,
} from "../runtime/live_handle.js";
import {
  graphRecordRefsEqual,
  isNormalizedGraph,
  type GraphRecord,
  type GraphRecordRef,
  type NormalizedGraph,
} from "./model.js";
import {
  originGraphForSelectionProjection,
  selectionProjectionOwnsRecord,
  type ProjectionRecord,
  type SelectionProjection,
} from "./selection_projection.js";

type Child = Client | Pane | Session | Window;
type ProjectedChild = Pane | Session | Window;

function invalidMaterialization(message: string): never {
  throw new QueryValidationError({ code: "invalid-query", message });
}

function requireAuthenticGraph(graph: NormalizedGraph): NormalizedGraph {
  if (!isNormalizedGraph(graph)) {
    return invalidMaterialization("handle materialization requires an authentic normalized graph");
  }
  return graph;
}

function requireProjectionGraph(
  projection: SelectionProjection,
  graph: NormalizedGraph,
): NormalizedGraph {
  const authenticGraph = requireAuthenticGraph(graph);
  const origin = originGraphForSelectionProjection(projection);
  if (origin === undefined) {
    return invalidMaterialization("handle materialization requires an authentic projection");
  }
  if (origin !== authenticGraph) {
    return invalidMaterialization("selection projection belongs to another normalized graph");
  }
  return authenticGraph;
}

function resolveGraphRecord(graph: NormalizedGraph, ref: GraphRecordRef): GraphRecord {
  if (!graphRecordRefsEqual(ref, ref)) {
    return invalidMaterialization("graph record reference is not authentic");
  }
  const record = graph.records.find((candidate) => graphRecordRefsEqual(candidate.ref, ref));
  if (record === undefined) {
    return invalidMaterialization("graph record reference does not exist in the normalized graph");
  }
  return record;
}

function resolveProjectionRecord(
  projection: SelectionProjection,
  graph: NormalizedGraph,
  record: ProjectionRecord,
): GraphRecord {
  const authenticGraph = requireProjectionGraph(projection, graph);
  if (!selectionProjectionOwnsRecord(projection, record)) {
    return invalidMaterialization("projection record belongs to another selection projection");
  }
  const graphRecord = resolveGraphRecord(authenticGraph, record.ref);
  if (graphRecord.model !== record.model) {
    return invalidMaterialization("projection record model does not match its normalized record");
  }
  return graphRecord;
}

function assertCurrentCapture(runtime: RuntimeContext, graph: NormalizedGraph): void {
  if (graph.capture.connection !== runtime.connectionAlias) {
    throw new LibTmuxException("normalized graph belongs to another runtime");
  }
  if (graph.capture.epoch !== runtime.daemonEpoch) {
    throw new LibTmuxException("normalized graph daemon epoch is stale");
  }
}

async function validateRuntimeCapture(server: Server, graph: NormalizedGraph): Promise<void> {
  const runtime = runtimeForServer(server);
  assertCurrentCapture(runtime, graph);

  const capabilities = await runtime.capabilities.bind();

  assertCurrentCapture(runtime, graph);
  if (
    capabilities.connectionAlias !== runtime.connectionAlias ||
    capabilities.daemonEpoch !== runtime.daemonEpoch ||
    capabilities.fingerprint !== graph.capture.capabilityFingerprint
  ) {
    throw new LibTmuxException("normalized graph capability binding is stale");
  }
}

function initialize<Handle extends Child>(
  prototype: object,
  server: Server,
  graph: NormalizedGraph,
  record: GraphRecord,
): Handle {
  const handle = Object.create(prototype) as Handle;
  return initializeLiveHandle(handle, {
    entity: record.entity,
    graph,
    model: record.model,
    record: record.ref,
    server,
    snapshot: record.scalars,
    winlink: record.winlink,
  });
}

function createProjectedHandle(
  server: Server,
  graph: NormalizedGraph,
  record: GraphRecord,
): ProjectedChild {
  switch (record.model) {
    case "pane":
      return initialize<Pane>(Pane.prototype, server, graph, record);
    case "session":
      return initialize<Session>(Session.prototype, server, graph, record);
    case "window":
      return initialize<Window>(Window.prototype, server, graph, record);
    case "client":
      return invalidMaterialization("Client records cannot be materialized from a projection");
  }
}

function createClientHandle(server: Server, graph: NormalizedGraph, record: GraphRecord): Client {
  if (record.model !== "client") {
    return invalidMaterialization("Client materialization requires a Client graph record");
  }
  return initialize<Client>(Client.prototype, server, graph, record);
}

function replacementEntitiesMatch(
  current: LiveHandleInitialization["entity"],
  replacement: GraphRecord["entity"],
): boolean {
  return (
    current.connection === replacement.connection &&
    current.epoch === replacement.epoch &&
    current.kind === replacement.kind &&
    current.id === replacement.id
  );
}

function validateReplacementRecord(state: LiveHandleInitialization, record: GraphRecord): void {
  if (record.model !== state.model) {
    return invalidMaterialization("replacement record model does not match the handle");
  }
  if (!replacementEntitiesMatch(state.entity, record.entity)) {
    return invalidMaterialization("replacement record belongs to another durable entity");
  }
  if ((record.model === "client" || record.model === "session") && record.winlink !== null) {
    return invalidMaterialization("Client and Session replacement records cannot have winlinks");
  }
  if ((record.model === "pane" || record.model === "window") && record.winlink === null) {
    return invalidMaterialization("Pane and Window replacement records require winlinks");
  }
}

function projectionRecordForMember(
  projection: SelectionProjection,
  member: GraphRecordRef,
): ProjectionRecord {
  const record = projection.records.find((candidate) =>
    graphRecordRefsEqual(candidate.ref, member),
  );
  if (record === undefined || !selectionProjectionOwnsRecord(projection, record)) {
    return invalidMaterialization("projection member has no owned projection record");
  }
  return record;
}

export async function materializeProjectionRecord(
  server: Server,
  projection: SelectionProjection,
  graph: NormalizedGraph,
  record: ProjectionRecord,
): Promise<ProjectedChild> {
  const graphRecord = resolveProjectionRecord(projection, graph, record);
  await validateRuntimeCapture(server, graph);
  return createProjectedHandle(server, graph, graphRecord);
}

export async function materializeProjectionMembers(
  server: Server,
  projection: SelectionProjection,
  graph: NormalizedGraph,
): Promise<readonly ProjectedChild[]> {
  const authenticGraph = requireProjectionGraph(projection, graph);
  const graphRecords = projection.members.map((member) =>
    resolveProjectionRecord(
      projection,
      authenticGraph,
      projectionRecordForMember(projection, member),
    ),
  );
  await validateRuntimeCapture(server, authenticGraph);
  return Object.freeze(
    graphRecords.map((record) => createProjectedHandle(server, authenticGraph, record)),
  );
}

export async function materializeClientRecord(
  server: Server,
  graph: NormalizedGraph,
  record: GraphRecordRef,
): Promise<Client> {
  const authenticGraph = requireAuthenticGraph(graph);
  const graphRecord = resolveGraphRecord(authenticGraph, record);
  if (graphRecord.model !== "client") {
    return invalidMaterialization("Client materialization requires a Client graph record");
  }
  await validateRuntimeCapture(server, authenticGraph);
  return createClientHandle(server, authenticGraph, graphRecord);
}

export async function replaceHandleSnapshotFromGraph(
  handle: Child,
  graph: NormalizedGraph,
  record: GraphRecordRef,
): Promise<void> {
  const state = liveHandleStateForReplacement(handle);
  const authenticGraph = requireAuthenticGraph(graph);
  const graphRecord = resolveGraphRecord(authenticGraph, record);
  validateReplacementRecord(state, graphRecord);
  await validateRuntimeCapture(state.server, authenticGraph);
  compareAndSwapLiveHandleState(
    handle,
    state,
    authenticGraph,
    graphRecord.ref,
    graphRecord.scalars,
    graphRecord.winlink,
  );
}
