import type {
  ConnectionAlias,
  DaemonEpoch,
  PaneId,
  PaneRef,
  SessionId,
  SessionRef,
  WindowId,
  WindowRef,
} from "../../src/common.js";
import {
  createLogicalRef,
  createWinlinkRef,
  type SerializedLogicalRef,
  type WinlinkRef,
} from "../../src/_internal/graph/refs.js";
import {
  createGraphRecordRef,
  createGraphSourceId,
  type GraphRecordRef,
  type GraphSourceId,
  type NormalizedGraph,
} from "../../src/_internal/graph/model.js";
import {
  SelectionProjectionBuilder,
  type ProjectionAdjacency,
  type ProjectionBuilderState,
  type SelectionProjection,
} from "../../src/_internal/graph/selection_projection.js";

import type { Equal, Expect } from "./assert.js";

declare const connection: ConnectionAlias;
declare const epoch: DaemonEpoch;
declare const paneId: PaneId;
declare const sessionId: SessionId;
declare const windowId: WindowId;
declare const sourceId: GraphSourceId;
declare const recordRef: GraphRecordRef;
declare const graph: NormalizedGraph;
declare const projection: SelectionProjection;
declare const builder: SelectionProjectionBuilder;
declare const serialized: SerializedLogicalRef;
declare const adjacency: ProjectionAdjacency;
declare const replacementGraphSources: NormalizedGraph["sources"];
declare const replacementGraphSessions: NormalizedGraph["sessions"];
declare const replacementGraphWindows: NormalizedGraph["windows"];
declare const replacementGraphPanes: NormalizedGraph["panes"];
declare const replacementGraphClients: NormalizedGraph["clients"];
declare const replacementGraphWinlinks: NormalizedGraph["winlinks"];
declare const replacementGraphRecords: NormalizedGraph["records"];
declare const replacementSourceRecords: NormalizedGraph["sources"][number]["records"];
declare const replacementEntityOccurrences: NormalizedGraph["sessions"][number]["occurrences"];
declare const replacementWinlinkOccurrences: NormalizedGraph["winlinks"][number]["occurrences"];
declare const replacementProjectionMembers: SelectionProjection["members"];
declare const replacementProjectionEntities: SelectionProjection["entities"];
declare const replacementProjectionWinlinks: SelectionProjection["winlinks"];
declare const replacementProjectionRecords: SelectionProjection["records"];
declare const replacementProjectedEntityOccurrences: SelectionProjection["entities"][number]["occurrences"];
declare const replacementProjectedWinlinkOccurrences: SelectionProjection["winlinks"][number]["occurrences"];
declare const replacementProjectionAdjacency: SelectionProjection["records"][number]["adjacency"];
declare const replacementManyTargets: Extract<
  ProjectionAdjacency,
  { readonly cardinality: "many" }
>["targets"];
declare const replacementOneTarget: Extract<
  ProjectionAdjacency,
  { readonly cardinality: "one" }
>["target"];

const sessionRef = createLogicalRef({ connection, epoch, id: sessionId, kind: "session" });
const windowRef = createLogicalRef({ connection, epoch, id: windowId, kind: "window" });
const paneRef = createLogicalRef({ connection, epoch, id: paneId, kind: "pane" });
const winlinkRef = createWinlinkRef({
  connection,
  epoch,
  sessionId,
  windowId,
  windowIndex: "1",
});
const nextRecord = createGraphRecordRef(sourceId, 1);
void createGraphSourceId("source");
void sessionRef.id;
void windowRef.id;
void paneRef.id;
void winlinkRef.windowIndex;
void nextRecord.ordinal;
void graph.records;
void projection.members;
void builder.state;

