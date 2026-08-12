import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "bun:test";

type Status = "planned" | "implemented" | "adapted" | "unsupported";
type EvidenceApplicability = "required" | `not-applicable: ${string}`;

interface EvidenceRecord {
  declarationTest: string | null;
  evidenceApplicability: {
    declarationTest: EvidenceApplicability;
    realTmuxScenario: EvidenceApplicability;
    unitTest: EvidenceApplicability;
  };
  realTmuxScenario: string | null;
  status: Status;
  typescriptSymbols: string[];
  unitTest: string | null;
}

interface PublicSymbol extends EvidenceRecord {
  adaptation: string | null;
  kind: string;
  owner: string;
  python: string;
  reason: string | null;
  source: string;
  typescript: string | null;
}

interface ObservableBehavior extends EvidenceRecord {
  adaptation: string;
  id: string;
  owners: string[];
  pythonEvidence: string[];
  reason: string | null;
  typescript: string | null;
}

interface TypeScriptExtension extends EvidenceRecord {
  id: string;
  rationale: string;
  reason: string | null;
  typescript: string;
}

interface InternalExclusion extends EvidenceRecord {
  id: string;
  pythonEvidence: string[];
  reason: string;
}

interface ParityManifest {
  baseline: {
    commit: string;
    pythonVersion: string;
    tag: string;
  };
  internalExclusions: InternalExclusion[];
  observableBehaviors: ObservableBehavior[];
  publicSymbols: PublicSymbol[];
  runtimeBoundary: {
    excludes: string[];
    includes: string;
  };
  schemaVersion: number;
  typescriptExtensions: TypeScriptExtension[];
}

const tsRoot = new URL("../..", import.meta.url);
const tsRootPath = fileURLToPath(tsRoot);
const manifestUrl = new URL("parity/python-0.62.0.json", tsRoot);
const baselineCommit = "38e368c11117fb4aeb2f082d552cd4f210eae06a";

const expectedKindCounts = {
  class: 16,
  "compatibility-alias": 45,
  constant: 23,
  "enum-member": 14,
  exception: 27,
  "format-field": 178,
  function: 21,
  method: 138,
  property: 22,
  "root-export": 5,
  "test-helper": 24,
};

const sectionDigests = {
  publicSymbols: "ca2220899befed0f3b33a90bf7c9b4f1b1cf4f76cb7aa3deb5f8dacbb7953cc9",
  observableBehaviors: "10ad51725168aa5256a42dc42208b468bf402a263eba1b902724860f1b891c1d",
  typescriptExtensions: "c66732f77406dc5d43359cf070cdd53626366e5074fc5c2e9722592660b2bbd2",
  internalExclusions: "f486533595a7aa3093d8babf687632704afa6a81fd4121992ae948bc535c03f9",
};

const requiredPublicSymbols = [
  "root-export:libtmux.Client",
  "root-export:libtmux.Pane",
  "root-export:libtmux.Server",
  "root-export:libtmux.Session",
  "root-export:libtmux.Window",
  "enum-member:libtmux.constants.ResizeAdjustmentDirection.Up",
  "enum-member:libtmux.constants.ResizeAdjustmentDirection.Down",
  "enum-member:libtmux.constants.ResizeAdjustmentDirection.Left",
  "enum-member:libtmux.constants.ResizeAdjustmentDirection.Right",
  "enum-member:libtmux.constants.WindowDirection.Before",
  "enum-member:libtmux.constants.WindowDirection.After",
  "enum-member:libtmux.constants.PaneDirection.Above",
  "enum-member:libtmux.constants.PaneDirection.Below",
  "enum-member:libtmux.constants.PaneDirection.Right",
  "enum-member:libtmux.constants.PaneDirection.Left",
  "enum-member:libtmux.constants.OptionScope.Server",
  "enum-member:libtmux.constants.OptionScope.Session",
  "enum-member:libtmux.constants.OptionScope.Window",
  "enum-member:libtmux.constants.OptionScope.Pane",
  "test-helper:libtmux.test.random.namer",
] as const;

const requiredBehaviors = [
  "accessor.attached-sessions-exact-one",
  "accessor.error-linked-sessions",
  "accessor.error-missing-daemon-topology",
  "accessor.error-point-lookup",
  "accessor.error-propagating-relations",
  "accessor.error-schema-protocol",
  "accessor.error-server-list-leniency",
  "client.structural-equality",
  "cmd-protocol.call",
  "collection.callable-filter",
  "collection.cardinality",
  "collection.client-callback-lookup",
  "collection.contextual-duplicates",
  "collection.default-retrieval",
  "collection.eager-snapshots",
  "collection.exact-retrieval",
  "collection.inherited-concatenation",
  "collection.inherited-containment",
  "collection.inherited-copy",
  "collection.inherited-count-value",
  "collection.inherited-first",
  "collection.inherited-index",
  "collection.inherited-repetition",
  "collection.inherited-reverse",
  "collection.inherited-slicing",
  "collection.iteration-order-duplicates",
  "collection.lookup-operators",
  "collection.query-errors",
  "collection.truthiness",
  "collection.value-list-filter",
  "collection.zero-argument-filter",
  "context.pane",
  "context.server",
  "context.session",
  "context.window",
  "environment-var-guard.context",
  "equality.pane",
  "equality.server",
  "equality.session",
  "equality.window",
  "random-str-sequence.iteration",
  "repr.core-handles",
  "subscription.pane",
  "subscription.session",
  "subscription.window",
] as const;

