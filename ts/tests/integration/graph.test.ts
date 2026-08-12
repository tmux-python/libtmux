import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "bun:test";

import { WHERE_FIELDS_V1, type WhereModel } from "../../src/_generated/where_fields.js";
import type { ConnectionAlias, DaemonEpoch } from "../../src/common.js";
import { executeGuardedFetch, executeGuardedList } from "../../src/_internal/codec/guard_codec.js";
import {
  createGraphSourceId,
  type CapturedRowSet,
  type GraphCapture,
  type GraphRecord,
  type GraphRecordRef,
  type NormalizedGraph,
} from "../../src/_internal/graph/model.js";
import { normalizeGraph } from "../../src/_internal/graph/normalize.js";
import {
  SelectionProjectionBuilder,
  type ProjectionDescriptor,
} from "../../src/_internal/graph/selection_projection.js";
import { LazyCapabilityBinding } from "../../src/_internal/runtime/capabilities.js";
import { TmuxConnection } from "../../src/_internal/runtime/connection.js";
import {
  prepareRunRoot,
  reapOwnedRunRoot,
  runWithCleanup,
} from "../../src/_internal/test/run_root.js";
import { TestServer } from "../../src/_internal/test/test_server.js";
import { NodeSpawnTransport } from "../../src/_internal/transport/node_spawn_transport.js";
import type { CommandTransport } from "../../src/_internal/transport/types.js";

interface QueryHarness {
  readonly capabilities: LazyCapabilityBinding;
  readonly connection: TmuxConnection;
  readonly transport: CommandTransport;
}

function queryHarness(server: TestServer): QueryHarness {
  const rawTransport = new NodeSpawnTransport({ terminationGraceMs: 100 });
  const transport: CommandTransport = {
    async execute(request) {
      await server.assertControllerCurrent();
      return rawTransport.execute(request);
    },
  };
  const connection = new TmuxConnection({
    environment: server.controllerEnvironment,
    executable: server.tmuxExecutable,
    socketPath: server.socketPath,
  });
  const capabilities = new LazyCapabilityBinding({
    connection,
    connectionAlias: server.logicalSocketName as ConnectionAlias,
    getDaemonEpoch: () => 1 as DaemonEpoch,
    transport,
  });
  return { capabilities, connection, transport };
}

async function withTestServer(
  prefix: string,
  body: (server: TestServer) => Promise<void>,
): Promise<void> {
  const parent = await mkdtemp(join(tmpdir(), prefix));
  const publishedRoot = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = publishedRoot ?? join(parent, "run, root");
  if (publishedRoot === undefined) await prepareRunRoot(runRoot);
  let cleanupComplete = false;
  try {
    await runWithCleanup(
      async () => {
        const server = await TestServer.create({ runRoot, sessionName: `${prefix}session` });
        await runWithCleanup(
          () => body(server),
          () => server.dispose(),
        );
      },
      async () => {
        if (publishedRoot === undefined) await reapOwnedRunRoot(runRoot);
        cleanupComplete = true;
      },
    );
  } finally {
    if (cleanupComplete) await rm(parent, { force: true, recursive: true });
  }
}

function descriptors(): Readonly<Record<WhereModel, ProjectionDescriptor>> {
  return {
    pane: {
      fields: WHERE_FIELDS_V1.pane,
      model: "pane",
      relations: [{ cardinality: "one", name: "containingWindow", targetModel: "window" }],
    },
    session: {
      fields: WHERE_FIELDS_V1.session,
      model: "session",
      relations: [],
    },
    window: {
      fields: WHERE_FIELDS_V1.window,
      model: "window",
      relations: [
        { cardinality: "one", name: "containingSession", targetModel: "session" },
        { cardinality: "many", name: "containedPanes", targetModel: "pane" },
      ],
    },
  };
}

function graphRecord(graph: NormalizedGraph, ref: GraphRecordRef): GraphRecord {
  const record = graph.records.find(
    ({ ref: candidate }) => candidate.source === ref.source && candidate.ordinal === ref.ordinal,
  );
  if (record === undefined) throw new Error("missing graph record in integration fixture");
  return record;
}

function sourceRecords(graph: NormalizedGraph, id: string): readonly GraphRecordRef[] {
  const source = graph.sources.find(({ id: candidate }) => candidate === id);
  if (source === undefined) throw new Error(`missing graph source ${id}`);
  return source.records;
}

function sameWinlink(left: GraphRecord, right: GraphRecord): boolean {
  return (
    left.winlink !== null &&
    right.winlink !== null &&
    left.winlink.sessionId === right.winlink.sessionId &&
    left.winlink.windowIndex === right.winlink.windowIndex
  );
}

