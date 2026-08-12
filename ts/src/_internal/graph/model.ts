import type {
  ConnectionAlias,
  DaemonEpoch,
  LogicalRef,
  PaneRef,
  SessionRef,
  WindowRef,
} from "../../common.js";
import { QueryValidationError } from "../../exc.js";
import type { ListCommand } from "../codec/format_types.js";
import type { CompleteFormatRow } from "../codec/schemas.js";
import type { WinlinkRef } from "./refs.js";

declare const graphSourceIdBrand: unique symbol;

export type GraphSourceId = string & {
  readonly [graphSourceIdBrand]: "graph-source";
};

declare class GraphRecordRefNominal {
  private readonly graphRecordRefBrand: undefined;
}

export interface GraphRecordRef extends GraphRecordRefNominal {
  readonly ordinal: number;
  readonly source: GraphSourceId;
}

export interface GraphCapture {
  readonly capabilityFingerprint: string;
  readonly connection: ConnectionAlias;
  readonly epoch: DaemonEpoch;
}

export interface CapturedRowSet {
  readonly listCommand: ListCommand;
  readonly rows: readonly CompleteFormatRow[];
  readonly source: GraphSourceId;
}

export interface GraphSource {
  readonly id: GraphSourceId;
  readonly listCommand: ListCommand;
  readonly records: readonly GraphRecordRef[];
}

export interface ClientRef {
  readonly connection: ConnectionAlias;
  readonly epoch: DaemonEpoch;
  readonly id: string;
  readonly kind: "client";
}

export type GraphEntityRef = ClientRef | LogicalRef;

export interface GraphEntity<Ref extends GraphEntityRef = GraphEntityRef> {
  readonly occurrences: readonly GraphRecordRef[];
  readonly ref: Ref;
}

export interface WinlinkEntity {
  readonly occurrences: readonly GraphRecordRef[];
  readonly ref: WinlinkRef;
}

export type GraphModel = "client" | "pane" | "session" | "window";

export interface GraphRecord {
  readonly entity: GraphEntityRef;
  readonly model: GraphModel;
  readonly ref: GraphRecordRef;
  readonly scalars: CompleteFormatRow;
  readonly winlink: WinlinkRef | null;
}

declare class NormalizedGraphNominal {
  private readonly normalizedGraphBrand: undefined;
}

export interface NormalizedGraph extends NormalizedGraphNominal {
  readonly capture: GraphCapture;
  readonly clients: readonly GraphEntity<ClientRef>[];
  readonly panes: readonly GraphEntity<PaneRef>[];
  readonly records: readonly GraphRecord[];
  readonly sessions: readonly GraphEntity<SessionRef>[];
  readonly sources: readonly GraphSource[];
  readonly windows: readonly GraphEntity<WindowRef>[];
  readonly winlinks: readonly WinlinkEntity[];
}

const authenticatedGraphRecordRefs = new WeakSet<object>();
const authenticatedNormalizedGraphs = new WeakSet<object>();

interface NormalizedGraphData {
  readonly capture: GraphCapture;
  readonly clients: readonly GraphEntity<ClientRef>[];
  readonly panes: readonly GraphEntity<PaneRef>[];
  readonly records: readonly GraphRecord[];
  readonly sessions: readonly GraphEntity<SessionRef>[];
  readonly sources: readonly GraphSource[];
  readonly windows: readonly GraphEntity<WindowRef>[];
  readonly winlinks: readonly WinlinkEntity[];
}

function invalidGraphIdentity(message: string): never {
  throw new QueryValidationError({ code: "invalid-query", message });
}

export function createGraphSourceId(value: string): GraphSourceId {
  if (typeof value !== "string" || value.length === 0) {
    return invalidGraphIdentity("Graph source ID must be a nonempty string");
  }
  return value as GraphSourceId;
}

export function createGraphRecordRef(source: GraphSourceId, ordinal: number): GraphRecordRef {
  if (typeof source !== "string" || source.length === 0) {
    return invalidGraphIdentity("Graph source ID must be a nonempty string");
  }
  if (!Number.isSafeInteger(ordinal) || ordinal < 0) {
    return invalidGraphIdentity("Graph record ordinal must be a nonnegative safe integer");
  }

  const ref = Object.freeze({ source, ordinal }) as unknown as GraphRecordRef;
  authenticatedGraphRecordRefs.add(ref);
  return ref;
}

export function graphRecordRefsEqual(left: GraphRecordRef, right: GraphRecordRef): boolean {
  return (
    authenticatedGraphRecordRefs.has(left) &&
    authenticatedGraphRecordRefs.has(right) &&
    left.source === right.source &&
    left.ordinal === right.ordinal
  );
}

export function createNormalizedGraph(data: NormalizedGraphData): NormalizedGraph {
  const graph = Object.freeze({
    capture: data.capture,
    sources: data.sources,
    sessions: data.sessions,
    windows: data.windows,
    panes: data.panes,
    clients: data.clients,
    winlinks: data.winlinks,
    records: data.records,
  }) as unknown as NormalizedGraph;
  authenticatedNormalizedGraphs.add(graph);
  return graph;
}

export function isNormalizedGraph(value: unknown): value is NormalizedGraph {
  return typeof value === "object" && value !== null && authenticatedNormalizedGraphs.has(value);
}
