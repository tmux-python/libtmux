import { describe, expect, test } from "bun:test";

import { FORMAT_FIELD_TOKENS } from "../../src/_generated/format_fields.js";
import type { ConnectionAlias, DaemonEpoch } from "../../src/common.js";
import { QueryValidationError } from "../../src/exc.js";
import type { CompleteFormatRow } from "../../src/_internal/codec/schemas.js";
import {
  createGraphRecordRef,
  createGraphSourceId,
  graphRecordRefsEqual,
  type CapturedRowSet,
  type GraphRecordRef,
  type GraphSourceId,
} from "../../src/_internal/graph/model.js";
import { normalizeGraph } from "../../src/_internal/graph/normalize.js";
import { completeFormatRow } from "../support/graph_rows.js";

function capture(): {
  capabilityFingerprint: string;
  connection: ConnectionAlias;
  epoch: DaemonEpoch;
} {
  return {
    capabilityFingerprint: "capability-a",
    connection: "graph-a" as ConnectionAlias,
    epoch: 2 as DaemonEpoch,
  };
}

function expectInvalidQuery(action: () => unknown, rawError?: unknown): void {
  let observed: unknown;
  try {
    action();
  } catch (error) {
    observed = error;
  }
  if (rawError !== undefined) expect(observed).not.toBe(rawError);
  expect(observed).toBeInstanceOf(QueryValidationError);
  expect(observed).toMatchObject({ code: "invalid-query" });
}

function assertFrozenData(value: unknown, seen = new Set<object>()): void {
  if (typeof value === "function") throw new Error("function escaped frozen graph data");
  if (typeof value !== "object" || value === null || seen.has(value)) return;
  if (value instanceof Map || value instanceof Promise || value instanceof Set) {
    throw new Error("mutable or executable object escaped frozen graph data");
  }

  seen.add(value);
  expect(Object.isFrozen(value)).toBe(true);
  for (const key of Reflect.ownKeys(value)) {
    expect(typeof key).toBe("string");
    assertFrozenData(Reflect.get(value, key), seen);
  }
}

describe("graph snapshot identities", () => {
  test("constructs nominal frozen source and occurrence refs", () => {
    const source = createGraphSourceId("sessions-main");
    const first = createGraphRecordRef(source, 0);
    const same = createGraphRecordRef(source, 0);
    const second = createGraphRecordRef(source, 1);
    const otherSource = createGraphRecordRef(createGraphSourceId("other"), 0);
    const independentlyTypedSource = "not-previously-minted" as GraphSourceId;
    const independent = createGraphRecordRef(independentlyTypedSource, 0);
    const forged = Object.freeze({ ordinal: 0, source }) as unknown as GraphRecordRef;

    expect(Object.keys(first)).toEqual(["source", "ordinal"]);
    expect(Object.isFrozen(first)).toBe(true);
    expect(graphRecordRefsEqual(first, same)).toBe(true);
    expect(graphRecordRefsEqual(first, second)).toBe(false);
    expect(graphRecordRefsEqual(first, otherSource)).toBe(false);
    expect(independent).toMatchObject({ ordinal: 0, source: "not-previously-minted" });
    expect(graphRecordRefsEqual(first, forged)).toBe(false);
    expectInvalidQuery(() => createGraphSourceId(""));
    expectInvalidQuery(() => createGraphSourceId(1 as never));
    expectInvalidQuery(() => createGraphRecordRef("" as GraphSourceId, 0));
    expectInvalidQuery(() => createGraphRecordRef(1 as never, 0));
    expectInvalidQuery(() => createGraphRecordRef(source, -1));
    expectInvalidQuery(() => createGraphRecordRef(source, 0.5));
    expectInvalidQuery(() => createGraphRecordRef(source, Number.MAX_SAFE_INTEGER + 1));
  });
});

