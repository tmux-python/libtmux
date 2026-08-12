import { WHERE_FIELDS_V1, type WhereModel } from "../../src/_generated/where_fields.js";
import type { ConnectionAlias, DaemonEpoch } from "../../src/common.js";
import { Client } from "../../src/client.js";
import type { CompleteFormatRow } from "../../src/_internal/codec/schemas.js";
import {
  createGraphSourceId,
  type CapturedRowSet,
  type GraphRecordRef,
  type NormalizedGraph,
} from "../../src/_internal/graph/model.js";
import { normalizeGraph } from "../../src/_internal/graph/normalize.js";
import {
  SelectionProjectionBuilder,
  type ProjectionDescriptor,
  type SelectionProjection,
} from "../../src/_internal/graph/selection_projection.js";
import {
  materializeClientRecord,
  materializeProjectionMembers,
} from "../../src/_internal/graph/materialize.js";
import { TmuxConnection } from "../../src/_internal/runtime/connection.js";
import {
  createRuntimeContext,
  createServerWithRuntime,
  type RuntimeContext,
} from "../../src/_internal/runtime/context.js";
import type {
  CommandRequest,
  CommandTransport,
  RawCommandResult,
} from "../../src/_internal/transport/types.js";
import type { ListCommand } from "../../src/_internal/codec/format_types.js";
import { Pane } from "../../src/pane.js";
import { Session } from "../../src/session.js";
import { Window } from "../../src/window.js";
import { completeFormatRow, type MutableCompleteFormatRow } from "./graph_rows.js";

const encoder = new TextEncoder();
let runtimeOrdinal = 0;

export interface RecordingTransport extends CommandTransport {
  readonly requests: CommandRequest[];
}

export interface ProjectedHarness<Model extends Session | Window | Pane> {
  readonly graph: NormalizedGraph;
  readonly projection: SelectionProjection;
  readonly runtime: RuntimeContext;
  readonly transport: RecordingTransport;
  readonly values: readonly Model[];
}

export interface RichProjectedHarness {
  readonly panes: ProjectedHarness<Pane>;
  readonly sessions: ProjectedHarness<Session>;
  readonly windows: ProjectedHarness<Window>;
}

export interface ClientHarness {
  readonly graph: NormalizedGraph;
  readonly runtime: RuntimeContext;
  readonly transport: RecordingTransport;
  readonly values: readonly Client[];
}

export interface SessionProvenanceHarness {
  readonly projection: SelectionProjection;
  readonly twinValues: readonly Session[];
  readonly values: readonly Session[];
}

function resultFor(request: CommandRequest): RawCommandResult {
  return {
    cmd: Object.freeze([request.executable, ...request.args]),
    returncode: 0,
    signal: null,
    stderr: new Uint8Array(),
    stdout: encoder.encode("3.7b\n"),
  };
}

function recordingTransport(): RecordingTransport {
  const requests: CommandRequest[] = [];
  return {
    requests,
    async execute(request) {
      requests.push(request);
      return resultFor(request);
    },
  };
}

function fixtureRuntime(): {
  readonly runtime: RuntimeContext;
  readonly transport: RecordingTransport;
} {
  runtimeOrdinal += 1;
  const transport = recordingTransport();
  const runtime = createRuntimeContext({
    connection: new TmuxConnection({ executable: "tmux", socketName: "selection-fixture" }),
    connectionAlias: `selection-fixture-${String(runtimeOrdinal)}` as ConnectionAlias,
    daemonEpoch: 0 as DaemonEpoch,
    transport,
  });
  return { runtime, transport };
}

function source(
  id: string,
  listCommand: ListCommand,
  rows: readonly MutableCompleteFormatRow[],
): CapturedRowSet {
  return { listCommand, rows, source: createGraphSourceId(id) };
}