// @ts-expect-error Existing Window brands cannot be supplied as Session IDs.
createLogicalRef({ connection, epoch, id: windowId, kind: "session" });
// @ts-expect-error Existing Session brands cannot be supplied as Window IDs.
createLogicalRef({ connection, epoch, id: sessionId, kind: "window" });
// @ts-expect-error Existing Pane brands cannot be supplied as Session IDs.
createWinlinkRef({ connection, epoch, sessionId: paneId, windowId, windowIndex: "1" });
// @ts-expect-error Existing Session brands cannot be supplied as Window IDs.
createWinlinkRef({ connection, epoch, sessionId, windowId: sessionId, windowIndex: "1" });
// @ts-expect-error Graph source identities are nominal.
const plainSource: GraphSourceId = "source";
void plainSource;
// @ts-expect-error Graph record references are readonly.
recordRef.ordinal = 2;
// @ts-expect-error Graph record references are nominal, not matching plain records.
const structuralRecord: GraphRecordRef = { ordinal: 0, source: sourceId };
void structuralRecord;
// @ts-expect-error Logical references are readonly.
sessionRef.id = sessionId;
// @ts-expect-error Winlink references are readonly.
winlinkRef.windowIndex = "2";
// @ts-expect-error Serialized logical references are readonly.
serialized.connection = connection;
// @ts-expect-error Normalized graph source properties are readonly.
graph.sources = replacementGraphSources;
// @ts-expect-error Normalized graph source arrays are readonly.
graph.sources.push(graph.sources[0]!);
// @ts-expect-error Normalized graph session properties are readonly.
graph.sessions = replacementGraphSessions;
// @ts-expect-error Normalized graph session arrays are readonly.
graph.sessions.push(graph.sessions[0]!);
// @ts-expect-error Normalized graph window properties are readonly.
graph.windows = replacementGraphWindows;
// @ts-expect-error Normalized graph window arrays are readonly.
graph.windows.push(graph.windows[0]!);
// @ts-expect-error Normalized graph pane properties are readonly.
graph.panes = replacementGraphPanes;
// @ts-expect-error Normalized graph pane arrays are readonly.
graph.panes.push(graph.panes[0]!);
// @ts-expect-error Normalized graph client properties are readonly.
graph.clients = replacementGraphClients;
// @ts-expect-error Normalized graph client arrays are readonly.
graph.clients.push(graph.clients[0]!);
// @ts-expect-error Normalized graph winlink properties are readonly.
graph.winlinks = replacementGraphWinlinks;
// @ts-expect-error Normalized graph winlink arrays are readonly.
graph.winlinks.push(graph.winlinks[0]!);
// @ts-expect-error Normalized graph record properties are readonly.
graph.records = replacementGraphRecords;
// @ts-expect-error Normalized graph arrays are readonly.
graph.records.push(graph.records[0]!);
// @ts-expect-error Normalized capture stamps are deeply readonly.
graph.capture.epoch = epoch;
// @ts-expect-error Source membership arrays are readonly.
graph.sources[0]!.records.push(recordRef);
// @ts-expect-error Source membership properties are readonly.
graph.sources[0]!.records = replacementSourceRecords;
// @ts-expect-error Entity occurrence arrays are readonly.
graph.sessions[0]!.occurrences.push(recordRef);
// @ts-expect-error Entity occurrence properties are readonly.
graph.sessions[0]!.occurrences = replacementEntityOccurrences;
// @ts-expect-error Winlink occurrence arrays are readonly.
graph.winlinks[0]!.occurrences.push(recordRef);
// @ts-expect-error Winlink occurrence properties are readonly.
graph.winlinks[0]!.occurrences = replacementWinlinkOccurrences;
// @ts-expect-error Captured scalar rows are readonly.
graph.records[0]!.scalars.session_id = "$2";
// @ts-expect-error Projection membership is readonly.
projection.members = replacementProjectionMembers;
// @ts-expect-error Projection membership arrays are readonly.
projection.members.push(recordRef);
// @ts-expect-error Projection capture stamps are deeply readonly.
projection.capture.epoch = epoch;
// @ts-expect-error Projection entity arrays are readonly.
projection.entities.push(projection.entities[0]!);
// @ts-expect-error Projection entity properties are readonly.
projection.entities = replacementProjectionEntities;
// @ts-expect-error Projected entity occurrence arrays are readonly.
projection.entities[0]!.occurrences.push(recordRef);
// @ts-expect-error Projected entity occurrence properties are readonly.
projection.entities[0]!.occurrences = replacementProjectedEntityOccurrences;
// @ts-expect-error Projection winlink arrays are readonly.
projection.winlinks.push(projection.winlinks[0]!);
// @ts-expect-error Projection winlink properties are readonly.
projection.winlinks = replacementProjectionWinlinks;
// @ts-expect-error Projected winlink occurrence arrays are readonly.
projection.winlinks[0]!.occurrences.push(recordRef);
// @ts-expect-error Projected winlink occurrence properties are readonly.
projection.winlinks[0]!.occurrences = replacementProjectedWinlinkOccurrences;
// @ts-expect-error Projection record arrays are readonly.
projection.records.push(projection.records[0]!);
// @ts-expect-error Projection record properties are readonly.
projection.records = replacementProjectionRecords;
// @ts-expect-error Projection records are readonly.
projection.records[0]!.scalars.name = "changed";
// @ts-expect-error Projection adjacency arrays are readonly.
projection.records[0]!.adjacency.push(adjacency);
// @ts-expect-error Projection adjacency properties are readonly.
projection.records[0]!.adjacency = replacementProjectionAdjacency;
if (adjacency.cardinality === "many") {
  // @ts-expect-error To-many adjacency targets are readonly.
  adjacency.targets.push(recordRef);
  // @ts-expect-error To-many adjacency target properties are readonly.
  adjacency.targets = replacementManyTargets;
} else {
  // @ts-expect-error To-one adjacency targets are readonly.
  adjacency.target = replacementOneTarget;
}
// @ts-expect-error NormalizedGraph is nominal rather than a structural placeholder.
const structuralGraph: NormalizedGraph = {
  capture: graph.capture,
  clients: graph.clients,
  panes: graph.panes,
  records: graph.records,
  sessions: graph.sessions,
  sources: graph.sources,
  windows: graph.windows,
  winlinks: graph.winlinks,
};
void structuralGraph;
// @ts-expect-error SelectionProjection is nominal rather than a structural placeholder.
const structuralProjection: SelectionProjection = {
  capture: projection.capture,
  entities: projection.entities,
  members: projection.members,
  records: projection.records,
  winlinks: projection.winlinks,
};
void structuralProjection;