describe("frozen normalized snapshots", () => {
  test("copies all 178 fields and preserves null separately from empty text", () => {
    const row = completeFormatRow({
      session_group: "",
      session_id: "$1",
      session_name: "before",
    });
    const rows = [row];
    const source = {
      listCommand: "list-sessions",
      rows,
      source: createGraphSourceId("sessions"),
    } satisfies CapturedRowSet;
    const captureInput = capture();
    const graph = normalizeGraph({ capture: captureInput, sources: [source] });

    row.session_name = "after";
    row.session_group = "changed";
    rows.length = 0;
    captureInput.capabilityFingerprint = "changed";

    const scalars = graph.records[0]?.scalars;
    expect(Object.keys(scalars ?? {})).toEqual([...FORMAT_FIELD_TOKENS]);
    expect(scalars?.session_name).toBe("before");
    expect(scalars?.session_group).toBe("");
    expect(scalars?.pane_id).toBeNull();
    expect(graph.capture.capabilityFingerprint).toBe("capability-a");
    expect(graph.sources[0]?.records).toHaveLength(1);
    assertFrozenData(graph);
  });

  test("reconstructs allowlisted data without retaining injected resources", () => {
    const row = completeFormatRow({ session_id: "$1", session_name: "safe" });
    const captureInput = Object.assign(capture(), {
      environment: { TOKEN: "private" },
      executable: "/private/tmux",
      logger: { info() {} },
      mutableMap: new Map([["unsafe", true]]),
      mutableSet: new Set(["unsafe"]),
      pending: Promise.resolve("unsafe"),
      socketPath: "/private/socket",
      transport: { execute() {} },
    });
    const sourceInput = Object.assign(
      {
        listCommand: "list-sessions" as const,
        rows: [row],
        source: createGraphSourceId("safe-source"),
      },
      { logger: { info() {} }, transport: { execute() {} } },
    );

    const graph = normalizeGraph({
      capture: captureInput,
      sources: [sourceInput],
    });
    const serialized = JSON.stringify(graph);

    expect(Object.keys(graph.capture)).toEqual(["connection", "epoch", "capabilityFingerprint"]);
    expect(Object.keys(graph.sources[0] ?? {})).toEqual(["id", "listCommand", "records"]);
    expect(Object.keys(graph.records[0]?.scalars ?? {})).toEqual([...FORMAT_FIELD_TOKENS]);
    expect(serialized).not.toContain("private");
    expect(serialized).not.toContain("transport");
    expect(serialized).not.toContain("logger");
    assertFrozenData(graph);
  });

  test("rejects incomplete, over-specified, and non-string scalar rows", () => {
    const normalize = (row: CompleteFormatRow): unknown =>
      normalizeGraph({
        capture: capture(),
        sources: [
          {
            listCommand: "list-sessions",
            rows: [row],
            source: createGraphSourceId("invalid-row"),
          },
        ],
      });
    const missing = completeFormatRow({ session_id: "$1" });
    Reflect.deleteProperty(missing, "pane_z");
    const extra = Object.assign(completeFormatRow({ session_id: "$1" }), {
      unexpected: "value",
    });
    const wrongType = completeFormatRow({ session_id: "$1" });
    Reflect.set(wrongType, "pane_z", 3);

    expect(() => normalize(missing as CompleteFormatRow)).toThrow();
    expect(() => normalize(extra)).toThrow();
    expect(() => normalize(wrongType)).toThrow();
  });

  test("rejects row keyset mutation during descriptor inspection without invoking getters", () => {
    const target = completeFormatRow({ session_id: "$1", session_name: "stable" });
    let getterCalls = 0;
    let mutated = false;
    const row = new Proxy(target, {
      getOwnPropertyDescriptor(inner, key) {
        const descriptor = Reflect.getOwnPropertyDescriptor(inner, key);
        if (!mutated) {
          mutated = true;
          Object.defineProperty(inner, "unexpected", {
            configurable: true,
            enumerable: true,
            get() {
              getterCalls += 1;
              return "sensitive";
            },
          });
        }
        return descriptor;
      },
    });

    expectInvalidQuery(() =>
      normalizeGraph({
        capture: capture(),
        sources: [
          {
            listCommand: "list-sessions",
            rows: [row],
            source: createGraphSourceId("mutating-row"),
          },
        ],
      }),
    );
    expect(getterCalls).toBe(0);
  });

  test("snapshots arrays without invoking iterators or leaking reflection failures", () => {
    const validRow = completeFormatRow({ session_id: "$1" });
    const validSource = {
      listCommand: "list-sessions" as const,
      rows: [validRow],
      source: createGraphSourceId("sessions"),
    };
    const revokedSources = Proxy.revocable([validSource], {});
    const revokedRows = Proxy.revocable([validRow], {});
    revokedSources.revoke();
    revokedRows.revoke();

    expectInvalidQuery(() => normalizeGraph({ capture: capture(), sources: revokedSources.proxy }));
    expectInvalidQuery(() =>
      normalizeGraph({
        capture: capture(),
        sources: [{ ...validSource, rows: revokedRows.proxy }],
      }),
    );

    const sourceReflectionSentinel = new Error("source descriptor trap escaped");
    const rowReflectionSentinel = new Error("row descriptor trap escaped");
    const trappedSources = new Proxy([validSource], {
      getOwnPropertyDescriptor(_target, key) {
        if (key === "0") throw sourceReflectionSentinel;
        return Reflect.getOwnPropertyDescriptor(_target, key);
      },
    });
    const trappedRows = new Proxy([validRow], {
      getOwnPropertyDescriptor(_target, key) {
        if (key === "0") throw rowReflectionSentinel;
        return Reflect.getOwnPropertyDescriptor(_target, key);
      },
    });

    expectInvalidQuery(
      () => normalizeGraph({ capture: capture(), sources: trappedSources }),
      sourceReflectionSentinel,
    );
    expectInvalidQuery(
      () =>
        normalizeGraph({
          capture: capture(),
          sources: [{ ...validSource, rows: trappedRows }],
        }),
      rowReflectionSentinel,
    );

    const sourceIteratorSentinel = new Error("source iterator invoked");
    const rowIteratorSentinel = new Error("row iterator invoked");
    let sourceIteratorReads = 0;
    let rowIteratorReads = 0;
    const iterableSources = [validSource];
    const iterableRows = [validRow];
    Object.defineProperty(iterableSources, Symbol.iterator, {
      configurable: true,
      get() {
        sourceIteratorReads += 1;
        throw sourceIteratorSentinel;
      },
    });
    Object.defineProperty(iterableRows, Symbol.iterator, {
      configurable: true,
      get() {
        rowIteratorReads += 1;
        throw rowIteratorSentinel;
      },
    });

    const sourceGraph = normalizeGraph({ capture: capture(), sources: iterableSources });
    const rowGraph = normalizeGraph({
      capture: capture(),
      sources: [{ ...validSource, rows: iterableRows }],
    });
    expect(sourceGraph.records).toHaveLength(1);
    expect(rowGraph.records).toHaveLength(1);
    expect(sourceIteratorReads).toBe(0);
    expect(rowIteratorReads).toBe(0);

    const sourceAccessorSentinel = new Error("source accessor invoked");
    const rowAccessorSentinel = new Error("row accessor invoked");
    const accessorSources = [validSource];
    const accessorRows = [validRow];
    Object.defineProperty(accessorSources, "0", {
      configurable: true,
      enumerable: true,
      get() {
        throw sourceAccessorSentinel;
      },
    });
    Object.defineProperty(accessorRows, "0", {
      configurable: true,
      enumerable: true,
      get() {
        throw rowAccessorSentinel;
      },
    });
    expectInvalidQuery(
      () => normalizeGraph({ capture: capture(), sources: accessorSources }),
      sourceAccessorSentinel,
    );
    expectInvalidQuery(
      () =>
        normalizeGraph({
          capture: capture(),
          sources: [{ ...validSource, rows: accessorRows }],
        }),
      rowAccessorSentinel,
    );

    const sparseSources: CapturedRowSet[] = [];
    const sparseRows: CompleteFormatRow[] = [];
    sparseSources.length = 1;
    sparseRows.length = 1;
    expectInvalidQuery(() => normalizeGraph({ capture: capture(), sources: sparseSources }));
    expectInvalidQuery(() =>
      normalizeGraph({
        capture: capture(),
        sources: [{ ...validSource, rows: sparseRows }],
      }),
    );
  });

  test("copies scalar rows safely past inherited nonwritable fields", () => {
    const row = completeFormatRow({ session_id: "$1", session_name: "safe" });
    const original = Object.getOwnPropertyDescriptor(Object.prototype, "session_name");
    try {
      Object.defineProperty(Object.prototype, "session_name", {
        configurable: true,
        enumerable: false,
        value: "polluted",
        writable: false,
      });
      const graph = normalizeGraph({
        capture: capture(),
        sources: [
          {
            listCommand: "list-sessions",
            rows: [row],
            source: createGraphSourceId("prototype-safe"),
          },
        ],
      });

      expect(graph.records[0]?.scalars.session_name).toBe("safe");
      expect(Object.hasOwn(graph.records[0]?.scalars ?? {}, "session_name")).toBe(true);
    } finally {
      if (original === undefined) {
        Reflect.deleteProperty(Object.prototype, "session_name");
      } else {
        Object.defineProperty(Object.prototype, "session_name", original);
      }
    }
  });

  test("does not expose scalar values to inherited accessors", () => {
    const sensitiveValue = "sensitive-session-name";
    const row = completeFormatRow({ session_id: "$1", session_name: sensitiveValue });
    const original = Object.getOwnPropertyDescriptor(Object.prototype, "session_name");
    let getterCalls = 0;
    const setterValues: unknown[] = [];
    try {
      Object.defineProperty(Object.prototype, "session_name", {
        configurable: true,
        enumerable: false,
        get() {
          getterCalls += 1;
          return "polluted";
        },
        set(value: unknown) {
          setterValues.push(value);
        },
      });
      const graph = normalizeGraph({
        capture: capture(),
        sources: [
          {
            listCommand: "list-sessions",
            rows: [row],
            source: createGraphSourceId("accessor-safe"),
          },
        ],
      });
      const scalars = graph.records[0]?.scalars;

      expect(getterCalls).toBe(0);
      expect(setterValues).toEqual([]);
      expect(scalars?.session_name).toBe(sensitiveValue);
      expect(Object.hasOwn(scalars ?? {}, "session_name")).toBe(true);
      expect(Object.isFrozen(scalars)).toBe(true);
    } finally {
      if (original === undefined) {
        Reflect.deleteProperty(Object.prototype, "session_name");
      } else {
        Object.defineProperty(Object.prototype, "session_name", original);
      }
    }
  });

  test("returns a complete frozen empty capture", () => {
    const graph = normalizeGraph({ capture: capture(), sources: [] });

    expect(graph.sources).toEqual([]);
    expect(graph.sessions).toEqual([]);
    expect(graph.windows).toEqual([]);
    expect(graph.panes).toEqual([]);
    expect(graph.clients).toEqual([]);
    expect(graph.winlinks).toEqual([]);
    expect(graph.records).toEqual([]);
    assertFrozenData(graph);
  });

  test("retains an explicitly empty source as successful captured data", () => {
    const graph = normalizeGraph({
      capture: capture(),
      sources: [
        {
          listCommand: "list-windows",
          rows: [],
          source: createGraphSourceId("empty-windows"),
        },
      ],
    });

    expect(graph.sources).toHaveLength(1);
    expect(graph.sources[0]).toMatchObject({ id: "empty-windows", records: [] });
    expect(graph.records).toEqual([]);
    assertFrozenData(graph);
  });

  test("rejects invalid capture and duplicate source identities", () => {
    const validSource = {
      listCommand: "list-sessions" as const,
      rows: [completeFormatRow({ session_id: "$1" })],
      source: createGraphSourceId("same"),
    };

    expect(() =>
      normalizeGraph({
        capture: { ...capture(), capabilityFingerprint: "" },
        sources: [],
      }),
    ).toThrow();
    expect(() =>
      normalizeGraph({
        capture: { ...capture(), connection: "" as ConnectionAlias },
        sources: [],
      }),
    ).toThrow();
    expect(() =>
      normalizeGraph({
        capture: { ...capture(), epoch: -1 as DaemonEpoch },
        sources: [],
      }),
    ).toThrow();
    expect(() =>
      normalizeGraph({ capture: capture(), sources: [validSource, validSource] }),
    ).toThrow(/source/);
  });
});