async function graphFor(
  runtime: RuntimeContext,
  sources: readonly CapturedRowSet[],
): Promise<NormalizedGraph> {
  const capabilities = await runtime.capabilities.bind();
  return normalizeGraph({
    capture: {
      capabilityFingerprint: capabilities.fingerprint,
      connection: runtime.connectionAlias,
      epoch: runtime.daemonEpoch,
    },
    sources,
  });
}

const descriptors: Readonly<Record<WhereModel, ProjectionDescriptor>> = {
  pane: {
    fields: WHERE_FIELDS_V1.pane,
    model: "pane",
    relations: [
      { cardinality: "one", name: "window", targetModel: "window" },
      { cardinality: "one", name: "session", targetModel: "session" },
    ],
  },
  session: {
    fields: WHERE_FIELDS_V1.session,
    model: "session",
    relations: [
      { cardinality: "many", name: "windows", targetModel: "window" },
      { cardinality: "many", name: "panes", targetModel: "pane" },
      { cardinality: "one", name: "activeWindow", targetModel: "window" },
      { cardinality: "one", name: "activePane", targetModel: "pane" },
    ],
  },
  window: {
    fields: WHERE_FIELDS_V1.window,
    model: "window",
    relations: [
      { cardinality: "one", name: "session", targetModel: "session" },
      { cardinality: "many", name: "linkedSessions", targetModel: "session" },
      { cardinality: "many", name: "panes", targetModel: "pane" },
      { cardinality: "one", name: "activePane", targetModel: "pane" },
    ],
  },
};

function sourceRefs(graph: NormalizedGraph, sourceId: string): readonly GraphRecordRef[] {
  const refs = graph.sources.find(({ id }) => id === sourceId)?.records;
  if (refs === undefined) throw new Error(`missing graph source ${sourceId}`);
  return refs;
}

function refAt(refs: readonly GraphRecordRef[], index: number): GraphRecordRef {
  const ref = refs[index];
  if (ref === undefined) throw new Error(`missing graph record ${String(index)}`);
  return ref;
}

function builderFor(graph: NormalizedGraph, rootSource: string): SelectionProjectionBuilder {
  return SelectionProjectionBuilder.create({
    descriptors,
    graph,
    source: createGraphSourceId(rootSource),
  });
}

function hydrateEmptySession(builder: SelectionProjectionBuilder, session: GraphRecordRef): void {
  builder.materializeMany(session, "windows", []);
  builder.materializeMany(session, "panes", []);
  builder.materializeOne(session, "activeWindow", null);
  builder.materializeOne(session, "activePane", null);
}

function requireSessions(values: readonly (Session | Window | Pane)[]): readonly Session[] {
  if (!values.every((value) => value instanceof Session)) {
    throw new Error("fixture materialized a non-Session member");
  }
  return values;
}

function requireWindows(values: readonly (Session | Window | Pane)[]): readonly Window[] {
  if (!values.every((value) => value instanceof Window)) {
    throw new Error("fixture materialized a non-Window member");
  }
  return values;
}

function requirePanes(values: readonly (Session | Window | Pane)[]): readonly Pane[] {
  if (!values.every((value) => value instanceof Pane)) {
    throw new Error("fixture materialized a non-Pane member");
  }
  return values;
}

export async function createSessionHarness(
  names: readonly (string | null)[],
): Promise<ProjectedHarness<Session>> {
  const { runtime, transport } = fixtureRuntime();
  const graph = await graphFor(runtime, [
    source(
      "sessions-root",
      "list-sessions",
      names.map((name, index) =>
        completeFormatRow({ session_id: `$${String(index + 1)}`, session_name: name }),
      ),
    ),
  ]);
  const builder = builderFor(graph, "sessions-root");
  for (const session of sourceRefs(graph, "sessions-root")) hydrateEmptySession(builder, session);
  const projection = builder.seal();
  const values = requireSessions(
    await materializeProjectionMembers(createServerWithRuntime(runtime), projection, graph),
  );
  return { graph, projection, runtime, transport, values };
}

