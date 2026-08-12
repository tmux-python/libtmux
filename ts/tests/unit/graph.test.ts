import { describe, expect, test } from "bun:test";

import {
  WHERE_FIELDS_V1,
  type WhereField,
  type WhereModel,
} from "../../src/_generated/where_fields.js";
import type { ConnectionAlias, DaemonEpoch } from "../../src/common.js";
import {
  createGraphRecordRef,
  createGraphSourceId,
  type CapturedRowSet,
  type GraphCapture,
  type GraphRecordRef,
  type NormalizedGraph,
} from "../../src/_internal/graph/model.js";
import { normalizeGraph } from "../../src/_internal/graph/normalize.js";
import {
  IncompleteProjectionError,
  SelectionProjectionBuilder,
  isSelectionProjection,
  type ProjectionDescriptor,
} from "../../src/_internal/graph/selection_projection.js";
import type { ListCommand } from "../../src/neo.js";
import { completeFormatRow, type MutableCompleteFormatRow } from "../support/graph_rows.js";

function capture(): GraphCapture {
  return {
    capabilityFingerprint: "graph-capability",
    connection: "graph-runtime" as ConnectionAlias,
    epoch: 7 as DaemonEpoch,
  };
}

function assertFrozenProjectionData(value: unknown, seen = new Set<object>()): void {
  if (typeof value === "function") throw new Error("function escaped projection data");
  if (typeof value !== "object" || value === null || seen.has(value)) return;
  if (value instanceof Map || value instanceof Promise || value instanceof Set) {
    throw new Error("mutable or executable object escaped projection data");
  }

  seen.add(value);
  expect(Object.isFrozen(value)).toBe(true);
  if (Array.isArray(value)) {
    expectExactOwnKeys(value, [
      ...Array.from({ length: value.length }, (_, index) => String(index)),
      "length",
    ]);
  }
  for (const key of Reflect.ownKeys(value)) {
    expect(typeof key).toBe("string");
    assertFrozenProjectionData(Reflect.get(value, key), seen);
  }
}

function expectExactOwnKeys(value: object, expected: readonly string[]): void {
  const keys = Reflect.ownKeys(value);
  if (!keys.every((key): key is string => typeof key === "string")) {
    throw new Error("symbol key escaped projection data");
  }
  expect(keys.toSorted()).toEqual([...expected].toSorted());
}

function source(
  id: string,
  listCommand: ListCommand,
  rows: readonly MutableCompleteFormatRow[],
): CapturedRowSet {
  return { listCommand, rows, source: createGraphSourceId(id) };
}

function recordRef(graph: NormalizedGraph, sourceId: string, ordinal: number): GraphRecordRef {
  const graphSource = graph.sources.find(({ id }) => id === sourceId);
  const ref = graphSource?.records[ordinal];
  if (ref === undefined) throw new Error(`missing test record ${sourceId}:${String(ordinal)}`);
  return ref;
}

function descriptors(
  overrides: Readonly<Partial<Record<WhereModel, ProjectionDescriptor>>> = {},
): Readonly<Record<WhereModel, ProjectionDescriptor>> {
  return {
    pane: overrides.pane ?? {
      fields: WHERE_FIELDS_V1.pane,
      model: "pane",
      relations: [],
    },
    session: overrides.session ?? {
      fields: WHERE_FIELDS_V1.session,
      model: "session",
      relations: [],
    },
    window: overrides.window ?? {
      fields: WHERE_FIELDS_V1.window,
      model: "window",
      relations: [],
    },
  };
}

function linkedWindowRows(): readonly MutableCompleteFormatRow[] {
  return [
    completeFormatRow({
      session_id: "$1",
      session_name: "one",
      window_active: "1",
      window_bigger: "raw-one",
      window_id: "@9",
      window_index: "1",
      window_name: "shared-first",
    }),
    completeFormatRow({
      session_id: "$2",
      session_name: "two",
      window_active: "0",
      window_bigger: "raw-two",
      window_id: "@9",
      window_index: "4",
      window_name: "shared-second",
    }),
  ];
}