const requiredCollectionProducers = [
  "libtmux.server.Server.sessions",
  "libtmux.server.Server.clients",
  "libtmux.server.Server.attached_sessions",
  "libtmux.server.Server.windows",
  "libtmux.server.Server.panes",
  "libtmux.server.Server.search_sessions",
  "libtmux.server.Server.search_windows",
  "libtmux.server.Server.search_panes",
  "libtmux.session.Session.windows",
  "libtmux.session.Session.panes",
  "libtmux.session.Session.search_windows",
  "libtmux.session.Session.search_panes",
  "libtmux.window.Window.panes",
  "libtmux.window.Window.linked_sessions",
  "libtmux.window.Window.search_panes",
] as const;

const requiredRealTmuxSymbols = [
  "libtmux.common.tmux_cmd",
  "libtmux.common.get_version",
  "libtmux.common.get_version_str",
  "libtmux.common.has_gt_version",
  "libtmux.common.has_gte_version",
  "libtmux.common.has_lt_version",
  "libtmux.common.has_lte_version",
  "libtmux.common.has_minimum_version",
  "libtmux.common.has_version",
  "libtmux.neo.fetch_obj",
  "libtmux.neo.fetch_objs",
  "libtmux.pytest_plugin.TestServer",
  "libtmux.pytest_plugin.control_mode",
  "libtmux.pytest_plugin.server",
  "libtmux.pytest_plugin.session",
  "libtmux.test.temporary.temp_session",
  "libtmux.test.temporary.temp_window",
] as const;

const genericCollectionBehaviors = [
  "collection.callable-filter",
  "collection.cardinality",
  "collection.default-retrieval",
  "collection.eager-snapshots",
  "collection.exact-retrieval",
  "collection.inherited-concatenation",
  "collection.inherited-containment",
  "collection.inherited-copy",
  "collection.inherited-count-value",
  "collection.inherited-first",
  "collection.inherited-index",
  "collection.inherited-repetition",
  "collection.inherited-reverse",
  "collection.inherited-slicing",
  "collection.iteration-order-duplicates",
  "collection.query-errors",
  "collection.truthiness",
  "collection.value-list-filter",
  "collection.zero-argument-filter",
] as const;

const requiredExtensions = [
  "client-where-never",
  "explicit-null-criteria",
  "logical-criteria",
  "multiple-matches-error",
  "no-match-error",
  "pane-where",
  "parse-legacy-where",
  "query-validation-error",
  "regex-data-grammar",
  "relation-quantifiers",
  "selection",
  "session-where",
  "where-document-v1",
  "window-where",
] as const;

const requiredExclusions = [
  "generic-double-underscore-parser",
  "list-valued-scalar-lookups",
  "mapping-valued-scalar-lookups",
  "pane-client-legacy-contains",
  "pytest-plugin-using-zsh",
  "python-type-only-aliases",
  "query-list-equality",
  "query-list-indexing-and-list-methods",
  "query-list-items-and-pk-key",
  "query-list-mutation",
  "query-list-public-surface",
  "unstable-internal-symbols",
  "unsupported-lookup-combinations",
] as const;

async function readManifest(path: string | URL = manifestUrl): Promise<ParityManifest> {
  return JSON.parse(await readFile(path, "utf8")) as ParityManifest;
}

function digest(values: readonly string[]): string {
  return createHash("sha256")
    .update(`${[...values].sort().join("\n")}\n`)
    .digest("hex");
}

async function runChecker(...arguments_: string[]) {
  const process = Bun.spawn(["bun", "scripts/check-parity.ts", ...arguments_], {
    cwd: tsRootPath,
    stderr: "pipe",
    stdout: "pipe",
  });
  const [exitCode, stdout, stderr] = await Promise.all([
    process.exited,
    new Response(process.stdout).text(),
    new Response(process.stderr).text(),
  ]);
  return { exitCode, stderr, stdout };
}

function parityCheckerTest(name: string, body: () => Promise<void>): void {
  test(name, body, 30_000);
}

