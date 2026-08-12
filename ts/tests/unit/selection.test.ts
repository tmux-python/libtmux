import { describe, expect, test } from "bun:test";
import { types as nodeTypes } from "node:util";

import { Client } from "../../src/client.js";
import { MultipleMatchesError, NoMatchError, QueryValidationError } from "../../src/exc.js";
import {
  createClientSelection,
  createProjectedSelection,
} from "../../src/_internal/selection/evaluate.js";
import {
  entityRefForHandle,
  snapshotForHandle,
  winlinkRefForHandle,
} from "../../src/_internal/runtime/live_handle.js";
import * as selectionModule from "../../src/selection.js";
import type { Selection } from "../../src/selection.js";
import { Session } from "../../src/session.js";
import { Window } from "../../src/window.js";
import {
  createClientHarness,
  createIncompleteSessionProjection,
  createRichProjectedHarness,
  createSessionHarness,
  createSessionProvenanceHarness,
  createWindowAssociationHarness,
} from "../support/selection_fixtures.js";

function expectInvalidQuery(action: () => unknown): QueryValidationError {
  let observed: unknown;
  try {
    action();
  } catch (error) {
    observed = error;
  }
  expect(observed).toBeInstanceOf(QueryValidationError);
  expect(observed).toMatchObject({ code: "invalid-query" });
  return observed as QueryValidationError;
}

function invokeMethod(receiver: object, key: PropertyKey, arguments_: readonly unknown[]): unknown {
  const callable: unknown = Reflect.get(receiver, key);
  if (typeof callable !== "function") throw new TypeError(`${String(key)} is not callable`);
  return Reflect.apply(callable, receiver, arguments_);
}

function captureError<ErrorType extends Error>(
  action: () => unknown,
  constructor: abstract new (...arguments_: never[]) => ErrorType,
): ErrorType {
  let observed: unknown;
  try {
    action();
  } catch (error) {
    observed = error;
  }
  expect(observed).toBeInstanceOf(constructor);
  return observed as ErrorType;
}

function assertDeepFrozenData(value: unknown, seen = new Set<object>()): void {
  if (typeof value !== "object" || value === null || seen.has(value)) return;
  seen.add(value);
  expect(Object.isFrozen(value)).toBe(true);
  for (const key of Reflect.ownKeys(value)) {
    expect(typeof key).toBe("string");
    assertDeepFrozenData(Reflect.get(value, key), seen);
  }
}

