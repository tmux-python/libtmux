import { fileURLToPath } from "node:url";

import { describe, expect, test } from "bun:test";

import { NoMatchError, QueryValidationError } from "../../src/exc.js";
import { compileWhere } from "../../src/_internal/selection/compile.js";
import { createProjectedSelection } from "../../src/_internal/selection/evaluate.js";
import {
  decodeWhereDocument,
  encodeWhereDocument,
} from "../../src/_internal/selection/serialization.js";
import type { PaneWhere, SessionWhere, WhereDocumentV1, WindowWhere } from "../../src/selection.js";
import { createRichProjectedHarness, createSessionHarness } from "../support/selection_fixtures.js";

interface RegexCorpusCase {
  readonly adaptation: string | null;
  readonly expected: { readonly bun: boolean; readonly node: boolean; readonly python: boolean };
  readonly flags: "" | "m" | "s" | "ms";
  readonly id: string;
  readonly input: string;
  readonly mode: "default" | "insensitive";
  readonly pattern: string;
  readonly session_id: string;
}

interface RegexCorpus {
  readonly adaptations: Readonly<Record<string, string>>;
  readonly cases: readonly RegexCorpusCase[];
  readonly protocol: string;
  readonly runtimes: { readonly bun: string; readonly node: string; readonly python: string };
}

const tsRootPath = fileURLToPath(new URL("../..", import.meta.url));

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