describe("normalized entity and winlink graph", () => {
  test("normalizes one linked window into one entity and ordered contextual edges", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [source("windows", "list-windows", linkedWindowRows())],
    });

    expect(graph.windows).toHaveLength(1);
    expect(graph.sessions).toHaveLength(2);
    expect(graph.winlinks.map(({ ref }) => [ref.sessionId, ref.windowIndex, ref.windowId])).toEqual(
      [
        ["$1", "1", "@9"],
        ["$2", "4", "@9"],
      ],
    );
    expect(graph.records).toHaveLength(2);
    expect(graph.sources[0]?.records).toEqual(graph.records.map(({ ref }) => ref));
    expect(graph.windows[0]?.occurrences).toEqual(graph.records.map(({ ref }) => ref));
    expect(graph.records.map(({ scalars }) => scalars.window_name)).toEqual([
      "shared-first",
      "shared-second",
    ]);
  });

  test("keeps two indexes in one session and byte-identical occurrences distinct", () => {
    const repeated = completeFormatRow({
      session_id: "$1",
      window_id: "@9",
      window_index: "2",
      window_name: "same",
    });
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("windows", "list-windows", [
          repeated,
          completeFormatRow({ ...repeated, window_index: "8" }),
          completeFormatRow({ ...repeated }),
        ]),
      ],
    });

    expect(graph.windows).toHaveLength(1);
    expect(graph.winlinks).toHaveLength(2);
    expect(graph.records).toHaveLength(3);
    expect(graph.winlinks.map(({ ref }) => ref.windowIndex)).toEqual(["2", "8"]);
    expect(graph.winlinks[0]?.occurrences).toEqual([
      recordRef(graph, "windows", 0),
      recordRef(graph, "windows", 2),
    ]);
  });

  test("coalesces a pane identity while preserving linked contextual duplicates", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("panes", "list-panes", [
          completeFormatRow({
            pane_id: "%3",
            session_id: "$1",
            window_id: "@9",
            window_index: "2",
          }),
          completeFormatRow({
            pane_id: "%3",
            session_id: "$2",
            window_id: "@9",
            window_index: "5",
          }),
        ]),
      ],
    });

    expect(graph.panes).toHaveLength(1);
    expect(graph.sessions.map(({ ref }) => String(ref.id))).toEqual(["$1", "$2"]);
    expect(graph.windows.map(({ ref }) => String(ref.id))).toEqual(["@9"]);
    expect(graph.panes[0]?.occurrences).toHaveLength(2);
    expect(graph.sessions.map(({ occurrences }) => occurrences)).toEqual([
      [recordRef(graph, "panes", 0)],
      [recordRef(graph, "panes", 1)],
    ]);
    expect(graph.windows[0]?.occurrences).toEqual([
      recordRef(graph, "panes", 0),
      recordRef(graph, "panes", 1),
    ]);
    expect(graph.records.map(({ entity }) => entity.id)).toEqual(["%3", "%3"]);
    expect(graph.records.map(({ winlink }) => winlink?.windowIndex)).toEqual(["2", "5"]);
  });

  test("coalesces identities across sources without coalescing source membership", () => {
    const row = completeFormatRow({
      session_id: "$1",
      window_id: "@9",
      window_index: "2",
      window_name: "shared",
    });
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("listing", "list-windows", [row, completeFormatRow({ ...row })]),
        source("targeted", "list-windows", [completeFormatRow({ ...row })]),
      ],
    });

    expect(graph.windows).toHaveLength(1);
    expect(graph.winlinks).toHaveLength(1);
    expect(graph.records).toHaveLength(3);
    expect(graph.sources.map(({ records }) => records.length)).toEqual([2, 1]);
    expect(graph.windows[0]?.occurrences).toHaveLength(3);
  });

  test("rejects conflicting winlink ownership and malformed required topology", () => {
    expect(() =>
      normalizeGraph({
        capture: capture(),
        sources: [
          source("conflict", "list-windows", [
            completeFormatRow({ session_id: "$1", window_id: "@1", window_index: "2" }),
            completeFormatRow({ session_id: "$1", window_id: "@2", window_index: "2" }),
          ]),
        ],
      }),
    ).toThrow(/winlink/);

    const malformed: readonly [ListCommand, MutableCompleteFormatRow][] = [
      ["list-sessions", completeFormatRow({ session_id: "" })],
      ["list-sessions", completeFormatRow({ session_id: "@1" })],
      ["list-windows", completeFormatRow({ session_id: "$1", window_id: "@1" })],
      ["list-windows", completeFormatRow({ session_id: "@1", window_id: "@1", window_index: "0" })],
      ["list-windows", completeFormatRow({ session_id: "$1", window_id: "$1", window_index: "0" })],
      [
        "list-windows",
        completeFormatRow({ session_id: "$1", window_id: "@1", window_index: "-1" }),
      ],
      [
        "list-windows",
        completeFormatRow({ session_id: "$1", window_id: "@1", window_index: "01" }),
      ],
      [
        "list-windows",
        completeFormatRow({ session_id: "$1", window_id: "@1", window_index: "1.5" }),
      ],
      [
        "list-windows",
        completeFormatRow({
          session_id: "$1",
          window_id: "@1",
          window_index: String(Number.MAX_SAFE_INTEGER + 1),
        }),
      ],
      ["list-panes", completeFormatRow({ pane_id: "%1", session_id: "$1", window_id: "@1" })],
      [
        "list-panes",
        completeFormatRow({
          pane_id: "@1",
          session_id: "$1",
          window_id: "@1",
          window_index: "0",
        }),
      ],
      [
        "list-panes",
        completeFormatRow({
          pane_id: "%1",
          session_id: "@1",
          window_id: "@1",
          window_index: "0",
        }),
      ],
      [
        "list-panes",
        completeFormatRow({
          pane_id: "%1",
          session_id: "$1",
          window_id: "$1",
          window_index: "0",
        }),
      ],
      [
        "list-panes",
        completeFormatRow({
          pane_id: "%1",
          session_id: "$1",
          window_id: "@1",
          window_index: "01",
        }),
      ],
      ["list-clients", completeFormatRow({ client_name: "" })],
      ["list-clients", completeFormatRow({ client_name: "%1" })],
      ["list-sessions", completeFormatRow({ session_id: "$1", window_id: "not-a-window-id" })],
    ];
    for (const [listCommand, row] of malformed) {
      expect(() =>
        normalizeGraph({
          capture: capture(),
          sources: [source(`bad-${listCommand}`, listCommand, [row])],
        }),
      ).toThrow();
    }
  });

  test("accepts empty irrelevant identities and canonical window-index boundaries", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("sessions", "list-sessions", [
          completeFormatRow({
            pane_id: "",
            session_id: "$1",
            window_id: "",
            window_index: "",
          }),
        ]),
        source("windows", "list-windows", [
          completeFormatRow({ session_id: "$1", window_id: "@1", window_index: "0" }),
          completeFormatRow({
            session_id: "$1",
            window_id: "@2",
            window_index: String(Number.MAX_SAFE_INTEGER),
          }),
        ]),
      ],
    });

    expect(graph.sessions).toHaveLength(1);
    expect(graph.panes).toEqual([]);
    expect(graph.windows.map(({ ref }) => String(ref.id))).toEqual(["@1", "@2"]);
    expect(graph.winlinks.map(({ ref }) => ref.windowIndex)).toEqual([
      "0",
      String(Number.MAX_SAFE_INTEGER),
    ]);
  });

  test("normalizes clients with first-occurrence identity order and duplicate records", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("clients", "list-clients", [
          completeFormatRow({ client_name: "/dev/pts/2", client_tty: "two-first" }),
          completeFormatRow({ client_name: "/dev/pts/1", client_tty: "one" }),
          completeFormatRow({ client_name: "/dev/pts/2", client_tty: "two-second" }),
        ]),
      ],
    });

    expect(graph.clients.map(({ ref }) => ref.id)).toEqual(["/dev/pts/2", "/dev/pts/1"]);
    expect(graph.clients.map(({ occurrences }) => occurrences.length)).toEqual([2, 1]);
    expect(graph.records.map(({ entity }) => entity.id)).toEqual([
      "/dev/pts/2",
      "/dev/pts/1",
      "/dev/pts/2",
    ]);
    expect(graph.records.map(({ scalars }) => scalars.client_tty)).toEqual([
      "two-first",
      "one",
      "two-second",
    ]);
    expect(graph.winlinks).toEqual([]);
  });

  test("keeps identity records payload-free and orders them by first occurrence", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("windows", "list-windows", [
          completeFormatRow({ session_id: "$2", window_id: "@2", window_index: "8" }),
          completeFormatRow({ session_id: "$1", window_id: "@1", window_index: "3" }),
          completeFormatRow({ session_id: "$2", window_id: "@2", window_index: "8" }),
        ]),
      ],
    });

    expect(graph.sessions.map(({ ref }) => String(ref.id))).toEqual(["$2", "$1"]);
    expect(graph.windows.map(({ ref }) => String(ref.id))).toEqual(["@2", "@1"]);
    expect(graph.winlinks.map(({ ref }) => [ref.sessionId, ref.windowIndex])).toEqual([
      ["$2", "8"],
      ["$1", "3"],
    ]);
    for (const entity of [...graph.sessions, ...graph.windows, ...graph.clients, ...graph.panes]) {
      expect(Object.keys(entity)).toEqual(["ref", "occurrences"]);
      expect(entity).not.toHaveProperty("scalars");
    }
    for (const winlink of graph.winlinks) {
      expect(Object.keys(winlink)).toEqual(["ref", "occurrences"]);
      expect(winlink).not.toHaveProperty("scalars");
    }
  });

  test("allows occurrence scalar disagreement for one logical entity", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [source("windows", "list-windows", linkedWindowRows())],
    });

    expect(graph.windows).toHaveLength(1);
    expect(graph.records[0]?.scalars.window_name).toBe("shared-first");
    expect(graph.records[1]?.scalars.window_name).toBe("shared-second");
  });
});