export function createIncompleteSessionProjection(
  graph: NormalizedGraph,
): SelectionProjectionBuilder {
  return builderFor(graph, "sessions-root");
}

function richSources(): readonly CapturedRowSet[] {
  return [
    source("sessions-rich", "list-sessions", [
      completeFormatRow({ session_id: "$1", session_name: "one" }),
      completeFormatRow({ session_id: "$2", session_name: "two" }),
      completeFormatRow({ session_id: "$3", session_name: "empty" }),
    ]),
    source("windows-rich", "list-windows", [
      completeFormatRow({
        session_id: "$1",
        window_active: "1",
        window_id: "@1",
        window_index: "0",
        window_name: "editor",
      }),
      completeFormatRow({
        session_id: "$2",
        window_active: "1",
        window_id: "@2",
        window_index: "0",
        window_name: "logs",
      }),
    ]),
    source("panes-rich", "list-panes", [
      completeFormatRow({
        pane_active: "1",
        pane_id: "%1",
        pane_title: "shell",
        session_id: "$1",
        window_id: "@1",
        window_index: "0",
      }),
      completeFormatRow({
        pane_active: "0",
        pane_id: "%2",
        pane_title: "tests",
        session_id: "$1",
        window_id: "@1",
        window_index: "0",
      }),
      completeFormatRow({
        pane_active: "1",
        pane_id: "%3",
        pane_title: "tail",
        session_id: "$2",
        window_id: "@2",
        window_index: "0",
      }),
    ]),
  ];
}

function hydrateRichProjection(
  builder: SelectionProjectionBuilder,
  graph: NormalizedGraph,
  rootSource: string,
): void {
  const sessions = sourceRefs(graph, "sessions-rich");
  const windows = sourceRefs(graph, "windows-rich");
  const panes = sourceRefs(graph, "panes-rich");
  const sessionOne = refAt(sessions, 0);
  const sessionTwo = refAt(sessions, 1);
  const sessionEmpty = refAt(sessions, 2);
  const windowEditor = refAt(windows, 0);
  const windowLogs = refAt(windows, 1);
  const paneShell = refAt(panes, 0);
  const paneTests = refAt(panes, 1);
  const paneTail = refAt(panes, 2);

  const hydrateSessions = (includeEmpty: boolean): void => {
    builder.materializeMany(sessionOne, "windows", [windowEditor]);
    builder.materializeMany(sessionOne, "panes", [paneShell, paneTests]);
    builder.materializeOne(sessionOne, "activeWindow", windowEditor);
    builder.materializeOne(sessionOne, "activePane", paneShell);
    builder.materializeMany(sessionTwo, "windows", [windowLogs]);
    builder.materializeMany(sessionTwo, "panes", [paneTail]);
    builder.materializeOne(sessionTwo, "activeWindow", windowLogs);
    builder.materializeOne(sessionTwo, "activePane", paneTail);
    if (includeEmpty) hydrateEmptySession(builder, sessionEmpty);
  };
  const hydrateWindows = (): void => {
    builder.materializeOne(windowEditor, "session", sessionOne);
    builder.materializeMany(windowEditor, "linkedSessions", [sessionOne]);
    builder.materializeMany(windowEditor, "panes", [paneShell, paneTests]);
    builder.materializeOne(windowEditor, "activePane", paneShell);
    builder.materializeOne(windowLogs, "session", sessionTwo);
    builder.materializeMany(windowLogs, "linkedSessions", [sessionTwo]);
    builder.materializeMany(windowLogs, "panes", [paneTail]);
    builder.materializeOne(windowLogs, "activePane", paneTail);
  };
  const hydratePanes = (): void => {
    builder.materializeOne(paneShell, "window", windowEditor);
    builder.materializeOne(paneShell, "session", sessionOne);
    builder.materializeOne(paneTests, "window", windowEditor);
    builder.materializeOne(paneTests, "session", sessionOne);
    builder.materializeOne(paneTail, "window", windowLogs);
    builder.materializeOne(paneTail, "session", sessionTwo);
  };

  if (rootSource === "sessions-rich") {
    hydrateSessions(true);
    hydrateWindows();
    hydratePanes();
    return;
  }
  if (rootSource === "windows-rich") {
    hydrateWindows();
    hydrateSessions(false);
    hydratePanes();
    return;
  }
  if (rootSource === "panes-rich") {
    hydratePanes();
    hydrateWindows();
    hydrateSessions(false);
    return;
  }
  throw new Error(`unsupported rich projection source: ${rootSource}`);
}