function invokeMethod(receiver: object, key: PropertyKey, arguments_: readonly unknown[]): unknown {
  const callable: unknown = Reflect.get(receiver, key);
  if (typeof callable !== "function") throw new TypeError(`${String(key)} is not callable`);
  return Reflect.apply(callable, receiver, arguments_);
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

function nestedAndCriteria(edges: number): Record<string, unknown> {
  let criteria: Record<string, unknown> = { name: "alpha" };
  for (let index = 0; index < edges; index += 1) criteria = { AND: [criteria] };
  return criteria;
}

function prefixedCriteriaCycle(edges: number): Record<string, unknown> {
  const root: Record<string, unknown> = {};
  let current = root;
  for (let index = 0; index < edges; index += 1) {
    const child: Record<string, unknown> = {};
    current.AND = [child];
    current = child;
  }
  current.AND = [root];
  return root;
}

describe("scalar and logical criteria", () => {
  test("supports bare equality and every canonical string comparison", async () => {
    const harness = await createSessionHarness(["Alpha", "alphabet", null, "beta", "ALPHA"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    expect(selection.where({ name: "Alpha" }).toArray()).toEqual([harness.values[0]!]);
    expect(selection.where({ name: { equals: "alpha", mode: "insensitive" } }).toArray()).toEqual([
      harness.values[0]!,
      harness.values[4]!,
    ]);
    expect(selection.where({ name: { contains: "pha" } }).toArray()).toEqual([
      harness.values[0]!,
      harness.values[1]!,
    ]);
    expect(selection.where({ name: { startsWith: "Al" } }).toArray()).toEqual([harness.values[0]!]);
    expect(selection.where({ name: { endsWith: "ta" } }).toArray()).toEqual([harness.values[3]!]);
    expect(selection.where({ name: { in: ["beta", "Alpha"] } }).toArray()).toEqual([
      harness.values[0]!,
      harness.values[3]!,
    ]);
    expect(selection.where({ name: { notIn: ["beta", "Alpha"] } }).toArray()).toEqual([
      harness.values[1]!,
      harness.values[4]!,
    ]);
  });

  test("applies insensitive mode to every non-regex string operator", async () => {
    const harness = await createSessionHarness(["MiXeDAlphaTail", "OtherValue", null]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    expect(selection.where({ name: { contains: "mixed" } }).toArray()).toEqual([]);
    expect(selection.where({ name: { contains: "mixed", mode: "insensitive" } }).toArray()).toEqual(
      [harness.values[0]!],
    );

    expect(selection.where({ name: { startsWith: "mixed" } }).toArray()).toEqual([]);
    expect(
      selection.where({ name: { mode: "insensitive", startsWith: "mixed" } }).toArray(),
    ).toEqual([harness.values[0]!]);

    expect(selection.where({ name: { endsWith: "TAIL" } }).toArray()).toEqual([]);
    expect(selection.where({ name: { endsWith: "TAIL", mode: "insensitive" } }).toArray()).toEqual([
      harness.values[0]!,
    ]);

    expect(selection.where({ name: { in: ["MIXEDALPHATAIL"] } }).toArray()).toEqual([]);
    expect(
      selection.where({ name: { in: ["MIXEDALPHATAIL"], mode: "insensitive" } }).toArray(),
    ).toEqual([harness.values[0]!]);

    expect(selection.where({ name: { notIn: ["MIXEDALPHATAIL"] } }).toArray()).toEqual([
      harness.values[0]!,
      harness.values[1]!,
    ]);
    expect(
      selection.where({ name: { mode: "insensitive", notIn: ["MIXEDALPHATAIL"] } }).toArray(),
    ).toEqual([harness.values[1]!]);

    expect(
      selection
        .where({
          name: {
            contains: "alpha",
            endsWith: "TAIL",
            mode: "insensitive",
            startsWith: "mixed",
          },
        })
        .toArray(),
    ).toEqual([harness.values[0]!]);
  });

  test("uses ECMAScript toLowerCase for non-regex insensitive equality", async () => {
    const harness = await createSessionHarness(["ſ", "ß", "K"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    expect(selection.where({ name: { equals: "s", mode: "insensitive" } }).toArray()).toEqual([]);
    expect(selection.where({ name: { equals: "ss", mode: "insensitive" } }).toArray()).toEqual([]);
    const kelvin = selection.where({ name: { equals: "k", mode: "insensitive" } }).toArray();
    expect(kelvin).toHaveLength(1);
    expect(kelvin[0]).toBe(harness.values[2]!);

    const nativeRegex = selection
      .where({
        name: {
          mode: "insensitive",
          regex: { flags: "", pattern: "^s$" },
        },
      })
      .toArray();
    expect(nativeRegex).toHaveLength(1);
    expect(nativeRegex[0]).toBe(harness.values[0]!);
  });

  test("ANDs scalar operators only for candidates satisfying every comparison", async () => {
    const sensitiveHarness = await createSessionHarness([
      "alpha-x",
      "prefix-tail",
      "alpha-tail",
      "other",
    ]);
    const sensitive = createProjectedSelection(
      "session",
      sensitiveHarness.values,
      sensitiveHarness.projection,
    );

    expect(sensitive.where({ name: { contains: "alpha" } }).toArray()).toEqual([
      sensitiveHarness.values[0]!,
      sensitiveHarness.values[2]!,
    ]);
    expect(sensitive.where({ name: { endsWith: "tail" } }).toArray()).toEqual([
      sensitiveHarness.values[1]!,
      sensitiveHarness.values[2]!,
    ]);
    expect(sensitive.where({ name: { contains: "alpha", endsWith: "tail" } }).toArray()).toEqual([
      sensitiveHarness.values[2]!,
    ]);

    const insensitiveHarness = await createSessionHarness([
      "MiXeD-x",
      "prefix-TaIl",
      "MiXeD-TaIl",
      "other",
    ]);
    const insensitive = createProjectedSelection(
      "session",
      insensitiveHarness.values,
      insensitiveHarness.projection,
    );
    const insensitiveContains = { contains: "mixed", mode: "insensitive" } as const;
    const insensitiveEnds = { endsWith: "TAIL", mode: "insensitive" } as const;

    expect(insensitive.where({ name: insensitiveContains }).toArray()).toEqual([
      insensitiveHarness.values[0]!,
      insensitiveHarness.values[2]!,
    ]);
    expect(insensitive.where({ name: insensitiveEnds }).toArray()).toEqual([
      insensitiveHarness.values[1]!,
      insensitiveHarness.values[2]!,
    ]);
    expect(
      insensitive
        .where({ name: { contains: "mixed", endsWith: "TAIL", mode: "insensitive" } })
        .toArray(),
    ).toEqual([insensitiveHarness.values[2]!]);
    expect(insensitive.where({ name: { contains: "mixed", endsWith: "TAIL" } }).toArray()).toEqual(
      [],
    );
  });

  test("ANDs multiple scalar operators and keeps the empty-list identities", async () => {
    const harness = await createSessionHarness(["Alpha", "alphabet", null, "beta", "ALPHA"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    expect(
      selection.where({ name: { contains: "ph", endsWith: "a", startsWith: "Al" } }).toArray(),
    ).toEqual([harness.values[0]!]);
    expect(selection.where({ name: { in: [] } }).toArray()).toEqual([]);
    expect(selection.where({ name: { notIn: [] } }).toArray()).toEqual([
      harness.values[0]!,
      harness.values[1]!,
      harness.values[3]!,
      harness.values[4]!,
    ]);
  });

  test("eagerly clones mutable nested criteria before returning a Selection", async () => {
    const harness = await createSessionHarness(["alpha", "beta", "alpha", "echo"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const criteria = { name: { contains: "a" } };

    const result = selection.where(criteria);
    criteria.name.contains = "z";

    expect(Object.isFrozen(result)).toBe(true);
    expect(result.toArray()).toEqual([harness.values[0]!, harness.values[1]!, harness.values[2]!]);
    expect(result.toArray()[0]).toBe(harness.values[0]!);
    expect(result.toArray()[1]).toBe(harness.values[1]!);
    expect(result.toArray()[2]).toBe(harness.values[2]!);
  });

  test("allows explicit null only for bare and equals criteria", async () => {
    const harness = await createSessionHarness(["alpha", null]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    expect(selection.where({ name: null }).toArray()).toEqual([harness.values[1]!]);
    expect(selection.where({ name: { equals: null } }).toArray()).toEqual([harness.values[1]!]);
    for (const criteria of [
      { name: { contains: null } },
      { name: { startsWith: null } },
      { name: { endsWith: null } },
      { name: { in: [null] } },
      { name: { notIn: [null] } },
      { name: { regex: null } },
    ]) {
      expectInvalidQuery(() => invokeMethod(selection, "where", [criteria]));
    }
  });

  test("applies top-level logical arrays with exact empty identities", async () => {
    const harness = await createSessionHarness(["alpha", "beta", "gamma"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    expect(selection.where({}).toArray()).toEqual([...harness.values]);
    expect(selection.where({ AND: [] }).toArray()).toEqual([...harness.values]);
    expect(selection.where({ OR: [] }).toArray()).toEqual([]);
    expect(selection.where({ NOT: [] }).toArray()).toEqual([...harness.values]);
    expect(selection.where({ OR: [{ name: "alpha" }, { name: "gamma" }] }).toArray()).toEqual([
      harness.values[0]!,
      harness.values[2]!,
    ]);
    expect(selection.where({ NOT: [{ name: "beta" }] }).toArray()).toEqual([
      harness.values[0]!,
      harness.values[2]!,
    ]);

    const logicalHarness = await createSessionHarness([
      "alpha-x",
      "prefix-tail",
      "alpha-tail",
      "other",
    ]);
    const logicalSelection = createProjectedSelection(
      "session",
      logicalHarness.values,
      logicalHarness.projection,
    );
    const firstChild = { name: { contains: "alpha" } } as const;
    const secondChild = { name: { endsWith: "tail" } } as const;

    expect(logicalSelection.where({ AND: [firstChild] }).toArray()).toEqual([
      logicalHarness.values[0]!,
      logicalHarness.values[2]!,
    ]);
    expect(logicalSelection.where({ AND: [secondChild] }).toArray()).toEqual([
      logicalHarness.values[1]!,
      logicalHarness.values[2]!,
    ]);
    expect(logicalSelection.where({ AND: [firstChild, secondChild] }).toArray()).toEqual([
      logicalHarness.values[2]!,
    ]);

    expect(logicalSelection.where({ OR: [firstChild, secondChild] }).toArray()).toEqual([
      logicalHarness.values[0]!,
      logicalHarness.values[1]!,
      logicalHarness.values[2]!,
    ]);
    expect(logicalSelection.where({ NOT: [firstChild] }).toArray()).toEqual([
      logicalHarness.values[1]!,
      logicalHarness.values[3]!,
    ]);
    expect(logicalSelection.where({ NOT: [secondChild] }).toArray()).toEqual([
      logicalHarness.values[0]!,
      logicalHarness.values[3]!,
    ]);
    expect(logicalSelection.where({ NOT: [firstChild, secondChild] }).toArray()).toEqual([
      logicalHarness.values[3]!,
    ]);
  });
});

describe("generated relation criteria", () => {
  test("evaluates all ten camelCase relations with empty and null semantics", async () => {
    const harness = await createRichProjectedHarness();
    const sessions = createProjectedSelection(
      "session",
      harness.sessions.values,
      harness.sessions.projection,
    );
    const windows = createProjectedSelection(
      "window",
      harness.windows.values,
      harness.windows.projection,
    );
    const panes = createProjectedSelection("pane", harness.panes.values, harness.panes.projection);

    expect(sessions.where({ windows: { some: { name: "editor" } } }).toArray()).toEqual([
      harness.sessions.values[0]!,
    ]);
    expect(sessions.where({ panes: { some: { title: "tail" } } }).toArray()).toEqual([
      harness.sessions.values[1]!,
    ]);
    expect(sessions.where({ activeWindow: { is: { name: "logs" } } }).toArray()).toEqual([
      harness.sessions.values[1]!,
    ]);
    expect(sessions.where({ activePane: { is: { title: "shell" } } }).toArray()).toEqual([
      harness.sessions.values[0]!,
    ]);

    expect(windows.where({ session: { is: { name: "one" } } }).toArray()).toEqual([
      harness.windows.values[0]!,
    ]);
    expect(windows.where({ linkedSessions: { some: { name: "two" } } }).toArray()).toEqual([
      harness.windows.values[1]!,
    ]);
    expect(windows.where({ panes: { some: { title: "tests" } } }).toArray()).toEqual([
      harness.windows.values[0]!,
    ]);
    expect(windows.where({ activePane: { is: { title: "tail" } } }).toArray()).toEqual([
      harness.windows.values[1]!,
    ]);

    expect(panes.where({ window: { is: { name: "editor" } } }).toArray()).toEqual([
      harness.panes.values[0]!,
      harness.panes.values[1]!,
    ]);
    expect(panes.where({ session: { is: { name: "two" } } }).toArray()).toEqual([
      harness.panes.values[2]!,
    ]);

    expect(sessions.where({ panes: { some: {} } }).toArray()).toEqual([
      harness.sessions.values[0]!,
      harness.sessions.values[1]!,
    ]);
    expect(sessions.where({ panes: { every: {} } }).toArray()).toEqual([
      ...harness.sessions.values,
    ]);
    expect(sessions.where({ panes: { none: {} } }).toArray()).toEqual([
      harness.sessions.values[2]!,
    ]);
    expect(sessions.where({ activeWindow: { is: null } }).toArray()).toEqual([
      harness.sessions.values[2]!,
    ]);
    expect(sessions.where({ activeWindow: { isNot: null } }).toArray()).toEqual([
      harness.sessions.values[0]!,
      harness.sessions.values[1]!,
    ]);
  });

  test("evaluates discriminating multi-hop cyclic relation criteria", async () => {
    const harness = await createRichProjectedHarness();
    const sessions = createProjectedSelection(
      "session",
      harness.sessions.values,
      harness.sessions.projection,
    );
    const panes = createProjectedSelection("pane", harness.panes.values, harness.panes.projection);

    const sessionResult = sessions
      .where({
        windows: {
          some: {
            session: { is: { name: "one" } },
          },
        },
      })
      .toArray();
    expect(sessionResult).toHaveLength(1);
    expect(sessionResult[0]).toBe(harness.sessions.values[0]!);

    const paneResult = panes
      .where({
        window: {
          is: {
            session: { is: { name: "two" } },
          },
        },
      })
      .toArray();
    expect(paneResult).toHaveLength(1);
    expect(paneResult[0]).toBe(harness.panes.values[2]!);
  });

  test("ANDs multiple operators within many and one relation wrappers", async () => {
    const harness = await createRichProjectedHarness();
    const sessions = createProjectedSelection(
      "session",
      harness.sessions.values,
      harness.sessions.projection,
    );
    const windows = createProjectedSelection(
      "window",
      harness.windows.values,
      harness.windows.projection,
    );

    expect(
      sessions
        .where({
          panes: {
            every: { title: { contains: "s" } },
            none: { title: "tail" },
            some: { title: "shell" },
          },
        })
        .toArray(),
    ).toEqual([harness.sessions.values[0]!]);
    expect(
      windows
        .where({
          session: {
            is: { name: { contains: "o" } },
            isNot: { name: "two" },
          },
        })
        .toArray(),
    ).toEqual([harness.windows.values[0]!]);
  });

  test("evaluates populated every and none truth tables before ANDing wrappers", async () => {
    const harness = await createRichProjectedHarness();
    const sessions = createProjectedSelection(
      "session",
      harness.sessions.values,
      harness.sessions.projection,
    );
    const [one, two, empty] = harness.sessions.values;
    if (one === undefined || two === undefined || empty === undefined) {
      throw new Error("fixture sessions are missing");
    }

    expect(sessions.where({ panes: { every: { title: { endsWith: "l" } } } }).toArray()).toEqual([
      two,
      empty,
    ]);
    expect(sessions.where({ panes: { none: { title: { endsWith: "s" } } } }).toArray()).toEqual([
      two,
      empty,
    ]);

    const commonSome = { title: { in: ["shell", "tail"] } } as const;
    expect(sessions.where({ panes: { some: commonSome } }).toArray()).toEqual([one, two]);

    const everyGate = { title: { notIn: ["tests"] } } as const;
    expect(sessions.where({ panes: { every: everyGate } }).toArray()).toEqual([two, empty]);
    expect(sessions.where({ panes: { every: everyGate, some: commonSome } }).toArray()).toEqual([
      two,
    ]);

    const noneGate = { title: { equals: "tail" } } as const;
    expect(sessions.where({ panes: { none: noneGate } }).toArray()).toEqual([one, empty]);
    expect(sessions.where({ panes: { none: noneGate, some: commonSome } }).toArray()).toEqual([
      one,
    ]);
  });

  test("rejects empty wrappers and every noncanonical relation spelling", async () => {
    const harness = await createRichProjectedHarness();
    const sessions = createProjectedSelection(
      "session",
      harness.sessions.values,
      harness.sessions.projection,
    );
    const windows = createProjectedSelection(
      "window",
      harness.windows.values,
      harness.windows.projection,
    );

    for (const criteria of [
      { windows: {} },
      { activeWindow: {} },
      { panes: { some: {}, unexpected: {} } },
      { active_window: { is: {} } },
      { active_pane: { is: {} } },
      { children: { some: {} } },
    ]) {
      expectInvalidQuery(() => invokeMethod(sessions, "where", [criteria]));
    }
    for (const criteria of [
      { linked_sessions: { some: {} } },
      { active_pane: { is: {} } },
      { children: { some: {} } },
    ]) {
      expectInvalidQuery(() => invokeMethod(windows, "where", [criteria]));
    }
  });
});

describe("regex criteria", () => {
  test("runs the shared corpus through Bun's native engine", async () => {
    const corpus = (await Bun.file(
      new URL("../fixtures/where_regex.json", import.meta.url),
    ).json()) as RegexCorpus;
    const harness = await createSessionHarness(corpus.cases.map(({ input }) => input));
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    expect(corpus.protocol).toBe("libtmux-where-regex-v1");
    expect(corpus.runtimes).toEqual({ bun: "1.3.14", node: "22", python: "3" });
    expect(process.versions.bun).toBe("1.3.14");
    expect(corpus.cases).toHaveLength(19);
    expect(new Set(corpus.cases.map(({ session_id }) => session_id)).size).toBe(
      corpus.cases.length,
    );
    for (const [index, entry] of corpus.cases.entries()) {
      expect(harness.values[index]?.id, entry.id).toBe(entry.session_id);
      const criteria: SessionWhere = {
        name: {
          equals: entry.input,
          regex: { flags: entry.flags, pattern: entry.pattern },
          ...(entry.mode === "insensitive" ? { mode: "insensitive" as const } : {}),
        },
        id: entry.session_id,
      };
      expect(selection.count(criteria), entry.id).toBe(entry.expected.bun ? 1 : 0);
    }

    const combined = corpus.cases.find(({ id }) => id === "multiline-dotall-open-quantifier");
    if (combined === undefined) throw new Error("combined regex case is missing");
    const countCombined = (flags: "m" | "ms" | "s", pattern = combined.pattern): number =>
      selection.count({
        name: {
          equals: combined.input,
          regex: { flags, pattern },
        },
        id: combined.session_id,
      });
    expect(countCombined("ms")).toBe(1);
    expect(countCombined("m")).toBe(0);
    expect(countCombined("s")).toBe(0);
    const unsatisfiedLowerBound = combined.pattern.replace("{2,}", "{4,}");
    expect(unsatisfiedLowerBound).not.toBe(combined.pattern);
    expect(countCombined("ms", unsatisfiedLowerBound)).toBe(0);
  });

  test("accepts only the closed canonical flags and grammar", async () => {
    const harness = await createSessionHarness(["ordinary bounded input"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    for (const regex of [
      { flags: "" },
      { pattern: "ordinary" },
      { extra: true, flags: "", pattern: "ordinary" },
      { flags: "", pattern: 1 },
      { flags: 1, pattern: "ordinary" },
    ]) {
      expectInvalidQuery(() => invokeMethod(selection, "where", [{ name: { regex } }]));
    }
    for (const flags of ["mm", "ss", "sm", "i", "g", "y", "u", "v", "d", "mi", "msu"]) {
      expectInvalidQuery(() =>
        invokeMethod(selection, "where", [{ name: { regex: { flags, pattern: "ordinary" } } }]),
      );
    }
    for (const pattern of [
      String.raw`(a)\1`,
      "(?=a)a",
      "(?!a)b",
      "(?<=a)b",
      "(?<!a)b",
      "(?<name>a)",
      "(?(1)a|b)",
      "(?i)a",
      String.raw`\d+`,
      String.raw`\p{Letter}`,
      String.raw`\x41`,
      String.raw`\u0041`,
      String.raw`\n`,
      "[a&&b]",
      "[a--b]",
      "(?>a)",
      "a++",
      "a*+",
      "a+?",
      "a{1,2}?",
      "[é]",
      "[À-Ö]",
    ]) {
      expectInvalidQuery(() =>
        invokeMethod(selection, "where", [{ name: { regex: { flags: "", pattern } } }]),
      );
    }
  });

  test("rejects a negated character class", async () => {
    const harness = await createSessionHarness(["a"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    expectInvalidQuery(() => selection.where({ name: { regex: { flags: "", pattern: "[^a]" } } }));
  });

  test("rejects an empty negated character class", async () => {
    const harness = await createSessionHarness(["^"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    expectInvalidQuery(() => selection.where({ name: { regex: { flags: "", pattern: "[^]" } } }));
    expect(selection.count({ name: { regex: { flags: "", pattern: String.raw`[\^]` } } })).toBe(1);
  });

  test("keeps only canonical user regex data in insensitive NoMatchError evidence", async () => {
    const harness = await createSessionHarness(["alpha"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const criteria = {
      name: {
        mode: "insensitive" as const,
        regex: { flags: "" as const, pattern: "^MISSING$" },
      },
    };
    let observed: unknown;
    try {
      selection.one(criteria);
    } catch (error) {
      observed = error;
    }

    criteria.name.regex.pattern = "^alpha$";
    expect(observed).toBeInstanceOf(NoMatchError);
    const noMatch = observed as NoMatchError;
    expect(noMatch.query).toEqual({
      name: {
        mode: "insensitive",
        regex: { flags: "", pattern: "^MISSING$" },
      },
    });
    const encodedQuery = JSON.stringify(noMatch.query);
    expect(encodedQuery).toBe(
      '{"name":{"mode":"insensitive","regex":{"flags":"","pattern":"^MISSING$"}}}',
    );
    expect(encodedQuery).not.toContain('"flags":"u"');
    expect(encodedQuery).not.toContain('"flags":"i"');
    const nameEvidence = Reflect.get(noMatch.query ?? {}, "name") as Record<string, unknown>;
    const regexEvidence = Reflect.get(nameEvidence, "regex");
    expect(regexEvidence).not.toBeInstanceOf(RegExp);
    expect(Reflect.ownKeys(regexEvidence as object)).toEqual(["flags", "pattern"]);
    assertDeepFrozenData(noMatch.query);
  });
});

describe("plain-data validation", () => {
  describe("criteria nesting budget", () => {
    test("accepts depth 64 across compilation, evaluation, and wire round trips", async () => {
      const harness = await createSessionHarness(["alpha"]);
      const criteria = nestedAndCriteria(64);
      const compiled = compileWhere("session", criteria);
      const record = harness.projection.records[0];
      if (record === undefined) throw new Error("fixture has no projected session record");

      expect(compiled.matches(record, () => undefined)).toBe(true);
      const selection = createProjectedSelection("session", harness.values, harness.projection);
      expect(selection.where(criteria as SessionWhere).toArray()).toEqual([...harness.values]);

      const encoded = encodeWhereDocument({
        model: "session",
        version: 1,
        where: criteria as SessionWhere,
      });
      const decoded = decodeWhereDocument(JSON.parse(encoded) as unknown);
      expect(encodeWhereDocument(decoded)).toBe(encoded);
    });

    for (const [name, createCriteria] of [
      ["depth 65", () => nestedAndCriteria(65)],
      ["a 10000-edge prefixed cycle", () => prefixedCriteriaCycle(10_000)],
    ] as const) {
      test(`compileWhere rejects ${name} with invalid-query`, async () => {
        await createSessionHarness(["alpha"]);
        expectInvalidQuery(() => compileWhere("session", createCriteria()));
      });

      test(`Selection.where rejects ${name} with invalid-query`, async () => {
        const harness = await createSessionHarness(["alpha"]);
        const selection = createProjectedSelection("session", harness.values, harness.projection);
        expectInvalidQuery(() => selection.where(createCriteria() as SessionWhere));
      });

      test(`encodeWhereDocument rejects ${name} with invalid-query`, () => {
        expectInvalidQuery(() =>
          encodeWhereDocument({
            model: "session",
            version: 1,
            where: createCriteria() as SessionWhere,
          }),
        );
      });

      test(`decodeWhereDocument rejects ${name} with invalid-query`, () => {
        expectInvalidQuery(() =>
          decodeWhereDocument({
            model: "session",
            version: 1,
            where: createCriteria(),
          }),
        );
      });
    }

    test("retains active-path cycle rejection below the depth budget", () => {
      expectInvalidQuery(() => compileWhere("session", prefixedCriteriaCycle(32)));
    });
  });

  test("accepts null-prototype data and canonically clones it", async () => {
    const harness = await createSessionHarness(["alpha"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const scalar = Object.assign(Object.create(null) as Record<string, unknown>, {
      contains: "missing",
      mode: "insensitive",
    });
    const criteria = Object.assign(Object.create(null) as Record<string, unknown>, {
      name: scalar,
    });
    let error: NoMatchError | undefined;
    try {
      selection.one(criteria as SessionWhere);
    } catch (caught) {
      if (caught instanceof Error && caught.name === "NoMatchError") {
        error = caught as NoMatchError;
      } else {
        throw caught;
      }
    }
    expect(error).toBeDefined();
    scalar.contains = "mutated";
    expect(error?.query).toEqual({ name: { contains: "missing", mode: "insensitive" } });
    assertDeepFrozenData(error?.query);
  });

  test("rejects null, primitive, and Array criteria roots", async () => {
    const harness = await createSessionHarness(["alpha"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);

    for (const criteria of [null, "alpha", 1, Object.assign([], { name: "alpha" })]) {
      expectInvalidQuery(() => invokeMethod(selection, "where", [criteria]));
    }
  });

  test("rejects executable, inherited, sparse, and non-enumerable data", async () => {
    const harness = await createSessionHarness(["alpha"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    let getterCalls = 0;
    let conversionCalls = 0;
    const accessor = Object.create(null) as Record<string, unknown>;
    Object.defineProperty(accessor, "name", {
      enumerable: true,
      get() {
        getterCalls += 1;
        return "alpha";
      },
    });
    const symbolKey = { name: "alpha", [Symbol("private")]: "value" };
    const nonEnumerable = { name: "alpha" };
    Object.defineProperty(nonEnumerable, "hidden", { enumerable: false, value: "value" });
    const customPrototype = Object.create({ inherited: true }) as Record<string, unknown>;
    customPrototype.name = "alpha";
    const sparse: SessionWhere[] = [];
    sparse.length = 2;
    sparse[1] = { name: "alpha" };
    const conversion = {
      name: "alpha",
      toJSON() {
        conversionCalls += 1;
        return { name: "alpha" };
      },
      toString() {
        conversionCalls += 1;
        return "alpha";
      },
    };

    for (const criteria of [
      { name: {} },
      { name: { mode: "insensitive" } },
      accessor,
      symbolKey,
      nonEnumerable,
      customPrototype,
      { name: undefined },
      { name: () => "alpha" },
      { name: /alpha/u },
      { AND: sparse },
      { AND: { name: "alpha" } },
      { OR: null },
      { unknown: "alpha" },
      conversion,
    ]) {
      expectInvalidQuery(() => invokeMethod(selection, "where", [criteria]));
    }
    expect(getterCalls).toBe(0);
    expect(conversionCalls).toBe(0);
  });

  test("rejects invalid modes and malformed membership arrays at every entrypoint", async () => {
    const harness = await createSessionHarness(["alpha"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const invalidCriteriaFactories: ReadonlyArray<() => unknown> = [
      () => ({ name: { equals: "alpha", mode: "default" } }),
      () => ({ name: { equals: "alpha", mode: "INSENSITIVE" } }),
      () => ({ name: { equals: "alpha", mode: "Insensitive" } }),
      () => ({ name: { equals: "alpha", mode: false } }),
      () => {
        const values: string[] = [];
        values.length = 1;
        return { name: { in: values } };
      },
      () => {
        const values: string[] = [];
        values.length = 2;
        values[1] = "beta";
        return { name: { notIn: values } };
      },
      () => ({ name: { in: ["alpha", 1] } }),
      () => ({ name: { notIn: ["alpha", false] } }),
    ];

    for (const makeCriteria of invalidCriteriaFactories) {
      expectInvalidQuery(() => invokeMethod(selection, "where", [makeCriteria()]));
      expectInvalidQuery(() =>
        encodeWhereDocument({
          model: "session",
          version: 1,
          where: makeCriteria(),
        } as never),
      );
      expectInvalidQuery(() =>
        decodeWhereDocument({
          model: "session",
          version: 1,
          where: makeCriteria(),
        }),
      );
    }
  });

  test("rejects recursively nested accessors and conversions without executing them", async () => {
    const harness = await createRichProjectedHarness();
    const sessions = createProjectedSelection(
      "session",
      harness.sessions.values,
      harness.sessions.projection,
    );
    let getterCalls = 0;
    let trapCalls = 0;
    let conversionCalls = 0;
    const scalarSentinel = new Error("nested scalar getter escaped");
    const relationSentinel = new Error("nested relation getter escaped");
    const logicalSentinel = new Error("nested logical getter escaped");

    const scalar = {} as Record<string, unknown>;
    Object.defineProperty(scalar, "contains", {
      enumerable: true,
      get() {
        getterCalls += 1;
        throw scalarSentinel;
      },
    });
    expectInvalidQuery(() => invokeMethod(sessions, "where", [{ name: scalar }]), scalarSentinel);

    const relatedCriteria = {} as Record<string, unknown>;
    Object.defineProperty(relatedCriteria, "title", {
      enumerable: true,
      get() {
        getterCalls += 1;
        throw relationSentinel;
      },
    });
    expectInvalidQuery(
      () => invokeMethod(sessions, "where", [{ panes: { some: relatedCriteria } }]),
      relationSentinel,
    );

    const logicalChild = {} as Record<string, unknown>;
    Object.defineProperty(logicalChild, "name", {
      enumerable: true,
      get() {
        getterCalls += 1;
        throw logicalSentinel;
      },
    });
    expectInvalidQuery(
      () => invokeMethod(sessions, "where", [{ AND: [logicalChild] }]),
      logicalSentinel,
    );

    const proxySentinel = new Error("nested relation proxy trap escaped");
    const relatedProxy = new Proxy(
      { title: "shell" },
      {
        getPrototypeOf() {
          trapCalls += 1;
          throw proxySentinel;
        },
      },
    );
    expectInvalidQuery(
      () => invokeMethod(sessions, "where", [{ panes: { some: relatedProxy } }]),
      proxySentinel,
    );

    const nestedConversion = {
      contains: "alpha",
      toJSON() {
        conversionCalls += 1;
        return { contains: "alpha" };
      },
    };
    expectInvalidQuery(() => invokeMethod(sessions, "where", [{ name: nestedConversion }]));

    expect(getterCalls).toBe(0);
    expect(trapCalls).toBeLessThanOrEqual(1);
    expect(conversionCalls).toBe(0);
  });

  test("wraps hostile reflection without leaking trap exceptions", async () => {
    const harness = await createSessionHarness(["alpha"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    const sentinels = [
      new Error("prototype trap escaped"),
      new Error("ownKeys trap escaped"),
      new Error("descriptor trap escaped"),
    ];
    const hostile = [
      new Proxy(
        {},
        {
          getPrototypeOf() {
            throw sentinels[0];
          },
        },
      ),
      new Proxy(
        {},
        {
          ownKeys() {
            throw sentinels[1];
          },
        },
      ),
      new Proxy(
        { name: "alpha" },
        {
          getOwnPropertyDescriptor() {
            throw sentinels[2];
          },
        },
      ),
    ];

    for (const [index, criteria] of hostile.entries()) {
      expectInvalidQuery(() => invokeMethod(selection, "where", [criteria]), sentinels[index]);
    }
  });

  test("rejects transparent and nonthrowing unstable criteria proxies", async () => {
    const harness = await createSessionHarness(["alpha"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    let conversionCalls = 0;
    const readWithoutConversion = (
      target: Record<string, unknown>,
      property: string | symbol,
      receiver: unknown,
    ): unknown => {
      if (property === "toJSON" || property === "toString") conversionCalls += 1;
      return Reflect.get(target, property, receiver);
    };
    const passive = new Proxy(
      { name: "alpha" },
      {
        get: readWithoutConversion,
      },
    );
    let keysetRead = 0;
    const unstableKeyset = new Proxy(
      { name: "alpha" },
      {
        get: readWithoutConversion,
        ownKeys() {
          keysetRead += 1;
          return keysetRead % 2 === 1 ? ["name"] : [];
        },
      },
    );
    let prototypeRead = 0;
    const unstablePrototype = new Proxy(
      { name: "alpha" },
      {
        get: readWithoutConversion,
        getPrototypeOf() {
          prototypeRead += 1;
          return prototypeRead % 2 === 1 ? Object.prototype : null;
        },
      },
    );

    for (const criteria of [passive, unstableKeyset, unstablePrototype]) {
      expectInvalidQuery(() => invokeMethod(selection, "where", [criteria]));
    }
    expect(conversionCalls).toBe(0);
  });

  test("rejects passive proxies at every recursive criteria position and entrypoint", async () => {
    const harness = await createSessionHarness(["alpha"]);
    const selection = createProjectedSelection("session", harness.values, harness.projection);
    let conversionCalls = 0;
    const passive = (target: Record<string, unknown>): Record<string, unknown> =>
      new Proxy(target, {
        get(value, property, receiver) {
          if (property === "toJSON" || property === "toString") conversionCalls += 1;
          return Reflect.get(value, property, receiver);
        },
      });
    const criteriaFactories: ReadonlyArray<() => unknown> = [
      () => ({ name: passive({ contains: "alpha" }) }),
      () => ({ windows: { some: passive({ name: "shared" }) } }),
      () => ({ AND: [passive({ name: "alpha" })] }),
    ];

    for (const makeCriteria of criteriaFactories) {
      expectInvalidQuery(() => invokeMethod(selection, "where", [makeCriteria()]));
      expectInvalidQuery(() =>
        encodeWhereDocument({
          model: "session",
          version: 1,
          where: makeCriteria(),
        } as never),
      );
      expectInvalidQuery(() =>
        decodeWhereDocument({
          model: "session",
          version: 1,
          where: makeCriteria(),
        }),
      );
    }
    expect(conversionCalls).toBe(0);
  });
});

describe("WhereDocumentV1 serialization", () => {
  test("does not invoke inherited object or array toJSON hooks", () => {
    const script = String.raw`
      import { encodeWhereDocument } from "./src/_internal/selection/serialization.js";

      const document = { model: "session", version: 1, where: { OR: [{ name: "alpha" }] } };
      let objectCalls = 0;
      let arrayCalls = 0;
      let objectEncoded;
      let arrayEncoded;

      try {
        Object.defineProperty(Object.prototype, "toJSON", {
          configurable: true,
          value() {
            objectCalls += 1;
            return "object-hook";
          },
        });
        objectEncoded = encodeWhereDocument(document);
      } finally {
        Reflect.deleteProperty(Object.prototype, "toJSON");
      }

      try {
        Object.defineProperty(Array.prototype, "toJSON", {
          configurable: true,
          value() {
            arrayCalls += 1;
            return "array-hook";
          },
        });
        arrayEncoded = encodeWhereDocument(document);
      } finally {
        Reflect.deleteProperty(Array.prototype, "toJSON");
      }

      process.stdout.write(JSON.stringify({ arrayCalls, arrayEncoded, objectCalls, objectEncoded }));
    `;
    const result = Bun.spawnSync(["bun", "--eval", script], {
      cwd: tsRootPath,
      stderr: "pipe",
      stdout: "pipe",
    });
    expect(result.exitCode, result.stderr.toString()).toBe(0);
    expect(JSON.parse(result.stdout.toString()) as unknown).toEqual({
      arrayCalls: 0,
      arrayEncoded: '{"model":"session","version":1,"where":{"OR":[{"name":"alpha"}]}}',
      objectCalls: 0,
      objectEncoded: '{"model":"session","version":1,"where":{"OR":[{"name":"alpha"}]}}',
    });
  });

  test("round-trips canonical JSON through Zod and freezes the decoded clone", () => {
    const document: WhereDocumentV1 = {
      version: 1,
      model: "session",
      where: {
        OR: [{ name: "main" }, { name: { mode: "insensitive", startsWith: "work" } }],
      },
    };
    const encoded = encodeWhereDocument(document);
    const decoded = decodeWhereDocument(JSON.parse(encoded) as unknown);

    expect(encoded).toBe(
      '{"model":"session","version":1,"where":{"OR":[{"name":"main"},{"name":{"mode":"insensitive","startsWith":"work"}}]}}',
    );
    expect(decoded).toEqual({
      model: "session",
      version: 1,
      where: {
        OR: [{ name: "main" }, { name: { mode: "insensitive", startsWith: "work" } }],
      },
    });
    expect(decoded).not.toBe(document);
    assertDeepFrozenData(decoded);
  });

  test("deeply clones nested null-prototype caller data before freezing", () => {
    const scalar: Record<string, unknown> = Object.assign(
      Object.create(null) as Record<string, unknown>,
      {
        contains: "alpha",
      },
    );
    const relationScalar: Record<string, unknown> = Object.assign(
      Object.create(null) as Record<string, unknown>,
      {
        startsWith: "win",
      },
    );
    const relationChild: Record<string, unknown> = Object.assign(
      Object.create(null) as Record<string, unknown>,
      {
        name: relationScalar,
      },
    );
    const relation: Record<string, unknown> = Object.assign(
      Object.create(null) as Record<string, unknown>,
      {
        some: relationChild,
      },
    );
    const logicalScalar: Record<string, unknown> = Object.assign(
      Object.create(null) as Record<string, unknown>,
      {
        endsWith: "tail",
      },
    );
    const logicalChild: Record<string, unknown> = Object.assign(
      Object.create(null) as Record<string, unknown>,
      {
        name: logicalScalar,
      },
    );
    const logical: Record<string, unknown>[] = [logicalChild];
    const where: Record<string, unknown> = Object.assign(
      Object.create(null) as Record<string, unknown>,
      {
        windows: relation,
        name: scalar,
        AND: logical,
      },
    );
    const document = { where, version: 1, model: "session" };
    const decoded = decodeWhereDocument(document);
    const decodedWhere = decoded.where as unknown as Record<string, unknown>;
    const decodedScalar = Reflect.get(decodedWhere, "name") as Record<string, unknown>;
    const decodedRelation = Reflect.get(decodedWhere, "windows") as Record<string, unknown>;
    const decodedRelationChild = Reflect.get(decodedRelation, "some") as Record<string, unknown>;
    const decodedRelationScalar = Reflect.get(decodedRelationChild, "name");
    const decodedLogical = Reflect.get(decodedWhere, "AND") as unknown[];
    const decodedLogicalChild = decodedLogical[0] as Record<string, unknown>;
    const decodedLogicalScalar = Reflect.get(decodedLogicalChild, "name");

    expect(decoded).not.toBe(document);
    expect(decodedWhere).not.toBe(where);
    expect(decodedScalar).not.toBe(scalar);
    expect(decodedRelation).not.toBe(relation);
    expect(decodedRelationChild).not.toBe(relationChild);
    expect(decodedRelationScalar).not.toBe(relationScalar);
    expect(decodedLogical).not.toBe(logical);
    expect(decodedLogicalChild).not.toBe(logicalChild);
    expect(decodedLogicalScalar).not.toBe(logicalScalar);
    for (const callerValue of [
      document,
      where,
      scalar,
      relation,
      relationChild,
      relationScalar,
      logical,
      logicalChild,
      logicalScalar,
    ]) {
      expect(Object.isFrozen(callerValue)).toBe(false);
    }

    document.model = "window";
    where.name = Object.assign(Object.create(null) as Record<string, unknown>, {
      equals: "mutated",
    });
    scalar.contains = "mutated";
    relation.some = Object.assign(Object.create(null) as Record<string, unknown>, {});
    relationChild.name = "mutated";
    relationScalar.startsWith = "mutated";
    logicalChild.name = "mutated";
    logicalScalar.endsWith = "mutated";
    logical.push(Object.assign(Object.create(null) as Record<string, unknown>, {}));
    expect(decoded).toEqual({
      model: "session",
      version: 1,
      where: {
        AND: [{ name: { endsWith: "tail" } }],
        name: { contains: "alpha" },
        windows: { some: { name: { startsWith: "win" } } },
      },
    });
    assertDeepFrozenData(decoded);
  });

  test("canonically round-trips Window, Pane, and null-prototype documents", () => {
    const windowDocument = {
      where: {
        session: {
          isNot: null,
          is: { name: { startsWith: "w", contains: "or" } },
        },
        name: { startsWith: "z", contains: "a" },
      },
      version: 1 as const,
      model: "window" as const,
    };
    const paneDocument = {
      where: {
        window: { isNot: null, is: { name: "editor" } },
        title: {
          regex: { pattern: "^X.*$", flags: "ms" as const },
          mode: "insensitive" as const,
          equals: "X\nY",
        },
      },
      version: 1 as const,
      model: "pane" as const,
    };
    const windowBytes = encodeWhereDocument(windowDocument);
    const paneBytes = encodeWhereDocument(paneDocument);

    expect(windowBytes).toBe(
      '{"model":"window","version":1,"where":{"name":{"contains":"a","startsWith":"z"},"session":{"is":{"name":{"contains":"or","startsWith":"w"}},"isNot":null}}}',
    );
    expect(paneBytes).toBe(
      '{"model":"pane","version":1,"where":{"pane_title":{"equals":"X\\nY","mode":"insensitive","regex":{"flags":"ms","pattern":"^X.*$"}},"window":{"is":{"name":"editor"},"isNot":null}}}',
    );
    expect(paneBytes).not.toContain('"flags":"u"');
    expect(paneBytes).not.toContain('"flags":"i"');

    for (const [bytes, model] of [
      [windowBytes, "window"],
      [paneBytes, "pane"],
    ] as const) {
      const decoded = decodeWhereDocument(JSON.parse(bytes) as unknown);
      expect(decoded.model).toBe(model);
      expect(Object.isFrozen(decoded.where)).toBe(true);
      assertDeepFrozenData(decoded);
      expect(encodeWhereDocument(decoded)).toBe(bytes);
    }

    const nullScalar = Object.assign(Object.create(null) as Record<string, unknown>, {
      startsWith: "m",
      contains: "a",
    });
    const nullWhere = Object.assign(Object.create(null) as Record<string, unknown>, {
      name: nullScalar,
    });
    const nullDocument = Object.assign(Object.create(null) as Record<string, unknown>, {
      where: nullWhere,
      version: 1,
      model: "session",
    });
    const directNullDecoded = decodeWhereDocument(nullDocument);
    expect(directNullDecoded).toEqual({
      model: "session",
      version: 1,
      where: { name: { contains: "a", startsWith: "m" } },
    });
    expect(directNullDecoded).not.toBe(nullDocument);
    assertDeepFrozenData(directNullDecoded);
    const nullBytes = encodeWhereDocument(nullDocument as never);
    expect(nullBytes).toBe(
      '{"model":"session","version":1,"where":{"name":{"contains":"a","startsWith":"m"}}}',
    );
    const nullDecoded = decodeWhereDocument(JSON.parse(nullBytes) as unknown);
    expect(nullDecoded.model).toBe("session");
    assertDeepFrozenData(nullDecoded);
    expect(encodeWhereDocument(nullDecoded)).toBe(nullBytes);
  });

  test("rejects non-plain document shapes in both wire entrypoints", () => {
    let hookCalls = 0;
    const customPrototype = Object.create({
      toJSON() {
        hookCalls += 1;
        return { model: "session", version: 1, where: {} };
      },
      toString() {
        hookCalls += 1;
        return "session";
      },
    }) as Record<string, unknown>;
    Object.assign(customPrototype, { model: "session", version: 1, where: {} });
    const symbolKey = {
      model: "session",
      version: 1,
      where: {},
      [Symbol("private")]: "value",
    };
    const nonEnumerable = { model: "session", version: 1, where: {} };
    Object.defineProperty(nonEnumerable, "hidden", { enumerable: false, value: "value" });

    for (const document of [customPrototype, symbolKey, nonEnumerable]) {
      expectInvalidQuery(() => encodeWhereDocument(document as never));
      expectInvalidQuery(() => decodeWhereDocument(document));
    }
    expect(hookCalls).toBe(0);
  });

  test("rejects unknown versions, models, aliases, fields, operators, and values", () => {
    for (const document of [
      { version: 2, model: "session", where: {} },
      { version: 1, model: "client", where: {} },
      { version: 1, model: "session", where: {}, extra: true },
      { version: 1, model: "session", where: { session_name: "main" } },
      { version: 1, model: "session", where: { pane_id: "%1" } },
      { version: 1, model: "session", where: { name: { unknown: "main" } } },
      { version: 1, model: "session", where: { name: { contains: 1 } } },
      { version: 1, model: "session", where: { name: { contains: () => "main" } } },
      { version: 1, model: "session", where: { name: /main/u } },
      { version: 1, model: "session", where: { name: { regex: { flags: "i", pattern: "main" } } } },
    ]) {
      expectInvalidQuery(() => decodeWhereDocument(document));
      expectInvalidQuery(() => encodeWhereDocument(document as never));
    }
  });

  test("requires every wire field and an ordinary document container", () => {
    for (const document of [
      { model: "session", where: {} },
      { version: 1, where: {} },
      { model: "session", version: 1 },
      null,
      Object.assign([], { model: "session", version: 1, where: {} }),
      "session",
    ]) {
      expectInvalidQuery(() => encodeWhereDocument(document as never));
      expectInvalidQuery(() => decodeWhereDocument(document));
    }
  });

  test("rejects invalid criteria containers inside a valid wire envelope", () => {
    for (const where of [null, [], "x"]) {
      expectInvalidQuery(() =>
        encodeWhereDocument({ model: "session", version: 1, where } as never),
      );
      expectInvalidQuery(() => decodeWhereDocument({ model: "session", version: 1, where }));
    }
  });

  test("rejects nested hostile document contents without executing them", () => {
    let getterCalls = 0;
    let trapCalls = 0;
    let conversionCalls = 0;
    const encodeSentinel = new Error("encode nested getter escaped");
    const decodeSentinel = new Error("decode nested getter escaped");

    const encodeWhere = {} as Record<string, unknown>;
    Object.defineProperty(encodeWhere, "name", {
      enumerable: true,
      get() {
        getterCalls += 1;
        throw encodeSentinel;
      },
    });
    expectInvalidQuery(
      () => encodeWhereDocument({ model: "session", version: 1, where: encodeWhere } as never),
      encodeSentinel,
    );

    const decodeChild = {} as Record<string, unknown>;
    Object.defineProperty(decodeChild, "name", {
      enumerable: true,
      get() {
        getterCalls += 1;
        throw decodeSentinel;
      },
    });
    expectInvalidQuery(
      () =>
        decodeWhereDocument({
          model: "session",
          version: 1,
          where: { OR: [decodeChild] },
        }),
      decodeSentinel,
    );

    const proxySentinel = new Error("decode nested proxy trap escaped");
    const decodeProxy = new Proxy(
      { name: "main" },
      {
        ownKeys() {
          trapCalls += 1;
          throw proxySentinel;
        },
      },
    );
    expectInvalidQuery(
      () =>
        decodeWhereDocument({
          model: "session",
          version: 1,
          where: { OR: [decodeProxy] },
        }),
      proxySentinel,
    );

    const encodeConversion = {
      equals: "main",
      toJSON() {
        conversionCalls += 1;
        return { equals: "main" };
      },
    };
    expectInvalidQuery(() =>
      encodeWhereDocument({
        model: "session",
        version: 1,
        where: { name: encodeConversion },
      } as never),
    );

    const decodeConversion = {
      equals: "main",
      toString() {
        conversionCalls += 1;
        return "main";
      },
    };
    expectInvalidQuery(() =>
      decodeWhereDocument({
        model: "session",
        version: 1,
        where: { name: decodeConversion },
      }),
    );

    expect(getterCalls).toBe(0);
    expect(trapCalls).toBeLessThanOrEqual(1);
    expect(conversionCalls).toBe(0);
  });

  test("rejects transparent and nonthrowing unstable document proxies", () => {
    let conversionCalls = 0;
    const readWithoutConversion = (
      target: Record<string, unknown>,
      property: string | symbol,
      receiver: unknown,
    ): unknown => {
      if (property === "toJSON" || property === "toString") conversionCalls += 1;
      return Reflect.get(target, property, receiver);
    };
    const makePassiveDocument = (): unknown =>
      new Proxy(
        { model: "session", version: 1, where: { name: "main" } },
        { get: readWithoutConversion },
      );
    const makeUnstableKeysetDocument = (): unknown => {
      let keysetRead = 0;
      const where = new Proxy(
        { name: "main" },
        {
          get: readWithoutConversion,
          ownKeys() {
            keysetRead += 1;
            return keysetRead % 2 === 1 ? ["name"] : [];
          },
        },
      );
      return { model: "session", version: 1, where };
    };
    const makeUnstablePrototypeDocument = (): unknown => {
      let prototypeRead = 0;
      const where = new Proxy(
        { name: "main" },
        {
          get: readWithoutConversion,
          getPrototypeOf() {
            prototypeRead += 1;
            return prototypeRead % 2 === 1 ? Object.prototype : null;
          },
        },
      );
      return { model: "session", version: 1, where };
    };

    for (const factory of [
      makePassiveDocument,
      makeUnstableKeysetDocument,
      makeUnstablePrototypeDocument,
    ]) {
      expectInvalidQuery(() => encodeWhereDocument(factory() as never));
      expectInvalidQuery(() => decodeWhereDocument(factory()));
    }
    expect(conversionCalls).toBe(0);
  });
});

void ({} as PaneWhere);
void ({} as WindowWhere);