type _SerializedKeys = Expect<
  Equal<keyof SerializedLogicalRef, "connection" | "epoch" | "id" | "kind">
>;
type _SerializedSession = Expect<
  Equal<
    Extract<SerializedLogicalRef, { readonly kind: "session" }>,
    {
      readonly connection: string;
      readonly epoch: number;
      readonly id: string;
      readonly kind: "session";
    }
  >
>;
type _SerializedWindow = Expect<
  Equal<
    Extract<SerializedLogicalRef, { readonly kind: "window" }>,
    {
      readonly connection: string;
      readonly epoch: number;
      readonly id: string;
      readonly kind: "window";
    }
  >
>;
type _SerializedPane = Expect<
  Equal<
    Extract<SerializedLogicalRef, { readonly kind: "pane" }>,
    {
      readonly connection: string;
      readonly epoch: number;
      readonly id: string;
      readonly kind: "pane";
    }
  >
>;
type _WinlinkRef = Expect<
  Equal<
    WinlinkRef,
    {
      readonly connection: ConnectionAlias;
      readonly epoch: DaemonEpoch;
      readonly kind: "winlink";
      readonly sessionId: SessionId;
      readonly windowId: WindowId;
      readonly windowIndex: string;
    }
  >
>;
type _RecordRefKeys = Expect<Equal<keyof GraphRecordRef, "ordinal" | "source">>;
type _SessionRefReturn = Expect<Equal<typeof sessionRef, SessionRef>>;
type _WindowRefReturn = Expect<Equal<typeof windowRef, WindowRef>>;
type _PaneRefReturn = Expect<Equal<typeof paneRef, PaneRef>>;
type _BuilderState = Expect<Equal<ProjectionBuilderState, "collecting" | "complete" | "failed">>;
type _ProjectionMembers = Expect<Equal<SelectionProjection["members"], readonly GraphRecordRef[]>>;
type _ManyTargets = Expect<
  Equal<
    Extract<ProjectionAdjacency, { readonly cardinality: "many" }>["targets"],
    readonly GraphRecordRef[]
  >
>;
type _MaterializeOne = Expect<
  Equal<
    SelectionProjectionBuilder["materializeOne"],
    (source: GraphRecordRef, relation: string, target: GraphRecordRef | null) => void
  >
>;
type _MaterializeMany = Expect<
  Equal<
    SelectionProjectionBuilder["materializeMany"],
    (source: GraphRecordRef, relation: string, targets: readonly GraphRecordRef[]) => void
  >
>;
type _Abort = Expect<Equal<SelectionProjectionBuilder["abort"], (cause: unknown) => never>>;
type _Seal = Expect<Equal<SelectionProjectionBuilder["seal"], () => SelectionProjection>>;

export type {
  _Abort,
  _BuilderState,
  _ManyTargets,
  _MaterializeMany,
  _MaterializeOne,
  _PaneRefReturn,
  _ProjectionMembers,
  _RecordRefKeys,
  _Seal,
  _SessionRefReturn,
  _SerializedKeys,
  _SerializedPane,
  _SerializedSession,
  _SerializedWindow,
  _WindowRefReturn,
  _WinlinkRef,
};
