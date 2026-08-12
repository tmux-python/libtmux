import { describe, expect, test } from "bun:test";

import { MultipleMatchesError, QueryValidationError } from "../../src/exc.js";
import { createProjectedSelection } from "../../src/_internal/selection/evaluate.js";
import { parseLegacyWhere } from "../../src/selection.js";
import { createSessionHarness } from "../support/selection_fixtures.js";

function expectInvalidQuery(action: () => unknown, escaped?: unknown): QueryValidationError {
  let observed: unknown;
  try {
    action();
  } catch (error) {
    observed = error;
  }
  if (escaped !== undefined) expect(observed).not.toBe(escaped);
  expect(observed).toBeInstanceOf(QueryValidationError);
  expect(observed).toMatchObject({ code: "invalid-query" });
  return observed as QueryValidationError;
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

describe("parseLegacyWhere", () => {
  test("lowers the sole Session and Window spelling to canonical documents", () => {
    const sessionInput = Object.assign(Object.create(null) as Record<string, unknown>, {
      name__contains: "main",
    });
    const session = parseLegacyWhere("session", sessionInput);
    const window = parseLegacyWhere("window", { name__contains: "logs" });

    expect(session).toEqual({
      model: "session",
      version: 1,
      where: { name: { contains: "main" } },
    });
    expect(window).toEqual({
      model: "window",
      version: 1,
      where: { name: { contains: "logs" } },
    });
    expect(JSON.stringify(session)).toBe(
      '{"model":"session","version":1,"where":{"name":{"contains":"main"}}}',
    );
    expect(JSON.stringify(window)).not.toContain("name__contains");
    assertDeepFrozenData(session);
    assertDeepFrozenData(window);
  });

  test("passes only lowered canonical criteria into Selection query evidence", async () => {
    const harness = await createSessionHarness(["alpha", "beta"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const document = parseLegacyWhere("session", { name__contains: "a" });
    let observed: unknown;
    try {
      selection.one(document.where);
    } catch (error) {
      observed = error;
    }

    expect(observed).toBeInstanceOf(MultipleMatchesError);
    const error = observed as MultipleMatchesError;
    expect(error.count).toBe(2);
    expect(error.query).toEqual({ name: { contains: "a" } });
    expect(error.message).toBe('Multiple objects returned (2): name={"contains":"a"}');
    expect(error.message).not.toContain("name__contains");
    assertDeepFrozenData(error.query);
  });

  test("rejects every other model, shape, key, and value", () => {
    for (const [model, input] of [
      ["pane", { name__contains: "x" }],
      ["client", { name__contains: "x" }],
      ["server", { name__contains: "x" }],
      ["session", null],
      ["session", []],
      ["session", {}],
      ["session", { name__contains: "x", extra: true }],
      ["session", { name__contains: 1 }],
      ["session", { name__contains: null }],
      ["session", { name__contains: new String("x") }],
      ["session", { name__exact: "x" }],
      ["session", { name__icontains: "x" }],
      ["session", { session_name__contains: "x" }],
      ["session", { name__contains__noeq: "x" }],
      ["session", { noeq: "x" }],
      ["window", { name__regex: "x" }],
    ] as const) {
      expectInvalidQuery(() => Reflect.apply(parseLegacyWhere, undefined, [model, input]));
    }
  });

  test("does not invoke accessors, conversion hooks, or hostile reflection", () => {
    let getterCalls = 0;
    let conversionCalls = 0;
    const accessor = Object.create(null) as Record<string, unknown>;
    Object.defineProperty(accessor, "name__contains", {
      enumerable: true,
      get() {
        getterCalls += 1;
        return "x";
      },
    });
    const conversion = {
      name__contains: "x",
      toJSON() {
        conversionCalls += 1;
        return { name__contains: "x" };
      },
      toString() {
        conversionCalls += 1;
        return "x";
      },
    };
    const reflectionSentinel = new Error("legacy reflection escaped");
    const hostile = new Proxy(
      { name__contains: "x" },
      {
        ownKeys() {
          throw reflectionSentinel;
        },
      },
    );

    expectInvalidQuery(() => parseLegacyWhere("session", accessor));
    expectInvalidQuery(() => parseLegacyWhere("session", conversion));
    expectInvalidQuery(() => parseLegacyWhere("window", hostile), reflectionSentinel);
    expect(getterCalls).toBe(0);
    expect(conversionCalls).toBe(0);
  });

  test("rejects every non-plain legacy object boundary independently", () => {
    let conversionCalls = 0;
    const customPrototype = Object.create({ inherited: true }) as Record<string, unknown>;
    customPrototype.name__contains = "x";
    const symbolKey = { name__contains: "x", [Symbol("private")]: "value" };
    const nonEnumerable = { name__contains: "x" };
    Object.defineProperty(nonEnumerable, "hidden", { enumerable: false, value: "value" });
    const prototypeSentinel = new Error("legacy prototype trap escaped");
    const descriptorSentinel = new Error("legacy descriptor trap escaped");
    const hostilePrototype = new Proxy(
      { name__contains: "x" },
      {
        getPrototypeOf() {
          throw prototypeSentinel;
        },
      },
    );
    const hostileDescriptor = new Proxy(
      { name__contains: "x" },
      {
        getOwnPropertyDescriptor() {
          throw descriptorSentinel;
        },
      },
    );
    const passive = new Proxy(
      { name__contains: "x" },
      {
        get(target, property, receiver) {
          if (property === "toJSON" || property === "toString") conversionCalls += 1;
          return Reflect.get(target, property, receiver);
        },
      },
    );

    expectInvalidQuery(() => parseLegacyWhere("session", customPrototype));
    expectInvalidQuery(() => parseLegacyWhere("session", symbolKey));
    expectInvalidQuery(() => parseLegacyWhere("window", nonEnumerable));
    expectInvalidQuery(() => parseLegacyWhere("session", hostilePrototype), prototypeSentinel);
    expectInvalidQuery(() => parseLegacyWhere("window", hostileDescriptor), descriptorSentinel);
    expectInvalidQuery(() => parseLegacyWhere("session", passive));
    expect(conversionCalls).toBe(0);
  });
});