describe("real normalized graph hydration", () => {
  test("captures linked contextual duplicates and remains stable after unlink", async () => {
    await withTestServer("ltx6-graph-", async (server) => {
      const harness = queryHarness(server);
      const identity = await server.executeText([
        "display-message",
        "-p",
        "-t",
        server.sessionId,
        "#{window_id}\t#{window_index}",
      ]);
      const [windowId, initialIndex] = identity.stdout[0]?.split("\t") ?? [];
      if (windowId === undefined || initialIndex === undefined) {
        throw new Error("tmux did not return the initial window identity");
      }
      const parsedInitialIndex = Number.parseInt(initialIndex, 10);
      if (!Number.isSafeInteger(parsedInitialIndex) || parsedInitialIndex < 0) {
        throw new Error("tmux returned a noncanonical initial window index");
      }
      const linkedIndex = String(parsedInitialIndex + 9);
      await server.executeText([
        "link-window",
        "-s",
        windowId,
        "-t",
        `${server.sessionId}:${linkedIndex}`,
      ]);

      const [capabilities, sessions, windows, panes, targeted] = await Promise.all([
        harness.capabilities.bind(),
        executeGuardedList({ ...harness, listCommand: "list-sessions" }),
        executeGuardedList({ ...harness, listCommand: "list-windows", listExtraArgs: ["-a"] }),
        executeGuardedList({ ...harness, listCommand: "list-panes", listExtraArgs: ["-a"] }),
        executeGuardedFetch({
          ...harness,
          identityField: "window_id",
          identityValue: windowId,
          listCommand: "list-windows",
          listExtraArgs: ["-t", windowId],
        }),
      ]);
      const capture: GraphCapture = {
        capabilityFingerprint: capabilities.fingerprint,
        connection: capabilities.connectionAlias,
        epoch: capabilities.daemonEpoch,
      };
      const graph = normalizeGraph({
        capture,
        sources: [
          {
            listCommand: "list-sessions",
            rows: sessions,
            source: createGraphSourceId("sessions"),
          },
          {
            listCommand: "list-windows",
            rows: windows,
            source: createGraphSourceId("windows"),
          },
          {
            listCommand: "list-panes",
            rows: panes,
            source: createGraphSourceId("panes"),
          },
        ] satisfies readonly CapturedRowSet[],
      });
      const windowRecords = sourceRecords(graph, "windows").filter(
        (ref) => graphRecord(graph, ref).entity.id === windowId,
      );
      const paneRecords = sourceRecords(graph, "panes").filter(
        (ref) => graphRecord(graph, ref).winlink?.windowId === windowId,
      );
      const sessionRecord = sourceRecords(graph, "sessions")[0];
      if (sessionRecord === undefined) throw new Error("missing real session record");

      expect(graph.windows.filter(({ ref }) => ref.id === windowId)).toHaveLength(1);
      expect(graph.winlinks.filter(({ ref }) => ref.windowId === windowId)).toHaveLength(2);
      expect(windowRecords).toHaveLength(2);
      expect(paneRecords).toHaveLength(2);
      expect(windowRecords.map((ref) => graphRecord(graph, ref).winlink?.windowIndex)).toEqual([
        initialIndex,
        linkedIndex,
      ]);
      const linkedPaneId = panes.find(({ window_id }) => window_id === windowId)?.pane_id;
      if (linkedPaneId === null || linkedPaneId === undefined) {
        throw new Error("missing real linked pane identity");
      }
      expect(paneRecords.map((ref) => String(graphRecord(graph, ref).entity.id))).toEqual([
        linkedPaneId,
        linkedPaneId,
      ]);

      const builder = SelectionProjectionBuilder.create({
        descriptors: descriptors(),
        graph,
        source: createGraphSourceId("windows"),
      });
      for (const windowRecord of windowRecords) {
        builder.materializeOne(windowRecord, "containingSession", sessionRecord);
        const contextualPanes = paneRecords.filter((paneRecord) =>
          sameWinlink(graphRecord(graph, windowRecord), graphRecord(graph, paneRecord)),
        );
        builder.materializeMany(windowRecord, "containedPanes", contextualPanes);
        for (const paneRecord of contextualPanes) {
          builder.materializeOne(paneRecord, "containingWindow", windowRecord);
        }
      }
      const projection = builder.seal();

      expect(projection.members).toEqual(sourceRecords(graph, "windows"));
      expect(projection.records.filter(({ model }) => model === "window")).toHaveLength(2);
      expect(projection.records.filter(({ model }) => model === "pane")).toHaveLength(2);
      expect(Object.isFrozen(projection.records[0]?.scalars)).toBe(true);

      const targetedGraph = normalizeGraph({
        capture,
        sources: [
          {
            listCommand: "list-windows",
            rows: [targeted],
            source: createGraphSourceId("targeted"),
          },
        ],
      });
      expect(targetedGraph.records).toHaveLength(1);
      const targetedWindowIndex = targeted.window_index;
      if (targetedWindowIndex === null) throw new Error("missing targeted window index");
      expect(targetedGraph.records[0]?.winlink?.windowIndex).toBe(targetedWindowIndex);
      expect(windowRecords.map((ref) => graphRecord(graph, ref).winlink?.windowIndex)).toContain(
        targetedWindowIndex,
      );

      await server.executeText(["unlink-window", "-t", `${server.sessionId}:${linkedIndex}`]);
      const afterUnlink = await executeGuardedList({
        ...harness,
        listCommand: "list-windows",
        listExtraArgs: ["-a"],
      });
      expect(afterUnlink.filter(({ window_id }) => window_id === windowId)).toHaveLength(1);
      expect(graph.winlinks.filter(({ ref }) => ref.windowId === windowId)).toHaveLength(2);
      expect(projection.records.filter(({ model }) => model === "window")).toHaveLength(2);
      expect(projection.records.map(({ winlink }) => winlink?.windowIndex)).toContain(linkedIndex);
    });
  }, 20_000);
});