async function withTemporaryFile<T>(
  prefix: string,
  filename: string,
  source: string | URL,
  use: (path: string) => Promise<T>,
): Promise<T> {
  return withTemporaryDirectory(prefix, async (directory) => {
    const path = join(directory, filename);
    await writeFile(path, await readFile(source));
    return use(path);
  });
}

async function withTemporaryDirectory<T>(
  prefix: string,
  use: (path: string) => Promise<T>,
): Promise<T> {
  const directory = await mkdtemp(join(tmpdir(), prefix));
  try {
    return await use(directory);
  } finally {
    await rm(directory, { force: true, recursive: true });
  }
}

function withTemporaryManifest<T>(use: (path: string) => Promise<T>): Promise<T> {
  return withTemporaryFile("libtmux-parity-", "manifest.json", manifestUrl, use);
}

function withTemporaryPackageManifest<T>(use: (path: string) => Promise<T>): Promise<T> {
  return withTemporaryFile(
    "libtmux-package-",
    "package.json",
    new URL("package.json", tsRoot),
    use,
  );
}

describe("Python 0.62.0 parity manifest", () => {
  test("pins the release baseline and explicit audited runtime boundary", async () => {
    const manifest = await readManifest();

    expect(manifest.schemaVersion).toBe(2);
    expect(manifest.baseline).toEqual({
      pythonVersion: "0.62.0",
      tag: "v0.62.0",
      commit: baselineCommit,
    });
    expect(manifest.runtimeBoundary.includes).toContain("public runtime");
    expect(manifest.runtimeBoundary.excludes).toEqual([
      "Python type-only aliases",
      "unstable _internal symbols",
      "private QueryList symbols and exports",
    ]);
  });

  test("classifies the exact public runtime symbols independently", async () => {
    const manifest = await readManifest();
    const classified = manifest.publicSymbols.map(({ kind, python }) => `${kind}:${python}`);
    const counts = Object.fromEntries(
      Object.keys(expectedKindCounts).map((kind) => [
        kind,
        manifest.publicSymbols.filter((entry) => entry.kind === kind).length,
      ]),
    );

    expect(manifest.publicSymbols).toHaveLength(513);
    expect(new Set(classified).size).toBe(513);
    expect(counts).toEqual(expectedKindCounts);
    expect(digest(classified)).toBe(sectionDigests.publicSymbols);
    for (const sentinel of requiredPublicSymbols) expect(classified).toContain(sentinel);
    expect(classified).not.toContain("test-helper:libtmux.pytest_plugin.USING_ZSH");
    expect(manifest.publicSymbols.some((entry) => entry.python.includes("QueryList"))).toBe(false);
    expect(manifest.publicSymbols.some((entry) => entry.python.includes("._internal."))).toBe(
      false,
    );
  });

  test("activates exactly the Task 5 pure symbols while deferring executor-owned parity", async () => {
    const manifest = await readManifest();
    const task5Rows = manifest.publicSymbols.filter(({ unitTest }) =>
      ["tests/unit/formats.test.ts", "tests/unit/neo.test.ts"].includes(unitTest ?? ""),
    );

    expect(task5Rows).toHaveLength(188);
    expect(task5Rows.filter(({ status }) => status === "implemented")).toHaveLength(7);
    expect(task5Rows.filter(({ status }) => status === "adapted")).toHaveLength(181);
    for (const row of task5Rows) {
      expect(row.typescript).not.toBeNull();
      expect(row.typescriptSymbols.length).toBeGreaterThan(0);
      expect(row.declarationTest).toMatch(/^tests\/types\/(formats|neo)\.test\.ts$/u);
      expect(row.evidenceApplicability).toEqual({
        declarationTest: "required",
        realTmuxScenario: "not-applicable: symbol has no direct tmux I/O behavior",
        unitTest: "required",
      });
      expect(row.realTmuxScenario).toBeNull();
    }

    for (const python of ["libtmux.neo.fetch_obj", "libtmux.neo.fetch_objs"]) {
      expect(manifest.publicSymbols.find((row) => row.python === python)).toMatchObject({
        declarationTest: null,
        realTmuxScenario: null,
        status: "planned",
        typescript: null,
        typescriptSymbols: [],
        unitTest: null,
      });
    }
    for (const id of ["accessor.error-point-lookup", "accessor.error-schema-protocol"]) {
      expect(manifest.observableBehaviors.find((row) => row.id === id)).toMatchObject({
        declarationTest: null,
        realTmuxScenario: null,
        status: "planned",
        typescriptSymbols: [],
        unitTest: null,
      });
    }
    for (const id of [
      "session-where",
      "window-where",
      "pane-where",
      "client-where-never",
      "where-document-v1",
      "parse-legacy-where",
    ]) {
      expect(manifest.typescriptExtensions.find((row) => row.id === id)).toMatchObject({
        declarationTest: null,
        realTmuxScenario: null,
        status: "planned",
        typescriptSymbols: [],
        unitTest: null,
      });
    }
  });

  test("records the accepted behavior, extension, and exclusion sets", async () => {
    const manifest = await readManifest();
    const behaviorIds = manifest.observableBehaviors.map(({ id }) => id);
    const extensionIds = manifest.typescriptExtensions.map(({ id }) => id);
    const exclusionIds = manifest.internalExclusions.map(({ id }) => id);

    expect(behaviorIds).toEqual([...requiredBehaviors]);
    expect(extensionIds).toEqual([...requiredExtensions]);
    expect(exclusionIds).toEqual([...requiredExclusions]);
    expect(digest(behaviorIds)).toBe(sectionDigests.observableBehaviors);
    expect(digest(extensionIds)).toBe(sectionDigests.typescriptExtensions);
    expect(digest(exclusionIds)).toBe(sectionDigests.internalExclusions);

    for (const behavior of manifest.observableBehaviors) {
      expect(behavior.owners.length).toBeGreaterThan(0);
      for (const owner of behavior.owners) expect(owner).not.toContain("QueryList");
    }
    for (const records of [
      manifest.publicSymbols,
      manifest.observableBehaviors,
      manifest.typescriptExtensions,
      manifest.internalExclusions,
    ]) {
      for (const record of records) {
        expect(Array.isArray(record.typescriptSymbols)).toBe(true);
        expect(Object.keys(record.evidenceApplicability)).toEqual([
          "declarationTest",
          "realTmuxScenario",
          "unitTest",
        ]);
        for (const applicability of Object.values(record.evidenceApplicability)) {
          expect(applicability === "required" || /^not-applicable: \S/.test(applicability)).toBe(
            true,
          );
        }
      }
    }
    expect(
      manifest.internalExclusions.find(({ id }) => id === "query-list-public-surface"),
    ).toMatchObject({
      declarationTest: "tests/fixtures/negative-declarations/query_list.test.ts",
      evidenceApplicability: { declarationTest: "required" },
      status: "unsupported",
      unitTest: "tests/unit/parity_manifest.test.ts",
    });

    for (const symbol of manifest.publicSymbols) {
      if (["method", "compatibility-alias", "property"].includes(symbol.kind)) {
        expect(symbol.evidenceApplicability.realTmuxScenario).toBe("required");
      }
    }
    for (const python of requiredRealTmuxSymbols) {
      expect(
        manifest.publicSymbols.find((symbol) => symbol.python === python)?.evidenceApplicability
          .realTmuxScenario,
      ).toBe("required");
    }
    expect(
      manifest.publicSymbols.find((symbol) => symbol.python === "libtmux.pane.Pane.send_keys")
        ?.evidenceApplicability.realTmuxScenario,
    ).toBe("required");
  });

  test("records the collection, equality, context, and compatibility mappings exactly", async () => {
    const manifest = await readManifest();
    const behavior = new Map(manifest.observableBehaviors.map((entry) => [entry.id, entry]));
    const extension = new Map(manifest.typescriptExtensions.map((entry) => [entry.id, entry]));

    expect(behavior.get("accessor.attached-sessions-exact-one")).toMatchObject({
      owners: ["libtmux.server.Server.attached_sessions"],
      typescript: "Server.attached_sessions()",
    });
    expect(behavior.get("accessor.attached-sessions-exact-one")?.adaptation).toContain(
      'session_attached === "1"',
    );
    expect(
      manifest.publicSymbols.find(({ python }) => python === "libtmux.Client")?.typescriptSymbols,
    ).toEqual([".#value:Client"]);
    expect(
      manifest.publicSymbols.find(({ python }) => python === "libtmux.constants.OptionScope.Pane")
        ?.typescriptSymbols,
    ).toEqual(["./constants#value:OptionScope.Pane"]);
    expect(behavior.get("accessor.error-server-list-leniency")?.owners).toEqual([
      "libtmux.server.Server.sessions",
      "libtmux.server.Server.clients",
      "libtmux.server.Server.attached_sessions",
    ]);
    expect(behavior.get("accessor.error-server-list-leniency")?.adaptation).toContain(
      "missing executable",
    );
    expect(behavior.get("accessor.error-missing-daemon-topology")?.adaptation).toContain(
      "permission failures propagate",
    );
    expect(behavior.get("accessor.error-propagating-relations")?.adaptation).toContain(
      "all recognized command and transport failures",
    );
    expect(behavior.get("accessor.error-linked-sessions")?.adaptation).toContain(
      "vanished sessions",
    );
    expect(behavior.get("accessor.error-point-lookup")?.adaptation).toContain(
      "recognized missing target",
    );
    expect(behavior.get("accessor.error-schema-protocol")?.adaptation).toContain(
      "Malformed rows and protocol failures always propagate",
    );
    for (const id of genericCollectionBehaviors) {
      expect(behavior.get(id)?.owners).toEqual([...requiredCollectionProducers]);
    }
    expect(behavior.get("collection.lookup-operators")?.owners).toEqual(
      requiredCollectionProducers.filter((owner) => owner !== "libtmux.server.Server.clients"),
    );

    expect(behavior.get("collection.callable-filter")).toMatchObject({
      typescript: "Selection.filter(predicate, thisArg?)",
      adaptation: "Predicate-only eager filtering; no zero-argument or declarative overload",
    });
    expect(behavior.get("collection.cardinality")?.typescript).toBe(
      "Selection.first/one/oneOrUndefined/exists/count",
    );
    expect(behavior.get("collection.client-callback-lookup")?.owners).toEqual([
      "libtmux.server.Server.clients",
    ]);
    expect(behavior.get("collection.lookup-operators")?.adaptation).toContain("canonical criteria");
    expect(behavior.get("equality.server")?.adaptation).toContain("socket_name and socket_path");
    for (const owner of ["session", "window", "pane"] as const) {
      expect(behavior.get(`equality.${owner}`)?.adaptation).toContain("raw owner ID only");
      expect(behavior.get(`context.${owner}`)?.typescript).toContain("Symbol.asyncDispose");
    }
    expect(behavior.get("client.structural-equality")?.adaptation).toContain("exact class");
    expect(behavior.get("environment-var-guard.context")?.owners).toEqual([
      "libtmux.test.environment.EnvironmentVarGuard",
    ]);
    expect(behavior.get("random-str-sequence.iteration")?.owners).toEqual([
      "libtmux.test.random.RandomStrSequence",
    ]);

    expect(extension.get("selection")?.typescript).toBe("Selection<T>");
    expect(extension.get("session-where")?.typescript).toBe("SessionWhere");
    expect(extension.get("window-where")?.typescript).toBe("WindowWhere");
    expect(extension.get("pane-where")?.typescript).toBe("PaneWhere");
    expect(extension.get("client-where-never")?.typescript).toBe("WhereOf<Client> = never");
    expect(extension.get("parse-legacy-where")?.typescript).toBe("parseLegacyWhere(model, input)");
    expect(
      manifest.internalExclusions.find(({ id }) => id === "generic-double-underscore-parser")
        ?.reason,
    ).toContain("noeq");
    expect(extension.get("no-match-error")?.typescript).toBe(
      "NoMatchError extends ObjectDoesNotExist",
    );
    expect(extension.get("multiple-matches-error")?.typescript).toBe(
      "MultipleMatchesError extends MultipleObjectsReturned",
    );
  });

  const invalidCases: Array<[string, (manifest: ParityManifest) => void, string]> = [
    [
      "unknown status",
      (manifest) => {
        manifest.publicSymbols[0]!.status = "done" as Status;
      },
      "invalid status",
    ],
    [
      "not-applicable lane without a reason",
      (manifest) => {
        manifest.publicSymbols[0]!.evidenceApplicability.realTmuxScenario =
          "not-applicable:" as EvidenceApplicability;
      },
      "must be required or include a not-applicable reason",
    ],
    [
      "evidence in a not-applicable lane",
      (manifest) => {
        manifest.publicSymbols[0]!.realTmuxScenario = "tests/integration/client.test.ts";
      },
      "realTmuxScenario must be null when its evidence lane is not applicable",
    ],
    [
      "implemented without unit evidence",
      (manifest) => {
        manifest.publicSymbols[0]!.status = "implemented";
        manifest.publicSymbols[0]!.typescript = "Client";
        manifest.publicSymbols[0]!.typescriptSymbols = [".#value:Client"];
        manifest.publicSymbols[0]!.declarationTest = "tests/types/client.test.ts";
        manifest.publicSymbols[0]!.unitTest = null;
      },
      "activated records require unitTest evidence",
    ],
    [
      "public type without declaration evidence",
      (manifest) => {
        manifest.publicSymbols[0]!.status = "implemented";
        manifest.publicSymbols[0]!.typescript = "Client";
        manifest.publicSymbols[0]!.typescriptSymbols = [".#value:Client"];
        manifest.publicSymbols[0]!.unitTest = "tests/unit/client.test.ts";
        manifest.publicSymbols[0]!.declarationTest = null;
      },
      "activated records require declarationTest evidence",
    ],
    [
      "I/O behavior without real tmux evidence",
      (manifest) => {
        const behavior = manifest.observableBehaviors.find(
          ({ id }) => id === "accessor.attached-sessions-exact-one",
        )!;
        behavior.status = "adapted";
        behavior.typescriptSymbols = ["./server#instance:Server.attached_sessions"];
        behavior.unitTest = "tests/unit/server.test.ts";
        behavior.declarationTest = "tests/types/server.test.ts";
        behavior.realTmuxScenario = null;
      },
      "activated records require realTmuxScenario evidence",
    ],
    [
      "nonexistent evidence path",
      (manifest) => {
        const symbol = manifest.publicSymbols.find(
          ({ python }) => python === "libtmux.client.Client",
        )!;
        symbol.status = "implemented";
        symbol.typescript = "Client";
        symbol.typescriptSymbols = [".#value:Client"];
        symbol.unitTest = "tests/unit/does-not-exist.test.ts";
        symbol.declarationTest = "tests/types/does-not-exist.test.ts";
      },
      "evidence path does not exist",
    ],
    [
      "escaping evidence path",
      (manifest) => {
        manifest.internalExclusions[0]!.unitTest = "../outside.test.ts";
      },
      "invalid unitTest evidence path",
    ],
    [
      "missing required QueryList declaration evidence",
      (manifest) => {
        const exclusion = manifest.internalExclusions.find(
          ({ id }) => id === "query-list-public-surface",
        )!;
        exclusion.declarationTest = null;
      },
      "activated records require declarationTest evidence",
    ],
    [
      "nonexistent TypeScript symbol",
      (manifest) => {
        const symbol = manifest.publicSymbols.find(
          ({ python }) => python === "libtmux.client.Client",
        )!;
        symbol.status = "implemented";
        symbol.typescript = "DefinitelyMissing";
        symbol.typescriptSymbols = [".#value:DefinitelyMissing"];
        symbol.unitTest = "tests/unit/parity_manifest.test.ts";
        symbol.declarationTest = "tests/fixtures/negative-declarations/query_list.test.ts";
      },
      "TypeScript symbol does not exist",
    ],
    [
      "unexported TypeScript module",
      (manifest) => {
        const symbol = manifest.publicSymbols.find(
          ({ python }) => python === "libtmux.client.Client",
        )!;
        symbol.status = "implemented";
        symbol.typescript = "Client";
        symbol.typescriptSymbols = ["./client#value:Client"];
        symbol.unitTest = "tests/unit/parity_manifest.test.ts";
        symbol.declarationTest = "tests/fixtures/negative-declarations/query_list.test.ts";
      },
      "TypeScript module is not exported",
    ],
    [
      "malformed TypeScript locator",
      (manifest) => {
        const symbol = manifest.publicSymbols.find(
          ({ python }) => python === "libtmux.client.Client",
        )!;
        symbol.status = "implemented";
        symbol.typescript = "Client";
        symbol.typescriptSymbols = ["DefinitelyMissing"];
        symbol.unitTest = "tests/unit/parity_manifest.test.ts";
        symbol.declarationTest = "tests/fixtures/negative-declarations/query_list.test.ts";
      },
      "invalid TypeScript symbol locator",
    ],
    [
      "malformed planned TypeScript locator",
      (manifest) => {
        const symbol = manifest.publicSymbols.find(({ python }) => python === "libtmux.Server")!;
        symbol.typescriptSymbols = ["not-a-locator"];
      },
      "invalid TypeScript symbol locator",
    ],
    [
      "behavior owner outside the public inventory",
      (manifest) => {
        manifest.observableBehaviors[0]!.owners = ["libtmux.server.Server.not_public"];
      },
      "owner is not an exact public symbol key",
    ],
    [
      "behavior evidence pinned only to the release tag",
      (manifest) => {
        manifest.observableBehaviors[0]!.pythonEvidence = [
          "https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/server.py",
        ];
      },
      "Python evidence must be canonical and pinned to baseline commit",
    ],
    [
      "exclusion evidence names a nonexistent baseline object",
      (manifest) => {
        manifest.internalExclusions[0]!.pythonEvidence = [
          `https://github.com/tmux-python/libtmux/blob/${baselineCommit}/src/libtmux/does_not_exist.py`,
        ];
      },
      "Python evidence does not exist at baseline commit",
    ],
    [
      "real-tmux behavior downgraded to deterministic",
      (manifest) => {
        manifest.observableBehaviors[0]!.evidenceApplicability.realTmuxScenario =
          "not-applicable: behavior is deterministic over validated in-memory values";
      },
      "has invalid realTmuxScenario applicability",
    ],
    [
      "unowned real-tmux exemption",
      (manifest) => {
        const symbol = manifest.publicSymbols.find(
          ({ python }) => python === "libtmux.pane.Pane.send_keys",
        )!;
        symbol.evidenceApplicability.realTmuxScenario =
          "not-applicable: real tmux coverage is owned by observable behavior records";
      },
      "cannot delegate through free-form text",
    ],
    [
      "adapted without explanation",
      (manifest) => {
        manifest.publicSymbols[0]!.status = "adapted";
        manifest.publicSymbols[0]!.typescript = "Client";
        manifest.publicSymbols[0]!.typescriptSymbols = [".#value:Client"];
        manifest.publicSymbols[0]!.unitTest = "tests/unit/client.test.ts";
        manifest.publicSymbols[0]!.adaptation = null;
      },
      "adapted records require an adaptation",
    ],
    [
      "unsupported without reason",
      (manifest) => {
        manifest.internalExclusions[0]!.reason = "";
      },
      "unsupported records require a reason",
    ],
  ];

  for (const [name, mutate, message] of invalidCases) {
    parityCheckerTest(`runtime rejects ${name}`, async () => {
      await withTemporaryManifest(async (path) => {
        const manifest = await readManifest(path);
        mutate(manifest);
        await writeFile(path, `${JSON.stringify(manifest, null, 2)}\n`);
        const result = await runChecker("--manifest", path);
        expect(result.exitCode).not.toBe(0);
        expect(result.stderr).toContain(message);
      });
    });
  }

  parityCheckerTest("rejects TypeScript symbols redirected outside package exports", async () => {
    await withTemporaryManifest(async (manifestPath) => {
      const manifest = await readManifest(manifestPath);
      const symbol = manifest.publicSymbols.find(({ python }) => python === "libtmux.Client")!;
      symbol.status = "implemented";
      symbol.typescript = "Client";
      symbol.unitTest = "tests/unit/parity_manifest.test.ts";
      symbol.declarationTest = "tests/fixtures/negative-declarations/query_list.test.ts";
      await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

      await withTemporaryPackageManifest(async (packagePath) => {
        const packageManifest = JSON.parse(await readFile(packagePath, "utf8")) as {
          exports: Record<string, unknown>;
        };
        packageManifest.exports["."] = {
          types: "./dist/unrelated.d.ts",
          import: "./dist/unrelated.js",
          default: "./dist/unrelated.js",
        };
        await writeFile(packagePath, `${JSON.stringify(packageManifest, null, 2)}\n`);

        const redirected = await runChecker(
          "--manifest",
          manifestPath,
          "--package-manifest",
          packagePath,
        );
        expect(redirected.exitCode).not.toBe(0);
        expect(redirected.stderr).toContain(
          "TypeScript module source does not exist for export target: ./src/unrelated.ts",
        );
      });
    });
  });

  parityCheckerTest(
    "preserves symbol evidence and manual record bytes during atomic regeneration",
    async () => {
      await withTemporaryManifest(async (path) => {
        const manifest = await readManifest(path);
        const symbol = manifest.publicSymbols.find(({ python }) => python === "libtmux.Client")!;
        symbol.typescript = "Client";
        symbol.typescriptSymbols = [".#value:Client"];
        symbol.unitTest = "tests/unit/parity_manifest.test.ts";
        symbol.declarationTest = "tests/fixtures/negative-declarations/query_list.test.ts";
        symbol.adaptation = "preservation sentinel";
        await writeFile(path, `${JSON.stringify(manifest, null, 2)}\n`);
        const before = await readFile(path, "utf8");
        const manualBytes = before.slice(before.indexOf('  "observableBehaviors":'));

        const result = await runChecker("--manifest", path, "--write");
        expect(result).toMatchObject({ exitCode: 0, stderr: "" });
        const after = await readFile(path, "utf8");
        const regenerated = await readManifest(path);
        expect(after.slice(after.indexOf('  "observableBehaviors":'))).toBe(manualBytes);
        expect(regenerated.publicSymbols.find(({ python }) => python === "libtmux.Client")).toEqual(
          symbol,
        );
      });
    },
  );

  parityCheckerTest("requires explicit approval for safe derived symbol removals", async () => {
    await withTemporaryManifest(async (path) => {
      const manifest = await readManifest(path);
      manifest.publicSymbols.push({
        ...manifest.publicSymbols[0]!,
        kind: "function",
        owner: "libtmux.review_sentinel",
        python: "libtmux.review_sentinel.removed",
        source:
          "https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/review_sentinel.py",
      });
      await writeFile(path, `${JSON.stringify(manifest, null, 2)}\n`);
      const before = await readFile(path, "utf8");

      const rejected = await runChecker("--manifest", path, "--write");
      expect(rejected.exitCode).not.toBe(0);
      expect(rejected.stderr).toContain(
        "removed public symbol keys require --allow-boundary-change",
      );
      expect(await readFile(path, "utf8")).toBe(before);
    });
  });

  parityCheckerTest("allows approved safe derived symbol removals", async () => {
    await withTemporaryManifest(async (path) => {
      const manifest = await readManifest(path);
      manifest.publicSymbols.push({
        ...manifest.publicSymbols[0]!,
        kind: "function",
        owner: "libtmux.review_sentinel",
        python: "libtmux.review_sentinel.removed",
        source:
          "https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/review_sentinel.py",
      });
      await writeFile(path, `${JSON.stringify(manifest, null, 2)}\n`);

      const approved = await runChecker("--manifest", path, "--write", "--allow-boundary-change");
      expect(approved).toMatchObject({ exitCode: 0, stderr: "" });
      expect((await readManifest(path)).publicSymbols).toHaveLength(513);
    });
  });

  parityCheckerTest(
    "rejects dangling provenance before approved boundary replacement",
    async () => {
      await withTemporaryManifest(async (path) => {
        const manifest = await readManifest(path);
        manifest.publicSymbols.push({
          ...manifest.publicSymbols[0]!,
          kind: "function",
          owner: "libtmux.review_sentinel",
          python: "libtmux.review_sentinel.removed",
          source:
            "https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/review_sentinel.py",
        });
        manifest.observableBehaviors
          .find(({ id }) => id === "repr.core-handles")!
          .owners.push("libtmux.review_sentinel.removed");
        await writeFile(path, `${JSON.stringify(manifest, null, 2)}\n`);
        const before = await readFile(path, "utf8");

        const approved = await runChecker("--manifest", path, "--write", "--allow-boundary-change");
        expect(approved.exitCode).not.toBe(0);
        expect(approved.stderr).toContain(
          "repr.core-handles owner is not an exact public symbol key: libtmux.review_sentinel.removed",
        );
        expect(await readFile(path, "utf8")).toBe(before);
      });
    },
  );

  parityCheckerTest(
    "rejects a baseline commit that does not resolve from the pinned tag",
    async () => {
      await withTemporaryManifest(async (path) => {
        const manifest = await readManifest(path);
        manifest.baseline.commit = "0000000000000000000000000000000000000000";
        await writeFile(path, `${JSON.stringify(manifest, null, 2)}\n`);

        const result = await runChecker("--manifest", path);
        expect(result.exitCode).not.toBe(0);
        expect(result.stderr).toContain(
          `v0.62.0 resolves to ${baselineCommit}, not 0000000000000000000000000000000000000000`,
        );
      });
    },
  );

  parityCheckerTest("passes the parity checker against all four sections", async () => {
    const result = await runChecker();

    expect(result.stderr).toBe("");
    expect(result.exitCode).toBe(0);
    expect(result.stdout.trim()).toBe(
      "Parity manifest valid: 513 public symbols, 45 behaviors, 14 TypeScript extensions, 13 exclusions",
    );
  });

  describe.serial("negative no-QueryList declaration fixture", () => {
    let freshDeclarationsAvailable = false;

    test("builds fresh declarations for the fixture", () => {
      freshDeclarationsAvailable = false;
      const build = Bun.spawnSync(["bun", "run", "build"], {
        cwd: tsRootPath,
        stderr: "pipe",
        stdout: "pipe",
      });
      expect(build.exitCode, `${build.stdout.toString()}${build.stderr.toString()}`).toBe(0);
      freshDeclarationsAvailable = true;
    });

    test("compiles the fixture against the fresh declarations", () => {
      expect(
        freshDeclarationsAvailable,
        "the declaration build test must run successfully before this test",
      ).toBe(true);
      const declarationTest = Bun.spawnSync(
        [
          "./node_modules/.bin/tsc",
          "-p",
          "tests/fixtures/negative-declarations/tsconfig.json",
          "--noEmit",
          "--pretty",
          "false",
        ],
        { cwd: tsRootPath, stderr: "pipe", stdout: "pipe" },
      );
      expect(
        declarationTest.exitCode,
        `${declarationTest.stdout.toString()}${declarationTest.stderr.toString()}`,
      ).toBe(0);
    });

    test("rejects the fixture when QueryList is declared", async () => {
      await withTemporaryDirectory("libtmux-query-list-negative-", async (directory) => {
        await Promise.all([
          writeFile(join(directory, "index.d.ts"), "export interface QueryList<T> { at: T }\n"),
          writeFile(
            join(directory, "query_list.test.ts"),
            '// @ts-expect-error QueryList must be absent.\nimport type { QueryList } from "./index.js";\nexport type { QueryList };\n',
          ),
        ]);
        const adversarial = Bun.spawnSync(
          [
            join(tsRootPath, "node_modules/.bin/tsc"),
            "--strict",
            "--noEmit",
            "--module",
            "NodeNext",
            "--moduleResolution",
            "NodeNext",
            "--target",
            "ES2024",
            "--pretty",
            "false",
            "query_list.test.ts",
          ],
          { cwd: directory, stderr: "pipe", stdout: "pipe" },
        );
        expect(adversarial.exitCode).not.toBe(0);
        expect(`${adversarial.stdout.toString()}${adversarial.stderr.toString()}`).toContain(
          "Unused '@ts-expect-error' directive",
        );
      });
    });
  });
});