async function projectedHarness<Model extends Session | Window | Pane>(
  runtime: RuntimeContext,
  transport: RecordingTransport,
  graph: NormalizedGraph,
  rootSource: string,
  requireModel: (values: readonly (Session | Window | Pane)[]) => readonly Model[],
): Promise<ProjectedHarness<Model>> {
  const builder = builderFor(graph, rootSource);
  hydrateRichProjection(builder, graph, rootSource);
  const projection = builder.seal();
  const values = requireModel(
    await materializeProjectionMembers(createServerWithRuntime(runtime), projection, graph),
  );
  return { graph, projection, runtime, transport, values };
}

export async function createRichProjectedHarness(): Promise<RichProjectedHarness> {
  const { runtime, transport } = fixtureRuntime();
  const graph = await graphFor(runtime, richSources());
  return {
    panes: await projectedHarness(runtime, transport, graph, "panes-rich", requirePanes),
    sessions: await projectedHarness(runtime, transport, graph, "sessions-rich", requireSessions),
    windows: await projectedHarness(runtime, transport, graph, "windows-rich", requireWindows),
  };
}

export async function createWindowAssociationHarness(): Promise<ProjectedHarness<Window>> {
  const { runtime, transport } = fixtureRuntime();
  const graph = await graphFor(runtime, [
    source("sessions-association", "list-sessions", [
      completeFormatRow({ session_id: "$1", session_name: "one" }),
      completeFormatRow({ session_id: "$2", session_name: "two" }),
    ]),
    source("windows-association", "list-windows", [
      completeFormatRow({
        session_id: "$1",
        window_id: "@7",
        window_index: "0",
        window_name: "shared",
      }),
      completeFormatRow({
        session_id: "$2",
        window_id: "@7",
        window_index: "0",
        window_name: "shared",
      }),
    ]),
  ]);
  const sessions = sourceRefs(graph, "sessions-association");
  const windows = sourceRefs(graph, "windows-association");
  const sessionOne = refAt(sessions, 0);
  const sessionTwo = refAt(sessions, 1);
  const windowOne = refAt(windows, 0);
  const windowTwo = refAt(windows, 1);
  const builder = builderFor(graph, "windows-association");

  builder.materializeOne(windowOne, "session", sessionOne);
  builder.materializeMany(windowOne, "linkedSessions", [sessionOne, sessionTwo]);
  builder.materializeMany(windowOne, "panes", []);
  builder.materializeOne(windowOne, "activePane", null);
  builder.materializeOne(windowTwo, "session", sessionTwo);
  builder.materializeMany(windowTwo, "linkedSessions", [sessionOne, sessionTwo]);
  builder.materializeMany(windowTwo, "panes", []);
  builder.materializeOne(windowTwo, "activePane", null);
  builder.materializeMany(sessionOne, "windows", [windowOne]);
  builder.materializeMany(sessionOne, "panes", []);
  builder.materializeOne(sessionOne, "activeWindow", windowOne);
  builder.materializeOne(sessionOne, "activePane", null);
  builder.materializeMany(sessionTwo, "windows", [windowTwo]);
  builder.materializeMany(sessionTwo, "panes", []);
  builder.materializeOne(sessionTwo, "activeWindow", windowTwo);
  builder.materializeOne(sessionTwo, "activePane", null);

  const projection = builder.seal();
  const values = requireWindows(
    await materializeProjectionMembers(createServerWithRuntime(runtime), projection, graph),
  );
  return { graph, projection, runtime, transport, values };
}