describe("selection projection snapshots", () => {
  test("projects canonical scalar names and contextual window values", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [source("windows", "list-windows", linkedWindowRows())],
    });
    const builder = SelectionProjectionBuilder.create({
      descriptors: descriptors(),
      graph,
      source: createGraphSourceId("windows"),
    });
    expect(builder.state).toBe("collecting");
    const projection = builder.seal();
    const rootSource = graph.sources[0];
    if (rootSource === undefined) throw new Error("missing window root source");

    expect(builder.state).toBe("complete");
    expect(projection.members).toEqual(rootSource.records);
    expect(projection.records.map(({ scalars }) => scalars.name)).toEqual([
      "shared-first",
      "shared-second",
    ]);
    expect(projection.records.map(({ scalars }) => scalars.window_index)).toEqual(["1", "4"]);
    expect(projection.records.map(({ scalars }) => scalars.window_bigger)).toEqual([
      "raw-one",
      "raw-two",
    ]);
    expect(projection.records[0]?.scalars).not.toHaveProperty("window_name");
    expect(projection.records[0]?.scalars).not.toHaveProperty("session_name");
    expect(projection.records.map(({ entity }) => String(entity.id))).toEqual(["@9", "@9"]);
    expect(projection.records.map(({ winlink }) => winlink?.windowIndex)).toEqual(["1", "4"]);
    expect(projection.entities.filter(({ ref }) => ref.kind === "window")).toHaveLength(1);
    expect(projection.winlinks).toHaveLength(2);
    expect(Object.isFrozen(projection)).toBe(true);
    expect(Object.isFrozen(projection.records)).toBe(true);
    expect(Object.isFrozen(projection.records[0]?.scalars)).toBe(true);
    expect(projection.capture).not.toBe(graph.capture);
    expect(projection.members).not.toBe(graph.sources[0]?.records);
    expect(projection.records[0]).not.toBe(graph.records[0]);
    expect(projection.records[0]?.entity).not.toBe(graph.records[0]?.entity);
    expect(projection.records[0]?.winlink).not.toBe(graph.records[0]?.winlink);
    expect(projection.records[0]?.scalars).not.toBe(graph.records[0]?.scalars);
    expect(projection.entities).not.toBe(graph.windows);
    expect(projection.winlinks).not.toBe(graph.winlinks);
    expectExactOwnKeys(projection, ["capture", "entities", "winlinks", "records", "members"]);
    expectExactOwnKeys(projection.capture, ["connection", "epoch", "capabilityFingerprint"]);
    for (const [index, member] of projection.members.entries()) {
      expectExactOwnKeys(member, ["source", "ordinal"]);
      expect(member).not.toBe(graph.sources[0]?.records[index]);
    }
    for (const [index, record] of projection.records.entries()) {
      const graphRecord = graph.records[index];
      if (graphRecord === undefined) throw new Error("missing graph record");
      expectExactOwnKeys(record, ["ref", "model", "entity", "winlink", "scalars", "adjacency"]);
      expectExactOwnKeys(record.ref, ["source", "ordinal"]);
      expectExactOwnKeys(record.entity, ["connection", "epoch", "kind", "id"]);
      expectExactOwnKeys(
        record.scalars,
        WHERE_FIELDS_V1.window.map(({ wireName }) => wireName),
      );
      expect(record.ref).not.toBe(graphRecord.ref);
      expect(record.entity).not.toBe(graphRecord.entity);
      expect(record.winlink).not.toBe(graphRecord.winlink);
      if (record.winlink === null) throw new Error("missing projected winlink");
      expectExactOwnKeys(record.winlink, [
        "connection",
        "epoch",
        "kind",
        "sessionId",
        "windowId",
        "windowIndex",
      ]);
    }
    for (const [index, entity] of projection.entities.entries()) {
      const graphEntity = graph.windows[index];
      if (graphEntity === undefined) throw new Error("missing graph entity");
      expectExactOwnKeys(entity, ["ref", "occurrences"]);
      expectExactOwnKeys(entity.ref, ["connection", "epoch", "kind", "id"]);
      expect(entity).not.toBe(graphEntity);
      expect(entity.ref).not.toBe(graphEntity.ref);
      expect(entity.occurrences).not.toBe(graphEntity.occurrences);
      for (const [occurrenceIndex, occurrence] of entity.occurrences.entries()) {
        expectExactOwnKeys(occurrence, ["source", "ordinal"]);
        expect(occurrence).not.toBe(graphEntity.occurrences[occurrenceIndex]);
      }
    }
    for (const [index, winlink] of projection.winlinks.entries()) {
      const graphWinlink = graph.winlinks[index];
      if (graphWinlink === undefined) throw new Error("missing graph winlink");
      expectExactOwnKeys(winlink, ["ref", "occurrences"]);
      expectExactOwnKeys(winlink.ref, [
        "connection",
        "epoch",
        "kind",
        "sessionId",
        "windowId",
        "windowIndex",
      ]);
      expect(winlink).not.toBe(graphWinlink);
      expect(winlink.ref).not.toBe(graphWinlink.ref);
      expect(winlink.occurrences).not.toBe(graphWinlink.occurrences);
      for (const [occurrenceIndex, occurrence] of winlink.occurrences.entries()) {
        expectExactOwnKeys(occurrence, ["source", "ordinal"]);
        expect(occurrence).not.toBe(graphWinlink.occurrences[occurrenceIndex]);
      }
    }
    expect(isSelectionProjection(projection)).toBe(true);
    expect(isSelectionProjection({ ...projection })).toBe(false);
    expect(builder.seal()).toBe(projection);
    assertFrozenProjectionData(projection);
  });

  test("projects the exact generated wire keys and occurrence values for every model", () => {
    const sessionRow = completeFormatRow({
      config_files: "",
      line: "session-line",
      session_id: "$1",
      session_name: "session-name",
    });
    const windowRow = completeFormatRow({
      line: "window-line",
      session_id: "$1",
      window_bigger: "window-raw",
      window_id: "@1",
      window_index: "3",
      window_name: "window-name",
    });
    const paneRow = completeFormatRow({
      line: "pane-line",
      pane_id: "%1",
      pane_title: "pane-title",
      session_id: "$1",
      window_id: "@1",
      window_index: "3",
    });
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("sessions", "list-sessions", [sessionRow]),
        source("windows", "list-windows", [windowRow]),
        source("panes", "list-panes", [paneRow]),
      ],
    });
    const cases: readonly [WhereModel, string, MutableCompleteFormatRow][] = [
      ["session", "sessions", sessionRow],
      ["window", "windows", windowRow],
      ["pane", "panes", paneRow],
    ];

    for (const [model, sourceId, row] of cases) {
      const projection = SelectionProjectionBuilder.create({
        descriptors: descriptors(),
        graph,
        source: createGraphSourceId(sourceId),
      }).seal();
      const scalars = projection.records[0]?.scalars;
      const expected = Object.fromEntries(
        WHERE_FIELDS_V1[model].map(({ token, wireName }) => [wireName, row[token]]),
      );

      if (scalars === undefined) throw new Error("missing projected scalars");
      expectExactOwnKeys(
        scalars,
        WHERE_FIELDS_V1[model].map(({ wireName }) => wireName),
      );
      expect(scalars).toEqual(expected);
    }
  });

  test("retains only records, entities, and winlinks reachable from the root source", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("sessions", "list-sessions", [completeFormatRow({ session_id: "$1" })]),
        source("windows", "list-windows", [
          completeFormatRow({ session_id: "$2", window_id: "@2", window_index: "2" }),
        ]),
        source("panes", "list-panes", [
          completeFormatRow({
            pane_id: "%2",
            session_id: "$2",
            window_id: "@2",
            window_index: "2",
          }),
        ]),
      ],
    });
    const projection = SelectionProjectionBuilder.create({
      descriptors: descriptors(),
      graph,
      source: createGraphSourceId("sessions"),
    }).seal();

    expect(projection.records).toHaveLength(1);
    expect(projection.entities.map(({ ref }) => `${ref.kind}:${String(ref.id)}`)).toEqual([
      "session:$1",
    ]);
    expect(projection.winlinks).toEqual([]);
    expect(Object.keys(projection).sort()).toEqual([
      "capture",
      "entities",
      "members",
      "records",
      "winlinks",
    ]);
    expect(JSON.stringify(projection)).not.toContain("collecting");
    expect(JSON.stringify(projection)).not.toContain("descriptors");
  });

  test("prunes reachable identity occurrences that point to unrelated records", () => {
    const rootRow = completeFormatRow({
      session_id: "$1",
      window_id: "@9",
      window_index: "1",
    });
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("root", "list-windows", [rootRow]),
        source("unrelated", "list-windows", [
          completeFormatRow({ ...rootRow }),
          completeFormatRow({ session_id: "$2", window_id: "@9", window_index: "2" }),
        ]),
      ],
    });
    expect(graph.windows[0]?.occurrences).toHaveLength(3);
    expect(graph.winlinks[0]?.occurrences).toHaveLength(2);
    const projection = SelectionProjectionBuilder.create({
      descriptors: descriptors(),
      graph,
      source: createGraphSourceId("root"),
    }).seal();

    expect(projection.records).toHaveLength(1);
    expect(projection.entities).toHaveLength(1);
    expect(projection.entities[0]?.occurrences).toEqual(projection.members);
    expect(projection.winlinks).toHaveLength(1);
    expect(projection.winlinks[0]?.occurrences).toEqual(projection.members);
    expect(projection.entities[0]?.occurrences.some(({ source }) => source === "unrelated")).toBe(
      false,
    );
    expect(projection.winlinks[0]?.occurrences.some(({ source }) => source === "unrelated")).toBe(
      false,
    );
  });

  test("distinguishes missing hydration, successful empty relations, and failure", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [source("sessions", "list-sessions", [completeFormatRow({ session_id: "$1" })])],
    });
    const relationDescriptors = descriptors({
      session: {
        fields: WHERE_FIELDS_V1.session,
        model: "session",
        relations: [
          { cardinality: "one", name: "activeWindow", targetModel: "window" },
          { cardinality: "many", name: "windows", targetModel: "window" },
        ],
      },
    });
    const member = recordRef(graph, "sessions", 0);

    const incomplete = SelectionProjectionBuilder.create({
      descriptors: relationDescriptors,
      graph,
      source: createGraphSourceId("sessions"),
    });
    expect(() => incomplete.seal()).toThrow(IncompleteProjectionError);
    expect(incomplete.state).toBe("collecting");

    const empty = SelectionProjectionBuilder.create({
      descriptors: relationDescriptors,
      graph,
      source: createGraphSourceId("sessions"),
    });
    empty.materializeOne(member, "activeWindow", null);
    empty.materializeMany(member, "windows", []);
    const projection = empty.seal();
    expect(projection.records[0]?.adjacency).toEqual([
      {
        cardinality: "one",
        name: "activeWindow",
        target: null,
        targetModel: "window",
      },
      {
        cardinality: "many",
        name: "windows",
        targetModel: "window",
        targets: [],
      },
    ]);
    const [oneAdjacency, manyAdjacency] = projection.records[0]?.adjacency ?? [];
    if (oneAdjacency?.cardinality !== "one" || manyAdjacency?.cardinality !== "many") {
      throw new Error("missing empty relation adjacency");
    }
    expectExactOwnKeys(oneAdjacency, ["cardinality", "name", "targetModel", "target"]);
    expectExactOwnKeys(manyAdjacency, ["cardinality", "name", "targetModel", "targets"]);
    assertFrozenProjectionData(projection);
    expect(() => empty.materializeOne(member, "activeWindow", null)).toThrow(/complete/);
    expect(() => empty.materializeMany(member, "windows", [])).toThrow(/complete/);

    const failed = SelectionProjectionBuilder.create({
      descriptors: relationDescriptors,
      graph,
      source: createGraphSourceId("sessions"),
    });
    const cause = new Error("hydration failed");
    let abortThrew = false;
    try {
      failed.abort(cause);
    } catch (error) {
      abortThrew = true;
      expect(error).toBe(cause);
    }
    expect(abortThrew).toBe(true);
    expect(failed.state).toBe("failed");
    for (const action of [
      () => failed.seal(),
      () => failed.materializeOne(member, "activeWindow", null),
      () => failed.materializeMany(member, "windows", []),
    ]) {
      let actionThrew = false;
      try {
        action();
      } catch (error) {
        actionThrew = true;
        expect(error).toBe(cause);
      }
      expect(actionThrew).toBe(true);
    }
  });

  test("materializes nested cyclic adjacency and preserves duplicate target order", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("sessions", "list-sessions", [completeFormatRow({ session_id: "$1" })]),
        source("windows", "list-windows", [
          completeFormatRow({ session_id: "$1", window_id: "@1", window_index: "1" }),
          completeFormatRow({ session_id: "$1", window_id: "@2", window_index: "2" }),
        ]),
      ],
    });
    const relationDescriptors = descriptors({
      session: {
        fields: WHERE_FIELDS_V1.session,
        model: "session",
        relations: [{ cardinality: "many", name: "windows", targetModel: "window" }],
      },
      window: {
        fields: WHERE_FIELDS_V1.window,
        model: "window",
        relations: [{ cardinality: "one", name: "session", targetModel: "session" }],
      },
    });
    const session = recordRef(graph, "sessions", 0);
    const firstWindow = recordRef(graph, "windows", 0);
    const secondWindow = recordRef(graph, "windows", 1);
    const targets = [firstWindow, firstWindow, secondWindow];
    const builder = SelectionProjectionBuilder.create({
      descriptors: relationDescriptors,
      graph,
      source: createGraphSourceId("sessions"),
    });

    builder.materializeMany(session, "windows", targets);
    targets.reverse();
    expect(() => builder.seal()).toThrow(IncompleteProjectionError);
    builder.materializeOne(firstWindow, "session", session);
    builder.materializeOne(secondWindow, "session", session);
    const projection = builder.seal();

    expect(projection.records).toHaveLength(3);
    expect(projection.records[0]?.adjacency[0]).toMatchObject({
      cardinality: "many",
      targets: [firstWindow, firstWindow, secondWindow],
    });
    expect(projection.records[1]?.adjacency[0]).toMatchObject({
      cardinality: "one",
      target: session,
    });
    expect(projection.records[2]?.adjacency[0]).toMatchObject({
      cardinality: "one",
      target: session,
    });
    expect(Object.isFrozen(projection.records[0]?.adjacency)).toBe(true);
    const adjacency = projection.records[0]?.adjacency[0];
    if (adjacency?.cardinality !== "many") throw new Error("missing many adjacency");
    expectExactOwnKeys(adjacency, ["cardinality", "name", "targetModel", "targets"]);
    expect(Object.isFrozen(adjacency.targets)).toBe(true);
    expect(adjacency.targets).not.toBe(targets);
    for (const target of adjacency.targets) {
      expectExactOwnKeys(target, ["source", "ordinal"]);
      expect([session, firstWindow, secondWindow].includes(target)).toBe(false);
    }
    for (const record of projection.records.slice(1)) {
      const relation = record.adjacency[0];
      if (relation?.cardinality !== "one" || relation.target === null) {
        throw new Error("missing cyclic to-one adjacency");
      }
      expectExactOwnKeys(relation, ["cardinality", "name", "targetModel", "target"]);
      expectExactOwnKeys(relation.target, ["source", "ordinal"]);
      expect(relation.target).not.toBe(session);
    }
    assertFrozenProjectionData(projection);
  });

  test("requires one materialized slot for every duplicate-preserving root record", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("sessions", "list-sessions", [
          completeFormatRow({ session_id: "$1" }),
          completeFormatRow({ session_id: "$2" }),
        ]),
        source("windows", "list-windows", linkedWindowRows()),
      ],
    });
    const relationDescriptors = descriptors({
      window: {
        fields: WHERE_FIELDS_V1.window,
        model: "window",
        relations: [{ cardinality: "one", name: "session", targetModel: "session" }],
      },
    });
    const firstWindow = recordRef(graph, "windows", 0);
    const secondWindow = recordRef(graph, "windows", 1);
    const firstSession = recordRef(graph, "sessions", 0);
    const secondSession = recordRef(graph, "sessions", 1);
    const builder = SelectionProjectionBuilder.create({
      descriptors: relationDescriptors,
      graph,
      source: createGraphSourceId("windows"),
    });

    builder.materializeOne(firstWindow, "session", firstSession);
    expect(() => builder.seal()).toThrow(IncompleteProjectionError);
    builder.materializeOne(secondWindow, "session", secondSession);
    expect(builder.seal().members).toEqual([firstWindow, secondWindow]);
  });

  test("rejects invalid slots, kinds, cardinalities, and duplicate materialization", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("sessions", "list-sessions", [completeFormatRow({ session_id: "$1" })]),
        source("windows", "list-windows", [
          completeFormatRow({ session_id: "$1", window_id: "@1", window_index: "1" }),
        ]),
        source("panes", "list-panes", [
          completeFormatRow({
            pane_id: "%1",
            session_id: "$1",
            window_id: "@1",
            window_index: "1",
          }),
        ]),
      ],
    });
    const relationDescriptors = descriptors({
      session: {
        fields: WHERE_FIELDS_V1.session,
        model: "session",
        relations: [{ cardinality: "many", name: "windows", targetModel: "window" }],
      },
    });
    const session = recordRef(graph, "sessions", 0);
    const window = recordRef(graph, "windows", 0);
    const pane = recordRef(graph, "panes", 0);

    const wrongCardinality = SelectionProjectionBuilder.create({
      descriptors: relationDescriptors,
      graph,
      source: createGraphSourceId("sessions"),
    });
    expect(() => wrongCardinality.materializeOne(session, "windows", window)).toThrow(
      /cardinality/,
    );
    expect(() => wrongCardinality.materializeMany(session, "unknown", [window])).toThrow(
      /relation/,
    );
    expect(() => wrongCardinality.materializeMany(session, "windows", [pane])).toThrow(/model/);
    expect(() =>
      wrongCardinality.materializeMany(session, "windows", [
        createGraphRecordRef(createGraphSourceId("missing"), 0),
      ]),
    ).toThrow(/record/);
    expect(() => wrongCardinality.materializeMany(window, "windows", [])).toThrow(/reachable/);
    wrongCardinality.materializeMany(session, "windows", [window]);
    expect(wrongCardinality.seal().records[0]?.adjacency).toMatchObject([
      { cardinality: "many", name: "windows", targets: [window] },
    ]);

    const duplicate = SelectionProjectionBuilder.create({
      descriptors: relationDescriptors,
      graph,
      source: createGraphSourceId("sessions"),
    });
    duplicate.materializeMany(session, "windows", [window]);
    expect(() => duplicate.materializeMany(session, "windows", [window])).toThrow(/materialized/);
  });

  test("preserves slot and failure state across target-array reflection reentrancy", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("sessions", "list-sessions", [completeFormatRow({ session_id: "$1" })]),
        source("windows", "list-windows", [
          completeFormatRow({ session_id: "$1", window_id: "@1", window_index: "1" }),
          completeFormatRow({ session_id: "$1", window_id: "@2", window_index: "2" }),
        ]),
      ],
    });
    const relationDescriptors = descriptors({
      session: {
        fields: WHERE_FIELDS_V1.session,
        model: "session",
        relations: [{ cardinality: "many", name: "windows", targetModel: "window" }],
      },
    });
    const session = recordRef(graph, "sessions", 0);
    const firstWindow = recordRef(graph, "windows", 0);
    const secondWindow = recordRef(graph, "windows", 1);
    const builder = SelectionProjectionBuilder.create({
      descriptors: relationDescriptors,
      graph,
      source: createGraphSourceId("sessions"),
    });
    let reentered = false;
    const reentrantTargets = new Proxy([secondWindow], {
      getOwnPropertyDescriptor(target, key) {
        if (key === "0" && !reentered) {
          reentered = true;
          builder.materializeMany(session, "windows", [firstWindow]);
        }
        return Reflect.getOwnPropertyDescriptor(target, key);
      },
    });

    expect(() => builder.materializeMany(session, "windows", reentrantTargets)).toThrow(
      /materialized/,
    );
    expect(builder.seal().records[0]?.adjacency).toMatchObject([
      { cardinality: "many", name: "windows", targets: [firstWindow] },
    ]);

    const failed = SelectionProjectionBuilder.create({
      descriptors: relationDescriptors,
      graph,
      source: createGraphSourceId("sessions"),
    });
    const cause = new Error("reentrant abort");
    let abortObserved: unknown;
    let abortReentered = false;
    const abortingTargets = new Proxy([secondWindow], {
      getOwnPropertyDescriptor(target, key) {
        if (key === "0" && !abortReentered) {
          abortReentered = true;
          try {
            failed.abort(cause);
          } catch (error) {
            abortObserved = error;
          }
        }
        return Reflect.getOwnPropertyDescriptor(target, key);
      },
    });
    let outerObserved: unknown;
    try {
      failed.materializeMany(session, "windows", abortingTargets);
    } catch (error) {
      outerObserved = error;
    }

    expect(abortObserved).toBe(cause);
    expect(outerObserved).toBe(cause);
    expect(failed.state).toBe("failed");

    const directlyFailed = SelectionProjectionBuilder.create({
      descriptors: relationDescriptors,
      graph,
      source: createGraphSourceId("sessions"),
    });
    const directCause = new Error("uncaught reentrant abort");
    let directAbortReentered = false;
    const directlyAbortingTargets = new Proxy([secondWindow], {
      getOwnPropertyDescriptor(target, key) {
        if (key === "0" && !directAbortReentered) {
          directAbortReentered = true;
          directlyFailed.abort(directCause);
        }
        return Reflect.getOwnPropertyDescriptor(target, key);
      },
    });
    let directOuterObserved: unknown;
    try {
      directlyFailed.materializeMany(session, "windows", directlyAbortingTargets);
    } catch (error) {
      directOuterObserved = error;
    }
    expect(directOuterObserved).toBe(directCause);
    expect(directlyFailed.state).toBe("failed");
    for (const action of [
      () => directlyFailed.materializeOne(session, "windows", firstWindow),
      () => directlyFailed.materializeMany(session, "windows", [firstWindow]),
      () => directlyFailed.seal(),
    ]) {
      let laterObserved: unknown;
      try {
        action();
      } catch (error) {
        laterObserved = error;
      }
      expect(laterObserved).toBe(directCause);
    }
  });

  test("validates descriptor uniqueness and snapshots caller descriptor data", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("sessions", "list-sessions", [
          completeFormatRow({ session_id: "$1", session_name: "stable" }),
        ]),
      ],
    });
    const nameField = {
      domain: "string",
      token: "session_name",
      wireName: "name",
    } satisfies WhereField;
    const fields: WhereField[] = [nameField];
    const relations: { cardinality: "many"; name: string; targetModel: "window" }[] = [];
    const callerDescriptors = descriptors({
      session: { fields, model: "session", relations },
    });
    const builder = SelectionProjectionBuilder.create({
      descriptors: callerDescriptors,
      graph,
      source: createGraphSourceId("sessions"),
    });

    nameField.wireName = "changed";
    fields.push({ domain: "string", token: "session_id", wireName: "later" });
    relations.push({ cardinality: "many", name: "later", targetModel: "window" });
    const projection = builder.seal();
    expect(projection.records[0]?.scalars).toEqual({ name: "stable" });

    const canonicalNameField = {
      domain: "string",
      token: "session_name",
      wireName: "name",
    } as const;
    const duplicateTokenField = {
      domain: "string",
      token: "session_name",
      wireName: "otherName",
    } as const;
    const duplicateWireField = {
      domain: "string",
      token: "session_id",
      wireName: "name",
    } as const;
    const invalidDescriptors = [
      descriptors({
        session: {
          fields: [canonicalNameField, duplicateTokenField],
          model: "session",
          relations: [],
        },
      }),
      descriptors({
        session: {
          fields: [canonicalNameField, duplicateWireField],
          model: "session",
          relations: [],
        },
      }),
      descriptors({
        session: {
          fields: WHERE_FIELDS_V1.session,
          model: "session",
          relations: [
            { cardinality: "many", name: "same", targetModel: "window" },
            { cardinality: "one", name: "same", targetModel: "window" },
          ],
        },
      }),
    ];
    for (const invalid of invalidDescriptors) {
      expect(() =>
        SelectionProjectionBuilder.create({
          descriptors: invalid,
          graph,
          source: createGraphSourceId("sessions"),
        }),
      ).toThrow(/duplicate/);
    }
    expect(() =>
      SelectionProjectionBuilder.create({
        descriptors: descriptors({
          session: {
            fields: WHERE_FIELDS_V1.session,
            model: "window",
            relations: [],
          },
        }),
        graph,
        source: createGraphSourceId("sessions"),
      }),
    ).toThrow(/descriptor model/);
  });

  test("rejects projection input and descriptor keyset mutation during inspection", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [source("sessions", "list-sessions", [completeFormatRow({ session_id: "$1" })])],
    });
    const sourceId = createGraphSourceId("sessions");
    const mutateDuringInspection = <Value extends object>(value: Value): Value => {
      let mutated = false;
      return new Proxy(value, {
        getOwnPropertyDescriptor(target, key) {
          const descriptor = Reflect.getOwnPropertyDescriptor(target, key);
          if (!mutated) {
            mutated = true;
            Reflect.defineProperty(target, "unexpected", {
              configurable: true,
              enumerable: true,
              value: "injected",
              writable: true,
            });
          }
          return descriptor;
        },
      });
    };
    const input = {
      descriptors: descriptors(),
      graph,
      source: sourceId,
    };
    const mutatingDescriptor = mutateDuringInspection({
      fields: WHERE_FIELDS_V1.session,
      model: "session" as const,
      relations: [],
    });

    const observed = [
      () => SelectionProjectionBuilder.create(mutateDuringInspection(input)),
      () =>
        SelectionProjectionBuilder.create({
          descriptors: descriptors({ session: mutatingDescriptor }),
          graph,
          source: sourceId,
        }),
    ].map((action) => {
      try {
        action();
      } catch (error) {
        return error;
      }
      return undefined;
    });

    for (const error of observed) {
      expect(error).toBeInstanceOf(Error);
      expect(error).toMatchObject({ message: expect.stringContaining("invalid keys") });
    }
  });

  test("snapshots relation objects and resolves reconstructed record refs by value", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("sessions", "list-sessions", [completeFormatRow({ session_id: "$1" })]),
        source("windows", "list-windows", [
          completeFormatRow({ session_id: "$1", window_id: "@1", window_index: "1" }),
        ]),
      ],
    });
    const relation: {
      cardinality: "many" | "one";
      name: string;
      targetModel: WhereModel;
    } = { cardinality: "many", name: "windows", targetModel: "window" };
    const builder = SelectionProjectionBuilder.create({
      descriptors: descriptors({
        session: {
          fields: WHERE_FIELDS_V1.session,
          model: "session",
          relations: [relation],
        },
      }),
      graph,
      source: createGraphSourceId("sessions"),
    });
    relation.cardinality = "one";
    relation.name = "changed";
    relation.targetModel = "pane";
    const session = recordRef(graph, "sessions", 0);
    const window = recordRef(graph, "windows", 0);
    const reconstructedSession = createGraphRecordRef(session.source, session.ordinal);
    const reconstructedWindow = createGraphRecordRef(window.source, window.ordinal);

    builder.materializeMany(reconstructedSession, "windows", [reconstructedWindow]);
    const projection = builder.seal();
    expect(projection.records[0]?.adjacency).toEqual([
      {
        cardinality: "many",
        name: "windows",
        targetModel: "window",
        targets: [window],
      },
    ]);
    const projectedRelation = projection.records[0]?.adjacency[0];
    if (projectedRelation?.cardinality !== "many") throw new Error("missing relation");
    expect(projectedRelation.targets[0]).not.toBe(reconstructedWindow);
    expect(projection.members[0]).not.toBe(reconstructedSession);

    const oneBuilder = SelectionProjectionBuilder.create({
      descriptors: descriptors({
        session: {
          fields: WHERE_FIELDS_V1.session,
          model: "session",
          relations: [{ cardinality: "one", name: "activeWindow", targetModel: "window" }],
        },
      }),
      graph,
      source: createGraphSourceId("sessions"),
    });
    const reconstructedOneSource = createGraphRecordRef(session.source, session.ordinal);
    const reconstructedOneTarget = createGraphRecordRef(window.source, window.ordinal);

    oneBuilder.materializeOne(reconstructedOneSource, "activeWindow", reconstructedOneTarget);
    const oneProjection = oneBuilder.seal();
    expect(oneProjection.records[0]?.adjacency).toEqual([
      {
        cardinality: "one",
        name: "activeWindow",
        target: window,
        targetModel: "window",
      },
    ]);
    const projectedOneRelation = oneProjection.records[0]?.adjacency[0];
    if (projectedOneRelation?.cardinality !== "one") throw new Error("missing relation");
    expect(projectedOneRelation.target).not.toBe(reconstructedOneTarget);
    expect(oneProjection.members[0]).not.toBe(reconstructedOneSource);
  });

  test("rejects structurally forged graph values at the projection boundary", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [source("sessions", "list-sessions", [completeFormatRow({ session_id: "$1" })])],
    });
    const forged = { ...graph } as NormalizedGraph;

    expect(() =>
      SelectionProjectionBuilder.create({
        descriptors: descriptors(),
        graph: forged,
        source: createGraphSourceId("sessions"),
      }),
    ).toThrow(/authentic/);
  });

  test("keeps targeted placement separate from duplicate-preserving listing membership", () => {
    const [first, second] = linkedWindowRows();
    if (first === undefined || second === undefined) throw new Error("missing linked-window rows");
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("listing", "list-windows", [first, second]),
        source("targeted", "list-windows", [completeFormatRow({ ...second })]),
      ],
    });
    const listing = SelectionProjectionBuilder.create({
      descriptors: descriptors(),
      graph,
      source: createGraphSourceId("listing"),
    }).seal();
    const targeted = SelectionProjectionBuilder.create({
      descriptors: descriptors(),
      graph,
      source: createGraphSourceId("targeted"),
    }).seal();

    expect(listing.members).toHaveLength(2);
    expect(targeted.members).toHaveLength(1);
    expect(targeted.records[0]?.winlink?.windowIndex).toBe("4");
  });

  test("rejects client roots because no Client Where descriptor exists", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        source("clients", "list-clients", [completeFormatRow({ client_name: "/dev/pts/1" })]),
      ],
    });

    expect(() =>
      SelectionProjectionBuilder.create({
        descriptors: descriptors(),
        graph,
        source: createGraphSourceId("clients"),
      }),
    ).toThrow(/client/);
  });
});