describe("Selection collection contract", () => {
  test("is a type-only public interface with private runtime construction", async () => {
    const harness = await createSessionHarness(["alpha"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const internalModule = await import("../../src/_internal/selection/evaluate.js");

    expect(Object.keys(selectionModule)).toEqual(["parseLegacyWhere"]);
    expect(Object.keys(internalModule).sort()).toEqual([
      "createClientSelection",
      "createProjectedSelection",
    ]);
    expect(Reflect.get(selectionModule, "Selection")).toBeUndefined();
    const runtimeConstructor = Reflect.get(selection, "constructor") as Function;
    expect(runtimeConstructor).not.toBe(selectionModule);
    expect(runtimeConstructor.name).not.toBe("Selection");
    const filtered = selection.filter(() => true);
    const queried = selection.where({});
    const chained = filtered.where({}).filter(() => true);
    for (const value of [selection, filtered, queried, chained]) {
      expect(nodeTypes.isProxy(value)).toBe(false);
      expect(Object.isFrozen(value)).toBe(true);
    }
  });

  test("preserves eager order and duplicates without becoming an Array", async () => {
    const harness = await createSessionHarness(["alpha", "beta", "alpha"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const firstIterator = selection[Symbol.iterator]();
    const secondIterator = selection[Symbol.iterator]();

    expect(selection).not.toBeInstanceOf(Array);
    expect(Array.isArray(selection)).toBe(false);
    expect(firstIterator).not.toBe(secondIterator);
    expect([...firstIterator]).toEqual([...harness.values]);
    expect([...secondIterator]).toEqual([...harness.values]);
    expect([...selection]).toEqual([...harness.values]);
    expect([...selection].map(({ name }) => name)).toEqual(["alpha", "beta", "alpha"]);
    expect(selection.length).toBe(3);
    expect(selection.at(0)).toBe(harness.values[0]!);
    expect(selection.at(Number.NaN)).toBe(harness.values[0]!);
    expect(selection.at(1.9)).toBe(harness.values[1]!);
    expect(selection.at(-1)).toBe(harness.values[2]!);
    expect(selection.at(-1.9)).toBe(harness.values[2]!);
    expect(selection.at(-4)).toBeUndefined();
    expect(Reflect.has(selection, "0")).toBe(false);
    expect(Reflect.has(selection, "push")).toBe(false);
    expect(selection.count({ name: "alpha" })).toBe(2);
  });

  test("returns defensive arrays whose mutation cannot alter membership", async () => {
    const harness = await createSessionHarness(["alpha", "beta"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const copy = selection.toArray();

    expect(copy).toEqual([...harness.values]);
    expect(copy).not.toBe(selection.toArray());
    copy.reverse();
    copy.pop();
    copy.push(harness.values[0]!);

    expect(selection.toArray()).toEqual([...harness.values]);
    expect(selection.length).toBe(2);
  });

  test("implements the complete eager Array filter callback contract", async () => {
    const harness = await createSessionHarness(["beta", "alpha", "beta", "gamma"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const context = { prefix: "b" };
    const calls: Array<{
      readonly index: number;
      readonly value: Session;
      readonly values: readonly Session[];
    }> = [];
    const filtered = selection.filter(function (
      this: typeof context,
      value: Session,
      index: number,
      values: readonly Session[],
    ): unknown {
      expect(this).toBe(context);
      calls.push({ index, value, values });
      return value.name?.startsWith(this.prefix);
    }, context);

    expect(calls.map(({ index }) => index)).toEqual([0, 1, 2, 3]);
    expect(calls.map(({ value }) => value)).toEqual([...harness.values]);
    expect(calls.every(({ values }) => values === calls[0]?.values)).toBe(true);
    expect(calls[0]?.values).not.toBe(harness.values);
    for (const { values } of calls) {
      expect(Object.isFrozen(values)).toBe(true);
      expect(values).toHaveLength(harness.values.length);
      for (const [index, value] of values.entries()) {
        expect(value).toBe(harness.values[index]!);
      }
    }
    expect(filtered.toArray()).toEqual([harness.values[0]!, harness.values[2]!]);
    expect(filtered).not.toBe(selection);
    const filter = Reflect.get(selection, "filter") as Selection<Session>["filter"];
    expect(() => Reflect.apply(filter, selection, [])).toThrow();

    const sentinel = new Error("predicate failure");
    let caught: unknown;
    try {
      selection.filter(() => {
        throw sentinel;
      });
    } catch (error) {
      caught = error;
    }
    expect(caught).toBe(sentinel);
  });

  test("applies synchronous ToBoolean filtering without interpreting promises", async () => {
    const harness = await createSessionHarness(["alpha", "beta", "gamma"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const truthyResult = invokeMethod(selection, "filter", [
      (_value: Session, index: number) => (index === 1 ? 0 : { include: true }),
    ]) as Selection<Session>;
    const truthyValues = truthyResult.toArray();

    expect(truthyValues).toHaveLength(2);
    expect(truthyValues[0]).toBe(harness.values[0]!);
    expect(truthyValues[1]).toBe(harness.values[2]!);

    let asyncCalls = 0;
    const asyncResult = invokeMethod(selection, "filter", [
      async () => {
        asyncCalls += 1;
        return false;
      },
    ]) as Selection<Session>;
    const asyncValues = asyncResult.toArray();

    expect(asyncResult).not.toBeInstanceOf(Promise);
    expect(asyncCalls).toBe(3);
    expect(asyncValues).toHaveLength(3);
    for (const [index, value] of asyncValues.entries()) {
      expect(value).toBe(harness.values[index]!);
    }
  });

  test("retains entry-record association across equal contextual windows", async () => {
    const harness = await createWindowAssociationHarness();
    const selection = createProjectedSelection("window", harness.values, harness.projection);
    const [first, second] = harness.values;
    if (first === undefined || second === undefined) throw new Error("fixture windows are missing");

    expect(first).not.toBe(second);
    expect(first.equals(second)).toBe(true);
    for (const retained of [
      selection.filter(() => true).toArray(),
      selection.where({ name: "shared" }).toArray(),
    ]) {
      expect(retained).toHaveLength(2);
      expect(retained[0]).toBe(first);
      expect(retained[1]).toBe(second);
    }
    expect(selection.where({ session: { is: { name: "one" } } }).toArray()).toEqual([first]);
    expect(selection.where({ session: { is: { name: "two" } } }).toArray()).toEqual([second]);
    expect(
      selection
        .filter((_value: Window, index: number) => index === 1)
        .where({ session: { is: { name: "two" } } })
        .toArray(),
    ).toEqual([second]);
    expect(
      selection
        .filter((_value: Window, index: number) => index === 1)
        .where({ session: { is: { name: "one" } } })
        .toArray(),
    ).toEqual([]);
  });

  test("implements the zero, one, and many cardinality table", async () => {
    const harness = await createSessionHarness(["alpha", "beta", "alpha"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    expect(selection.first({ name: "missing" })).toBeUndefined();
    expect(selection.first({ name: "alpha" })).toBe(harness.values[0]!);
    expect(selection.one({ name: "beta" })).toBe(harness.values[1]!);
    expect(selection.oneOrUndefined({ name: "missing" })).toBeUndefined();
    expect(selection.oneOrUndefined({ name: "beta" })).toBe(harness.values[1]!);
    expect(selection.exists({ name: "missing" })).toBe(false);
    expect(selection.exists({ name: "alpha" })).toBe(true);
    expect(selection.count({ name: "missing" })).toBe(0);
    expect(selection.count({ name: "alpha" })).toBe(2);

    const noMatch = captureError(() => selection.one({ name: "missing" }), NoMatchError);
    expect(noMatch.query).toEqual({ name: "missing" });
    let ambiguousResult: Session | undefined;
    const ambiguous = captureError(() => {
      ambiguousResult = selection.one({ name: "alpha" });
    }, MultipleMatchesError);
    expect(ambiguousResult).toBeUndefined();
    expect(ambiguous.count).toBe(2);
    expect(ambiguous.query).toEqual({ name: "alpha" });
    assertDeepFrozenData(ambiguous.query);

    const optionalMany = captureError(
      () => selection.oneOrUndefined({ name: "alpha" }),
      MultipleMatchesError,
    );
    expect(optionalMany.count).toBe(2);
    expect(optionalMany.query).toEqual({ name: "alpha" });
  });

  test("validates fresh malformed projected criteria through every criteria entrypoint", async () => {
    const harness = await createRichProjectedHarness();
    const selection = createProjectedSelection(
      "session",
      harness.sessions.values,
      harness.sessions.projection,
    );
    const makeMalformedCriteria = (): unknown => ({
      windows: {
        some: {
          session: {
            is: { name: "one", unexpected: true },
          },
        },
      },
    });

    for (const method of ["where", "first", "one", "oneOrUndefined", "exists", "count"] as const) {
      expectInvalidQuery(() =>
        Reflect.apply(selection[method], selection, [makeMalformedCriteria()]),
      );
    }
  });

  test("attaches frozen canonical queries and deterministic messages", async () => {
    const harness = await createSessionHarness(["alpha", "beta"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const criteria = {
      sessionId: "$404",
      name: { mode: "insensitive" as const, contains: "Z" },
    };
    const noMatch = captureError(() => selection.one(criteria), NoMatchError);

    criteria.name.contains = "mutated";
    expect(noMatch.message).toBe(
      'No objects found: name={"contains":"Z","mode":"insensitive"}, session_id=\'$404\'',
    );
    expect(noMatch.message).not.toContain("[object Object]");
    expect(noMatch.query).toEqual({
      name: { contains: "Z", mode: "insensitive" },
      session_id: "$404",
    });
    expect(Object.keys(noMatch.query ?? {})).toEqual(["name", "session_id"]);
    assertDeepFrozenData(noMatch.query);

    const nested = captureError(
      () =>
        selection.one({
          OR: [{ sessionId: "$9", name: { startsWith: "z", contains: "x" } }],
        }),
      NoMatchError,
    );
    expect(nested.message).toBe(
      'No objects found: OR=[{"name":{"contains":"x","startsWith":"z"},"session_id":"$9"}]',
    );
    expect(nested.message).not.toContain("[object Object]");
    assertDeepFrozenData(nested.query);

    const rich = await createRichProjectedHarness();
    const panes = createProjectedSelection("pane", rich.panes.values, rich.panes.projection).filter(
      () => false,
    );
    const flat = captureError(() => panes.one({ paneId: "%3" }), NoMatchError);
    expect(flat.message).toBe("No objects found: pane_id='%3'");

    const absent = captureError(() => panes.one(), NoMatchError);
    expect(absent.message).toBe("No objects found");
    expect(absent.query).toEqual({});
    assertDeepFrozenData(absent.query);
  });

  test("performs no transport I/O after selection construction", async () => {
    const harness = await createRichProjectedHarness();
    const selection = createProjectedSelection(
      "session",
      harness.sessions.values,
      harness.sessions.projection,
    );
    const requestCount = harness.sessions.transport.requests.length;

    void [...selection];
    void selection.at(-1);
    void selection.toArray();
    void selection.filter(() => true);
    void selection.where({ panes: { some: { paneTitle: "shell" } } });
    void selection.first();
    void selection.one({ name: "one" });
    void selection.oneOrUndefined({ name: "missing" });
    void selection.exists();
    void selection.count();

    expect(harness.sessions.transport.requests).toHaveLength(requestCount);
  });
});

describe("internal Selection construction", () => {
  test("requires authentic model-complete projection membership alignment", async () => {
    const first = await createSessionHarness(["alpha", "beta"]);
    const second = await createSessionHarness(["alpha", "beta"]);
    const counterfeit = Object.create(Session.prototype) as Session;
    const incomplete = createIncompleteSessionProjection(first.graph);

    expectInvalidQuery(() =>
      createProjectedSelection("session", [first.values[1]!, first.values[0]!], first.projection),
    );
    expectInvalidQuery(() =>
      createProjectedSelection("session", first.values.slice(0, 1), first.projection),
    );
    expectInvalidQuery(() =>
      createProjectedSelection("session", [...first.values, first.values[0]!], first.projection),
    );
    expectInvalidQuery(() =>
      Reflect.apply(createProjectedSelection, undefined, ["pane", first.values, first.projection]),
    );
    expectInvalidQuery(() => createProjectedSelection("session", second.values, first.projection));
    expectInvalidQuery(() =>
      createProjectedSelection("session", [counterfeit, first.values[1]!], first.projection),
    );
    expectInvalidQuery(() =>
      Reflect.apply(createProjectedSelection, undefined, [
        "session",
        first.values,
        { ...first.projection },
      ]),
    );
    expectInvalidQuery(() =>
      Reflect.apply(createProjectedSelection, undefined, ["session", first.values, incomplete]),
    );
  });

  test("rejects swapped byte-identical handles from distinct member records", async () => {
    const harness = await createSessionProvenanceHarness();
    const [first, second] = harness.values;
    if (first === undefined || second === undefined)
      throw new Error("fixture sessions are missing");

    expect(first).not.toBe(second);
    expect(first.equals(second)).toBe(true);
    expect(entityRefForHandle(first)).toEqual(entityRefForHandle(second));
    expect(snapshotForHandle(first)).toEqual(snapshotForHandle(second));
    expect(winlinkRefForHandle(first)).toBeNull();
    expect(winlinkRefForHandle(second)).toBeNull();
    const canonical = createProjectedSelection("session", harness.values, harness.projection);
    expect(canonical.where({ windows: { some: { name: "first" } } }).toArray()).toEqual([first]);
    expect(canonical.where({ windows: { some: { name: "second" } } }).toArray()).toEqual([second]);
    expectInvalidQuery(() =>
      createProjectedSelection("session", [second, first], harness.projection),
    );
  });

  test("rejects byte-identical handles from an exact-ref twin graph", async () => {
    const harness = await createSessionProvenanceHarness();

    expectInvalidQuery(() =>
      createProjectedSelection("session", harness.twinValues, harness.projection),
    );
  });

  test("constructs authentic Client selections without declarative criteria", async () => {
    const harness = await createClientHarness(["/dev/pts/1", "/dev/pts/2"]);
    const selection: Selection<Client> = createClientSelection(harness.values);
    const requestCount = harness.transport.requests.length;

    const initialValues = selection.toArray();
    const filtered = selection.filter((client: Client) => client.name?.endsWith("2"));
    const filteredValues = filtered.toArray();
    for (const value of [selection, filtered]) {
      expect(nodeTypes.isProxy(value)).toBe(false);
      expect(Object.isFrozen(value)).toBe(true);
    }
    expect(initialValues).toHaveLength(2);
    expect(initialValues[0]).toBe(harness.values[0]!);
    expect(initialValues[1]).toBe(harness.values[1]!);
    expect(filteredValues).toHaveLength(1);
    expect(filteredValues[0]).toBe(harness.values[1]!);
    expect(selection.first()).toBe(harness.values[0]!);
    expect(selection.count()).toBe(2);
    expect(selection.exists()).toBe(true);
    expect(harness.transport.requests).toHaveLength(requestCount);
    const ambiguous = captureError(() => selection.one(), MultipleMatchesError);
    expect(ambiguous.count).toBe(2);
    expect(ambiguous.query).toEqual({});
    assertDeepFrozenData(ambiguous.query);
    const optionalAmbiguous = captureError(() => selection.oneOrUndefined(), MultipleMatchesError);
    expect(optionalAmbiguous.count).toBe(2);
    expect(optionalAmbiguous.query).toEqual({});
    assertDeepFrozenData(optionalAmbiguous.query);

    const criteria = { name: "forbidden" };
    for (const method of ["first", "one", "oneOrUndefined", "exists", "count"] as const) {
      expectInvalidQuery(() => Reflect.apply(selection[method], selection, [criteria]));
    }
    const where = Reflect.get(selection, "where") as (...arguments_: unknown[]) => unknown;
    expectInvalidQuery(() => Reflect.apply(where, selection, [{}]));
    expectInvalidQuery(() => createClientSelection([Object.create(Client.prototype) as Client]));
  });
});