export async function createSessionProvenanceHarness(): Promise<SessionProvenanceHarness> {
  const { runtime } = fixtureRuntime();
  const provenanceSources = (): readonly CapturedRowSet[] => {
    const row = completeFormatRow({ session_id: "$1", session_name: "same" });
    return [
      source("sessions-provenance", "list-sessions", [row, row]),
      source("windows-provenance", "list-windows", [
        completeFormatRow({
          session_id: "$1",
          window_id: "@1",
          window_index: "0",
          window_name: "first",
        }),
        completeFormatRow({
          session_id: "$1",
          window_id: "@2",
          window_index: "1",
          window_name: "second",
        }),
      ]),
    ];
  };
  const graph = await graphFor(runtime, provenanceSources());
  const twinGraph = await graphFor(runtime, provenanceSources());
  const materialize = async (
    sourceGraph: NormalizedGraph,
  ): Promise<{
    readonly projection: SelectionProjection;
    readonly values: readonly Session[];
  }> => {
    const builder = builderFor(sourceGraph, "sessions-provenance");
    const sessions = sourceRefs(sourceGraph, "sessions-provenance");
    const windows = sourceRefs(sourceGraph, "windows-provenance");
    const firstSession = refAt(sessions, 0);
    const secondSession = refAt(sessions, 1);
    const firstWindow = refAt(windows, 0);
    const secondWindow = refAt(windows, 1);
    builder.materializeMany(firstSession, "windows", [firstWindow]);
    builder.materializeMany(firstSession, "panes", []);
    builder.materializeOne(firstSession, "activeWindow", firstWindow);
    builder.materializeOne(firstSession, "activePane", null);
    builder.materializeMany(secondSession, "windows", [secondWindow]);
    builder.materializeMany(secondSession, "panes", []);
    builder.materializeOne(secondSession, "activeWindow", secondWindow);
    builder.materializeOne(secondSession, "activePane", null);
    builder.materializeOne(firstWindow, "session", firstSession);
    builder.materializeMany(firstWindow, "linkedSessions", [firstSession]);
    builder.materializeMany(firstWindow, "panes", []);
    builder.materializeOne(firstWindow, "activePane", null);
    builder.materializeOne(secondWindow, "session", secondSession);
    builder.materializeMany(secondWindow, "linkedSessions", [secondSession]);
    builder.materializeMany(secondWindow, "panes", []);
    builder.materializeOne(secondWindow, "activePane", null);
    const projection = builder.seal();
    const values = requireSessions(
      await materializeProjectionMembers(createServerWithRuntime(runtime), projection, sourceGraph),
    );
    return { projection, values };
  };
  const primary = await materialize(graph);
  const twin = await materialize(twinGraph);
  return {
    projection: primary.projection,
    twinValues: twin.values,
    values: primary.values,
  };
}

export async function createClientHarness(names: readonly string[]): Promise<ClientHarness> {
  const { runtime, transport } = fixtureRuntime();
  const graph = await graphFor(runtime, [
    source(
      "clients-root",
      "list-clients",
      names.map((name) => completeFormatRow({ client_name: name })),
    ),
  ]);
  const server = createServerWithRuntime(runtime);
  const values = await Promise.all(
    sourceRefs(graph, "clients-root").map((ref) => materializeClientRecord(server, graph, ref)),
  );
  if (!values.every((value) => value instanceof Client)) {
    throw new Error("fixture materialized a non-Client member");
  }
  return { graph, runtime, transport, values: Object.freeze(values) };
}

export function forgedCompleteRow(overrides: Partial<CompleteFormatRow>): CompleteFormatRow {
  return Object.assign(completeFormatRow(), overrides);
}
