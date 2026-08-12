import { randomUUID } from "node:crypto";
import { existsSync, realpathSync, statSync } from "node:fs";
import { open, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";

const tsRoot = join(import.meta.dir, "..");
const repositoryRoot = join(tsRoot, "..");
const defaultManifestPath = join(tsRoot, "parity/python-0.62.0.json");
const defaultPackageManifestPath = join(tsRoot, "package.json");
const sourceUrl = "https://github.com/tmux-python/libtmux/blob/v0.62.0";

const modules = [
  "client",
  "common",
  "constants",
  "exc",
  "hooks",
  "neo",
  "options",
  "pane",
  "server",
  "session",
  "window",
] as const;
const testHelperModules = ["constants", "environment", "random", "retry", "temporary"] as const;
const ignoredMethods = new Set(["__init__"]);
const ignoredTestHelpers = new Set(["libtmux.pytest_plugin.USING_ZSH"]);
const compatibilityAliases = new Set([
  "Pane.get",
  "Pane.height",
  "Pane.id",
  "Pane.index",
  "Pane.resize_pane",
  "Pane.select_pane",
  "Pane.split_window",
  "Pane.title",
  "Pane.width",
  "Session.attach_session",
  "Session.attached_pane",
  "Session.attached_window",
  "Session.get",
  "Session.get_by_id",
  "Session.id",
  "Session.kill_session",
  "Session.name",
  "Session.find_where",
  "Session.list_windows",
  "Session.where",
  "Session.children",
  "Server.find_where",
  "Server.get_by_id",
  "Server.kill_server",
  "Server.list_sessions",
  "Server.where",
  "Server.children",
  "Window.attached_pane",
  "Window.find_where",
  "Window.get",
  "Window.get_by_id",
  "Window.height",
  "Window.id",
  "Window.index",
  "Window.kill_window",
  "Window.list_panes",
  "Window.name",
  "Window.select_window",
  "Window.set_window_option",
  "Window.show_window_option",
  "Window.show_window_options",
  "Window.split_window",
  "Window.where",
  "Window.width",
  "Window.children",
]);
const behaviorDunders = new Set([
  "__call__",
  "__eq__",
  "__enter__",
  "__exit__",
  "__getitem__",
  "__iter__",
  "__next__",
  "__repr__",
  "__str__",
]);

const enumMembers = {
  OptionScope: ["Server", "Session", "Window", "Pane"],
  PaneDirection: ["Above", "Below", "Right", "Left"],
  ResizeAdjustmentDirection: ["Up", "Down", "Left", "Right"],
  WindowDirection: ["Before", "After"],
} as const;
const rootExports = ["Client", "Pane", "Server", "Session", "Window"] as const;
const deterministicBehaviorApplicability =
  "not-applicable: behavior is deterministic over validated in-memory values";
const requiredRealTmuxBehaviors = new Set([
  "accessor.attached-sessions-exact-one",
  "accessor.error-linked-sessions",
  "accessor.error-missing-daemon-topology",
  "accessor.error-point-lookup",
  "accessor.error-propagating-relations",
  "accessor.error-schema-protocol",
  "accessor.error-server-list-leniency",
  "cmd-protocol.call",
  "collection.contextual-duplicates",
  "collection.eager-snapshots",
  "context.pane",
  "context.server",
  "context.session",
  "context.window",
]);

type ParityKind =
  | "class"
  | "compatibility-alias"
  | "constant"
  | "enum-member"
  | "exception"
  | "format-field"
  | "function"
  | "method"
  | "property"
  | "root-export"
  | "test-helper";
type Status = "planned" | "implemented" | "adapted" | "unsupported";
type EvidenceApplicability = "required" | `not-applicable: ${string}`;

interface EvidenceApplicabilityFields {
  declarationTest: EvidenceApplicability;
  realTmuxScenario: EvidenceApplicability;
  unitTest: EvidenceApplicability;
}

interface EvidenceFields {
  adaptation: string | null;
  declarationTest: string | null;
  evidenceApplicability: EvidenceApplicabilityFields;
  realTmuxScenario: string | null;
  reason: string | null;
  status: Status;
  typescript: string | null;
  typescriptSymbols: string[];
  unitTest: string | null;
}

interface PublicSymbol extends EvidenceFields {
  kind: ParityKind;
  owner: string;
  python: string;
  source: string;
}

interface ObservableBehavior extends EvidenceFields {
  adaptation: string;
  id: string;
  owners: string[];
  pythonEvidence: string[];
}

interface TypeScriptExtension extends EvidenceFields {
  id: string;
  rationale: string;
  typescript: string;
}

interface InternalExclusion extends EvidenceFields {
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

const evidenceKeys = [
  "adaptation",
  "declarationTest",
  "evidenceApplicability",
  "realTmuxScenario",
  "reason",
  "status",
  "typescript",
  "typescriptSymbols",
  "unitTest",
] as const;
const evidenceLanes = ["declarationTest", "realTmuxScenario", "unitTest"] as const;

function fail(message: string): never {
  throw new Error(message);
}

function objectAt(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(`${path} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(object: Record<string, unknown>, keys: readonly string[], path: string): void {
  const expected = [...keys].sort();
  const actual = Object.keys(object).sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    fail(`${path} must contain exactly: ${expected.join(", ")}`);
  }
}

function stringAt(object: Record<string, unknown>, key: string, path: string): string {
  const value = object[key];
  if (typeof value !== "string" || value.length === 0) fail(`${path}.${key} must be a string`);
  return value;
}

function nullableStringAt(
  object: Record<string, unknown>,
  key: string,
  path: string,
): string | null {
  const value = object[key];
  if (value !== null && typeof value !== "string") fail(`${path}.${key} must be string or null`);
  return value as string | null;
}

function stringArrayAt(object: Record<string, unknown>, key: string, path: string): string[] {
  const value = object[key];
  if (
    !Array.isArray(value) ||
    value.length === 0 ||
    value.some((item) => typeof item !== "string")
  ) {
    fail(`${path}.${key} must be a nonempty string array`);
  }
  return value as string[];
}

function stringListAt(object: Record<string, unknown>, key: string, path: string): string[] {
  const value = object[key];
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || item.length === 0) ||
    new Set(value).size !== value.length
  ) {
    fail(`${path}.${key} must be an array of unique nonempty strings`);
  }
  return value as string[];
}

function validateEvidenceApplicability(
  object: Record<string, unknown>,
  path: string,
): EvidenceApplicabilityFields {
  const applicability = objectAt(object.evidenceApplicability, `${path}.evidenceApplicability`);
  exactKeys(applicability, evidenceLanes, `${path}.evidenceApplicability`);
  for (const lane of evidenceLanes) {
    const value = stringAt(applicability, lane, `${path}.evidenceApplicability`);
    if (value !== "required" && !/^not-applicable: \S/.test(value)) {
      fail(
        `${path}.evidenceApplicability.${lane} must be required or include a not-applicable reason`,
      );
    }
    if (value.includes("owned by observable behavior records")) {
      fail(`${path}.evidenceApplicability.${lane} cannot delegate through free-form text`);
    }
  }
  return applicability as unknown as EvidenceApplicabilityFields;
}

function validateEvidence(object: Record<string, unknown>, path: string): void {
  const status = object.status;
  if (!(["planned", "implemented", "adapted", "unsupported"] as unknown[]).includes(status)) {
    fail(`${path} has invalid status`);
  }
  const typedStatus = status as Status;
  const typescript = nullableStringAt(object, "typescript", path);
  const unitTest = nullableStringAt(object, "unitTest", path);
  const adaptation = nullableStringAt(object, "adaptation", path);
  const reason = nullableStringAt(object, "reason", path);
  const typescriptSymbols = stringListAt(object, "typescriptSymbols", path);
  const declarationTest = nullableStringAt(object, "declarationTest", path);
  const realTmuxScenario = nullableStringAt(object, "realTmuxScenario", path);
  const evidenceApplicability = validateEvidenceApplicability(object, path);

  if ((typedStatus === "implemented" || typedStatus === "adapted") && !typescript) {
    fail(`${path} activated records require a TypeScript target`);
  }
  if (
    (typedStatus === "implemented" || typedStatus === "adapted") &&
    typescriptSymbols.length === 0
  ) {
    fail(`${path} activated records require TypeScript symbols`);
  }
  if (typedStatus === "unsupported" && typescriptSymbols.length !== 0) {
    fail(`${path} unsupported records cannot name TypeScript symbols`);
  }
  if (typedStatus === "adapted" && !adaptation) {
    fail(`${path} adapted records require an adaptation`);
  }
  if (typedStatus === "unsupported" && !reason) {
    fail(`${path} unsupported records require a reason`);
  }
  const activated = typedStatus !== "planned";
  const evidence = { declarationTest, realTmuxScenario, unitTest };
  for (const lane of evidenceLanes) {
    const applicability = evidenceApplicability[lane];
    if (activated && applicability === "required" && !evidence[lane]) {
      fail(`${path} activated records require ${lane} evidence`);
    }
    if (applicability !== "required" && evidence[lane] !== null) {
      fail(`${path}.${lane} must be null when its evidence lane is not applicable`);
    }
  }
  if (typescript?.startsWith("planned:")) fail(`${path} contains a fabricated planned target`);
}

function parseManifest(value: unknown): ParityManifest {
  const manifest = objectAt(value, "manifest");
  exactKeys(
    manifest,
    [
      "schemaVersion",
      "baseline",
      "runtimeBoundary",
      "publicSymbols",
      "observableBehaviors",
      "typescriptExtensions",
      "internalExclusions",
    ],
    "manifest",
  );
  if (manifest.schemaVersion !== 2) fail("manifest.schemaVersion must be 2");

  const baseline = objectAt(manifest.baseline, "manifest.baseline");
  exactKeys(baseline, ["pythonVersion", "tag", "commit"], "manifest.baseline");
  stringAt(baseline, "pythonVersion", "manifest.baseline");
  stringAt(baseline, "tag", "manifest.baseline");
  const commit = stringAt(baseline, "commit", "manifest.baseline");
  if (!/^[0-9a-f]{40}$/.test(commit)) fail("manifest.baseline.commit must be a full commit");

  const boundary = objectAt(manifest.runtimeBoundary, "manifest.runtimeBoundary");
  exactKeys(boundary, ["includes", "excludes"], "manifest.runtimeBoundary");
  stringAt(boundary, "includes", "manifest.runtimeBoundary");
  stringArrayAt(boundary, "excludes", "manifest.runtimeBoundary");

  if (!Array.isArray(manifest.publicSymbols)) fail("manifest.publicSymbols must be an array");
  for (const [index, value] of manifest.publicSymbols.entries()) {
    const path = `manifest.publicSymbols[${index}]`;
    const record = objectAt(value, path);
    exactKeys(record, [...evidenceKeys, "kind", "owner", "python", "source"], path);
    for (const key of ["kind", "owner", "python", "source"]) stringAt(record, key, path);
    validateEvidence(record, path);
  }

  if (!Array.isArray(manifest.observableBehaviors)) {
    fail("manifest.observableBehaviors must be an array");
  }
  for (const [index, value] of manifest.observableBehaviors.entries()) {
    const path = `manifest.observableBehaviors[${index}]`;
    const record = objectAt(value, path);
    exactKeys(record, [...evidenceKeys, "id", "owners", "pythonEvidence"], path);
    stringAt(record, "id", path);
    stringArrayAt(record, "owners", path);
    stringArrayAt(record, "pythonEvidence", path);
    if (!nullableStringAt(record, "adaptation", path)) fail(`${path}.adaptation must be a string`);
    validateEvidence(record, path);
  }

  if (!Array.isArray(manifest.typescriptExtensions)) {
    fail("manifest.typescriptExtensions must be an array");
  }
  for (const [index, value] of manifest.typescriptExtensions.entries()) {
    const path = `manifest.typescriptExtensions[${index}]`;
    const record = objectAt(value, path);
    exactKeys(record, [...evidenceKeys, "id", "rationale"], path);
    stringAt(record, "id", path);
    stringAt(record, "rationale", path);
    stringAt(record, "typescript", path);
    validateEvidence(record, path);
  }

  if (!Array.isArray(manifest.internalExclusions)) {
    fail("manifest.internalExclusions must be an array");
  }
  for (const [index, value] of manifest.internalExclusions.entries()) {
    const path = `manifest.internalExclusions[${index}]`;
    const record = objectAt(value, path);
    exactKeys(record, [...evidenceKeys, "id", "pythonEvidence"], path);
    stringAt(record, "id", path);
    stringArrayAt(record, "pythonEvidence", path);
    validateEvidence(record, path);
    if (record.status !== "unsupported") fail(`${path}.status must be unsupported`);
  }

  for (const [name, records] of [
    ["publicSymbols", manifest.publicSymbols],
    ["observableBehaviors", manifest.observableBehaviors],
    ["typescriptExtensions", manifest.typescriptExtensions],
    ["internalExclusions", manifest.internalExclusions],
  ] as const) {
    const keys = (records as Array<Record<string, unknown>>).map((record) =>
      name === "publicSymbols"
        ? `${String(record.kind)}:${String(record.python)}`
        : String(record.id),
    );
    if (new Set(keys).size !== keys.length) fail(`manifest.${name} keys must be unique`);
  }

  return manifest as unknown as ParityManifest;
}

function sourcePath(module: string, testHelper = false): string {
  return join(repositoryRoot, "src/libtmux", testHelper ? "test" : "", `${module}.py`);
}

function runGit(arguments_: string[]): string {
  const result = Bun.spawnSync(["git", ...arguments_], {
    cwd: repositoryRoot,
    stderr: "pipe",
    stdout: "pipe",
  });
  if (result.exitCode !== 0) fail(result.stderr.toString().trim());
  return result.stdout.toString().trim();
}

function verifyBaseline(manifest: ParityManifest): void {
  const { commit, pythonVersion, tag } = manifest.baseline;
  if (pythonVersion !== "0.62.0") fail("baseline.pythonVersion must be 0.62.0");
  if (tag !== "v0.62.0") fail("baseline.tag must be v0.62.0");
  let resolved: string;
  try {
    resolved = runGit(["rev-parse", `${tag}^{commit}`]);
  } catch {
    fail(`Unable to resolve ${tag}; fetch tags and unshallow the checkout before checking parity`);
  }
  if (resolved !== commit) fail(`${tag} resolves to ${resolved}, not ${commit}`);
}

function verifyPythonEvidence(key: string, values: string[], baselineCommit: string): void {
  const canonicalPattern = new RegExp(
    `^https://github\\.com/tmux-python/libtmux/(blob|tree)/${baselineCommit}/([A-Za-z0-9_./-]+)$`,
  );
  for (const value of values) {
    const match = canonicalPattern.exec(value);
    if (!match?.[1] || !match[2]) {
      fail(`${key} Python evidence must be canonical and pinned to baseline commit: ${value}`);
    }
    const [, linkKind, objectPath] = match;
    if (objectPath.split("/").some((part) => part === "" || part === "." || part === "..")) {
      fail(`${key} Python evidence must be canonical and pinned to baseline commit: ${value}`);
    }
    let objectKind: string;
    try {
      objectKind = runGit(["cat-file", "-t", `${baselineCommit}:${objectPath}`]);
    } catch {
      fail(`${key} Python evidence does not exist at baseline commit: ${value}`);
    }
    const expectedKind = linkKind === "blob" ? "blob" : "tree";
    if (objectKind !== expectedKind) {
      fail(`${key} Python evidence URL kind does not match its Git object: ${value}`);
    }
  }
}

function verifyManualProvenance(manifest: ParityManifest): void {
  const publicSymbolKeys = new Set(manifest.publicSymbols.map(({ python }) => python));
  for (const behavior of manifest.observableBehaviors) {
    for (const owner of behavior.owners) {
      if (!publicSymbolKeys.has(owner)) {
        fail(`${behavior.id} owner is not an exact public symbol key: ${owner}`);
      }
    }
    const expectedApplicability = requiredRealTmuxBehaviors.has(behavior.id)
      ? "required"
      : deterministicBehaviorApplicability;
    if (behavior.evidenceApplicability.realTmuxScenario !== expectedApplicability) {
      fail(`${behavior.id} has invalid realTmuxScenario applicability`);
    }
    verifyPythonEvidence(behavior.id, behavior.pythonEvidence, manifest.baseline.commit);
  }
  for (const exclusion of manifest.internalExclusions) {
    verifyPythonEvidence(exclusion.id, exclusion.pythonEvidence, manifest.baseline.commit);
  }
}

function evidenceRecords(manifest: ParityManifest): Array<{ key: string; record: EvidenceFields }> {
  return [
    ...manifest.publicSymbols.map((record) => ({
      key: `${record.kind}:${record.python}`,
      record,
    })),
    ...manifest.observableBehaviors.map((record) => ({ key: record.id, record })),
    ...manifest.typescriptExtensions.map((record) => ({ key: record.id, record })),
    ...manifest.internalExclusions.map((record) => ({ key: record.id, record })),
  ];
}

const evidencePathPatterns = {
  declarationTest: /^tests\/(?:types|fixtures\/negative-declarations)\/[a-z0-9_./-]+\.test\.ts$/,
  realTmuxScenario: /^tests\/(?:integration|differential)\/[a-z0-9_./-]+\.test\.ts$/,
  unitTest: /^tests\/unit\/[a-z0-9_./-]+\.test\.ts$/,
} as const;

function verifyEvidencePaths(manifest: ParityManifest): void {
  for (const { key, record } of evidenceRecords(manifest)) {
    for (const lane of evidenceLanes) {
      const path = record[lane];
      if (path === null) continue;
      if (!evidencePathPatterns[lane].test(path)) {
        fail(`${key} has invalid ${lane} evidence path: ${path}`);
      }
      const absolutePath = resolve(tsRoot, path);
      const packageRelative = relative(tsRoot, absolutePath);
      if (
        packageRelative !== path ||
        packageRelative === ".." ||
        packageRelative.startsWith("../") ||
        isAbsolute(packageRelative)
      ) {
        fail(`${key} evidence path escapes the package: ${path}`);
      }
      if (!existsSync(absolutePath) || !statSync(absolutePath).isFile()) {
        fail(`${key} evidence path does not exist: ${path}`);
      }
      const realRelative = relative(tsRoot, realpathSync(absolutePath));
      if (realRelative === ".." || realRelative.startsWith("../") || isAbsolute(realRelative)) {
        fail(`${key} evidence path resolves outside the package: ${path}`);
      }
    }
  }
}

const typescriptSymbolPattern =
  /^(?:\.|\.\/[a-z][a-z0-9_-]*)#(?:type|value|instance|well-known-instance):[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$/;

interface TypeScriptSymbolLocator {
  kind: "instance" | "type" | "value" | "well-known-instance";
  moduleName: string;
  path: string[];
  raw: string;
}

function parseTypeScriptSymbol(key: string, locator: string): TypeScriptSymbolLocator {
  if (!typescriptSymbolPattern.test(locator)) {
    fail(`${key} has invalid TypeScript symbol locator: ${locator}`);
  }
  const separator = locator.indexOf("#");
  const moduleName = locator.slice(0, separator);
  const [kind, symbol] = locator.slice(separator + 1).split(":", 2) as [
    TypeScriptSymbolLocator["kind"],
    string,
  ];
  const path = symbol.split(".");
  if (kind === "instance" && path.length < 2) {
    fail(`${key} instance symbol locator requires a member: ${locator}`);
  }
  if (
    kind === "well-known-instance" &&
    (path.length !== 2 || !["asyncDispose", "dispose", "iterator"].includes(path[1]!))
  ) {
    fail(`${key} has invalid well-known TypeScript symbol locator: ${locator}`);
  }
  return { kind, moduleName, path, raw: locator };
}

function probeType(locator: TypeScriptSymbolLocator, index: number): string {
  const [top, ...members] = locator.path;
  const indexedMembers = members.map((member) => `["${member}"]`).join("");
  if (locator.kind === "type") {
    if (members.length === 0) return "";
    return `type ParityTarget${index} = ParityTypes${index}.${top}${indexedMembers};`;
  }
  if (locator.kind === "instance") {
    return `type ParityTarget${index} = (typeof ParityValues${index}.${top}.prototype)${indexedMembers};`;
  }
  if (locator.kind === "well-known-instance") {
    return `type ParityTarget${index} = (typeof ParityValues${index}.${top}.prototype)[typeof Symbol.${members[0]}];`;
  }
  return `type ParityTarget${index} = (typeof ParityValues${index}.${top})${indexedMembers};`;
}

interface ExportSource {
  importPath: string;
  relativePath: string;
}

function exportSource(moduleName: string, value: unknown): ExportSource {
  const path = `package.exports[${JSON.stringify(moduleName)}]`;
  const conditions = objectAt(value, path);
  exactKeys(conditions, ["types", "import", "default"], path);
  const typesTarget = stringAt(conditions, "types", path);
  const importTarget = stringAt(conditions, "import", path);
  const defaultTarget = stringAt(conditions, "default", path);
  const typesMatch = /^\.\/dist\/([a-z][a-z0-9_/-]*)\.d\.ts$/.exec(typesTarget);
  const importMatch = /^\.\/dist\/([a-z][a-z0-9_/-]*)\.js$/.exec(importTarget);
  const defaultMatch = /^\.\/dist\/([a-z][a-z0-9_/-]*)\.js$/.exec(defaultTarget);
  if (
    !typesMatch?.[1] ||
    !importMatch?.[1] ||
    !defaultMatch?.[1] ||
    typesMatch[1] !== importMatch[1] ||
    importMatch[1] !== defaultMatch[1]
  ) {
    fail(`${path} must have aligned ./dist types, import, and default targets`);
  }
  return {
    importPath: `./src/${importMatch[1]}.js`,
    relativePath: `./src/${importMatch[1]}.ts`,
  };
}

async function verifyTypeScriptSymbols(
  manifest: ParityManifest,
  packageManifestPath: string,
): Promise<void> {
  const parsed = evidenceRecords(manifest).flatMap(({ key, record }) =>
    record.typescriptSymbols.map((raw) => ({
      activated: record.status === "implemented" || record.status === "adapted",
      key,
      locator: parseTypeScriptSymbol(key, raw),
    })),
  );
  const activated = parsed.filter(({ activated }) => activated);
  if (activated.length === 0) return;

  const packageManifest = JSON.parse(await readFile(packageManifestPath, "utf8")) as {
    exports?: Record<string, unknown>;
  };
  const exports = packageManifest.exports ?? {};
  const locators: TypeScriptSymbolLocator[] = [];
  const sources: ExportSource[] = [];
  for (const { key, locator } of activated) {
    if (!Object.hasOwn(exports, locator.moduleName)) {
      fail(`${key} TypeScript module is not exported: ${locator.moduleName}`);
    }
    const source = exportSource(locator.moduleName, exports[locator.moduleName]);
    const sourcePath = join(tsRoot, source.relativePath);
    if (!existsSync(sourcePath) || !statSync(sourcePath).isFile()) {
      fail(`TypeScript module source does not exist for export target: ${source.relativePath}`);
    }
    locators.push(locator);
    sources.push(source);
  }

  const imports = locators.flatMap((locator, index) => {
    const source = sources[index]!.importPath;
    if (locator.kind === "type" && locator.path.length === 1) {
      return [`import type { ${locator.path[0]} as ParityImportedType${index} } from "${source}";`];
    }
    return locator.kind === "type"
      ? [`import type * as ParityTypes${index} from "${source}";`]
      : [`import * as ParityValues${index} from "${source}";`];
  });
  const probe = `${imports.join("\n")}\n\n${locators.map(probeType).join("\n")}\n\nexport {};\n`;
  const identifier = randomUUID();
  const probeName = `.parity-symbols-${identifier}.ts`;
  const configName = `.parity-symbols-${identifier}.json`;
  const probePath = join(tsRoot, probeName);
  const configPath = join(tsRoot, configName);
  const config = `${JSON.stringify(
    {
      extends: "./tsconfig.json",
      compilerOptions: {
        declaration: false,
        isolatedDeclarations: false,
        noEmit: true,
        rootDir: ".",
      },
      files: [probeName],
    },
    null,
    2,
  )}\n`;
  try {
    await Promise.all([writeFile(probePath, probe, { flag: "wx" }), writeFile(configPath, config)]);
    const result = Bun.spawnSync(
      [join(tsRoot, "node_modules/.bin/tsc"), "-p", configPath, "--pretty", "false"],
      { cwd: tsRoot, stderr: "pipe", stdout: "pipe" },
    );
    if (result.exitCode !== 0) {
      fail(
        `TypeScript symbol does not exist or does not typecheck: ${locators
          .map(({ raw }) => raw)
          .join(", ")}\n${result.stdout.toString()}${result.stderr.toString()}`.trim(),
      );
    }
  } finally {
    await Promise.all([
      unlink(probePath).catch(() => undefined),
      unlink(configPath).catch(() => undefined),
    ]);
  }
}

function readPythonSource(path: string): string {
  const revisionPath = relative(repositoryRoot, path);
  try {
    return runGit(["show", `v0.62.0:${revisionPath}`]);
  } catch (error) {
    fail(`Unable to read v0.62.0:${revisionPath}: ${(error as Error).message}`);
  }
}

function ownerOf(python: string): string {
  return python.slice(0, python.lastIndexOf("."));
}

function knownTarget(kind: ParityKind, python: string): string | null {
  if (kind === "root-export") return python.slice("libtmux.".length);
  if (kind === "enum-member") return python.slice("libtmux.constants.".length);
  if (python === "libtmux.test.random.namer") return "namer";
  return null;
}

function knownTypeScriptSymbols(kind: ParityKind, python: string): string[] {
  if (kind === "root-export") return [`.#value:${python.slice("libtmux.".length)}`];
  if (kind === "enum-member") {
    return [`./constants#value:${python.slice("libtmux.constants.".length)}`];
  }
  if (python === "libtmux.test.random.namer") return ["./test#value:namer"];
  return [];
}

const requiredRealTmuxSymbols = new Set([
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
]);

const NOT_PORTED = "not-applicable: the symbol is not ported, so it has no evidence to record";

const plannedNeoSymbols = new Set(["libtmux.neo.fetch_obj", "libtmux.neo.fetch_objs"]);

function publicSymbolEvidenceApplicability(
  kind: ParityKind,
  python: string,
): EvidenceApplicabilityFields {
  const realTmuxRequired =
    kind === "method" ||
    kind === "compatibility-alias" ||
    kind === "property" ||
    requiredRealTmuxSymbols.has(python);
  // neo.py's responsibilities are split across generated metadata, the codec,
  // the graph, and the handles rather than ported to a module of their own, so
  // its symbols carry no evidence of their own.
  if (python.startsWith("libtmux.neo") && !plannedNeoSymbols.has(python)) {
    return {
      declarationTest: NOT_PORTED,
      realTmuxScenario: NOT_PORTED,
      unitTest: NOT_PORTED,
    };
  }
  return {
    declarationTest: "required",
    realTmuxScenario: realTmuxRequired
      ? "required"
      : "not-applicable: symbol has no direct tmux I/O behavior",
    unitTest: "required",
  };
}

function createSymbol(kind: ParityKind, python: string, path: string): PublicSymbol {
  return {
    adaptation: null,
    declarationTest: null,
    evidenceApplicability: publicSymbolEvidenceApplicability(kind, python),
    kind,
    owner: ownerOf(python),
    python,
    realTmuxScenario: null,
    reason: null,
    source: `${sourceUrl}/${relative(repositoryRoot, path)}`,
    status: "planned",
    typescript: knownTarget(kind, python),
    typescriptSymbols: knownTypeScriptSymbols(kind, python),
    unitTest: null,
  };
}

function memberKind(className: string, memberName: string, property: boolean): ParityKind | null {
  const symbol = `${className}.${memberName}`;
  if (
    behaviorDunders.has(memberName) ||
    memberName.startsWith("_") ||
    ignoredMethods.has(memberName)
  ) {
    return null;
  }
  if (compatibilityAliases.has(symbol)) return "compatibility-alias";
  if (property) return "property";
  return "method";
}

function collectModule(module: string): PublicSymbol[] {
  const path = sourcePath(module);
  const lines = readPythonSource(path).split("\n");
  const entries: PublicSymbol[] = [];
  const methods = new Set<string>();
  let currentClass: string | undefined;
  let property = false;

  for (const line of lines) {
    const classMatch = /^class ([A-Za-z][A-Za-z0-9_]*)/.exec(line);
    if (classMatch?.[1]) {
      currentClass = classMatch[1].startsWith("_") ? undefined : classMatch[1];
      property = false;
      if (currentClass) {
        entries.push(
          createSymbol(
            module === "exc" ? "exception" : "class",
            `libtmux.${module}.${currentClass}`,
            path,
          ),
        );
      }
      continue;
    }

    const topLevelDefinition = /^(?:def |[A-Z][A-Z0-9_]*(?::[^=]+)?\s*=)/.test(line);
    if (topLevelDefinition) {
      currentClass = undefined;
      property = false;
      const functionMatch = /^def ([a-z][A-Za-z0-9_]*)/.exec(line);
      if (functionMatch?.[1]) {
        entries.push(createSymbol("function", `libtmux.${module}.${functionMatch[1]}`, path));
      }
      const constantMatch = /^([A-Z][A-Z0-9_]*)(?::[^=]+)?\s*=/.exec(line);
      if (constantMatch?.[1] && module !== "exc") {
        entries.push(createSymbol("constant", `libtmux.${module}.${constantMatch[1]}`, path));
      }
      continue;
    }

    if (!currentClass) continue;
    if (line.trim() === "@property") {
      property = true;
      continue;
    }
    const methodMatch = /^    def ([A-Za-z_][A-Za-z0-9_]*)/.exec(line);
    if (!methodMatch?.[1] || module === "exc") continue;
    const key = `${currentClass}.${methodMatch[1]}`;
    if (methods.has(key)) {
      property = false;
      continue;
    }
    methods.add(key);
    const kind = memberKind(currentClass, methodMatch[1], property);
    if (kind) entries.push(createSymbol(kind, `libtmux.${module}.${key}`, path));
    property = false;
  }
  return entries;
}

function collectFormatFields(): PublicSymbol[] {
  const path = sourcePath("neo");
  const lines = readPythonSource(path).split("\n");
  const entries: PublicSymbol[] = [];
  let inObj = false;
  for (const line of lines) {
    if (/^class Obj\b/.test(line)) inObj = true;
    else if (inObj && /^\S/.test(line)) break;
    if (!inObj) continue;
    const field = /^    ([a-z][a-z0-9_]+):/.exec(line)?.[1];
    if (field && field !== "server") {
      entries.push(createSymbol("format-field", `libtmux.neo.Obj.${field}`, path));
    }
  }
  return entries;
}

function collectTestHelpers(): PublicSymbol[] {
  const entries: PublicSymbol[] = [];
  for (const module of testHelperModules) {
    const path = sourcePath(module, true);
    const lines = readPythonSource(path).split("\n");
    let currentClass: string | undefined;
    for (const line of lines) {
      const classMatch = /^class ([A-Za-z][A-Za-z0-9_]*)/.exec(line);
      if (classMatch?.[1]) {
        currentClass = classMatch[1];
        entries.push(createSymbol("test-helper", `libtmux.test.${module}.${currentClass}`, path));
        continue;
      }
      const functionMatch = /^def ([a-z][A-Za-z0-9_]*)/.exec(line);
      if (functionMatch?.[1]) {
        currentClass = undefined;
        entries.push(
          createSymbol("test-helper", `libtmux.test.${module}.${functionMatch[1]}`, path),
        );
        continue;
      }
      const methodMatch = currentClass && /^    def ([a-z][A-Za-z0-9_]*)\(/.exec(line)?.[1];
      if (methodMatch && !behaviorDunders.has(methodMatch)) {
        entries.push(
          createSymbol(
            "test-helper",
            `libtmux.test.${module}.${currentClass}.${methodMatch}`,
            path,
          ),
        );
      }
      const constantMatch = /^([A-Z][A-Z0-9_]*)(?::[^=]+)?\s*=/.exec(line);
      if (constantMatch?.[1]) {
        entries.push(
          createSymbol("test-helper", `libtmux.test.${module}.${constantMatch[1]}`, path),
        );
      }
    }
  }

  const randomPath = sourcePath("random", true);
  entries.push(createSymbol("test-helper", "libtmux.test.random.namer", randomPath));

  const pluginPath = sourcePath("pytest_plugin");
  for (const line of readPythonSource(pluginPath).split("\n")) {
    const functionMatch = /^def ([A-Za-z][A-Za-z0-9_]*)/.exec(line);
    if (functionMatch?.[1]) {
      entries.push(
        createSymbol("test-helper", `libtmux.pytest_plugin.${functionMatch[1]}`, pluginPath),
      );
    }
    const constantMatch = /^([A-Z][A-Z0-9_]*)(?::[^=]+)?\s*=/.exec(line);
    if (constantMatch?.[1]) {
      const python = `libtmux.pytest_plugin.${constantMatch[1]}`;
      if (!ignoredTestHelpers.has(python))
        entries.push(createSymbol("test-helper", python, pluginPath));
    }
  }
  return entries;
}

function collectConstants(): PublicSymbol[] {
  const entries: PublicSymbol[] = [];
  for (const module of ["common", "constants", "formats", "neo", "options"]) {
    const path = sourcePath(module);
    for (const line of readPythonSource(path).split("\n")) {
      const constant = /^([A-Z][A-Z0-9_]*)(?::[^=]+)?\s*=/.exec(line)?.[1];
      if (constant) entries.push(createSymbol("constant", `libtmux.${module}.${constant}`, path));
    }
  }
  const packagePath = join(repositoryRoot, "src/libtmux/__init__.py");
  for (const name of [
    "__author__",
    "__copyright__",
    "__description__",
    "__email__",
    "__license__",
    "__package_name__",
    "__title__",
    "__version__",
  ]) {
    entries.push(createSymbol("constant", `libtmux.${name}`, packagePath));
  }
  return entries;
}

function collectRootExports(): PublicSymbol[] {
  const path = join(repositoryRoot, "src/libtmux/__init__.py");
  const source = readPythonSource(path);
  return rootExports.map((name) => {
    if (!source.includes(`from .${name.toLowerCase()} import ${name}`)) {
      fail(`missing audited root export ${name}`);
    }
    return createSymbol("root-export", `libtmux.${name}`, path);
  });
}

function collectEnumMembers(): PublicSymbol[] {
  const path = sourcePath("constants");
  const source = readPythonSource(path);
  const entries: PublicSymbol[] = [];
  for (const [owner, members] of Object.entries(enumMembers)) {
    for (const member of members) {
      if (!new RegExp(`^    ${member} = `, "m").test(source)) {
        fail(`missing audited enum member ${owner}.${member}`);
      }
      entries.push(createSymbol("enum-member", `libtmux.constants.${owner}.${member}`, path));
    }
  }
  return entries;
}

function inventory(): PublicSymbol[] {
  const entries = [
    ...modules.flatMap(collectModule).filter((entry) => entry.kind !== "constant"),
    ...collectConstants(),
    ...collectFormatFields(),
    ...collectTestHelpers(),
    ...collectRootExports(),
    ...collectEnumMembers(),
  ];
  return entries.sort((left, right) =>
    `${left.kind}:${left.python}`.localeCompare(`${right.kind}:${right.python}`),
  );
}

function symbolKey(symbol: PublicSymbol): string {
  return `${symbol.kind}:${symbol.python}`;
}

function mergeSymbols(generated: PublicSymbol[], existing: PublicSymbol[]): PublicSymbol[] {
  const previous = new Map(existing.map((entry) => [symbolKey(entry), entry]));
  return generated.map((entry) => {
    const found = previous.get(symbolKey(entry));
    if (!found) return entry;
    return {
      ...entry,
      adaptation: found.adaptation,
      declarationTest: found.declarationTest,
      evidenceApplicability: found.evidenceApplicability,
      realTmuxScenario: found.realTmuxScenario,
      reason: found.reason,
      status: found.status,
      typescript: found.typescript,
      typescriptSymbols: found.typescriptSymbols,
      unitTest: found.unitTest,
    };
  });
}

function publicSymbolsBounds(raw: string): { end: number; start: number } {
  const marker = '"publicSymbols":';
  const markerIndex = raw.indexOf(marker);
  if (markerIndex < 0) fail("manifest.publicSymbols text boundary is missing");
  const start = raw.indexOf("[", markerIndex + marker.length);
  if (start < 0) fail("manifest.publicSymbols array is missing");
  let depth = 0;
  let escaped = false;
  let quoted = false;
  for (let index = start; index < raw.length; index += 1) {
    const character = raw[index];
    if (quoted) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') quoted = false;
      continue;
    }
    if (character === '"') quoted = true;
    else if (character === "[") depth += 1;
    else if (character === "]") {
      depth -= 1;
      if (depth === 0) return { end: index + 1, start };
    }
  }
  fail("manifest.publicSymbols array is unterminated");
}

async function atomicWrite(path: string, contents: string): Promise<void> {
  const temporaryPath = join(
    dirname(path),
    `.${basename(path)}.${process.pid}.${randomUUID()}.tmp`,
  );
  try {
    const handle = await open(temporaryPath, "wx");
    try {
      await handle.writeFile(contents);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporaryPath, path);
  } catch (error) {
    await unlink(temporaryPath).catch(() => undefined);
    throw error;
  }
}

function renderUpdatedManifest(raw: string, symbols: PublicSymbol[]): string {
  const { end, start } = publicSymbolsBounds(raw);
  const rendered = JSON.stringify(symbols, null, 2).replaceAll("\n", "\n  ");
  return `${raw.slice(0, start)}${rendered}${raw.slice(end)}`;
}

function validateInventory(manifest: ParityManifest, expected: PublicSymbol[]): string[] {
  const problems: string[] = [];
  const actual = new Map(manifest.publicSymbols.map((entry) => [symbolKey(entry), entry]));
  const expectedByKey = new Map(expected.map((entry) => [symbolKey(entry), entry]));
  for (const [key, expectedEntry] of expectedByKey) {
    const actualEntry = actual.get(key);
    if (!actualEntry) {
      problems.push(`missing: ${key}`);
      continue;
    }
    for (const field of ["kind", "owner", "python", "source"] as const) {
      if (actualEntry[field] !== expectedEntry[field]) problems.push(`${key} has invalid ${field}`);
    }
  }
  for (const key of actual.keys()) {
    if (!expectedByKey.has(key)) problems.push(`unexpected: ${key}`);
  }
  return problems;
}

function validateSymbolPolicies(manifest: ParityManifest, expected: PublicSymbol[]): string[] {
  const expectedByKey = new Map(expected.map((entry) => [symbolKey(entry), entry]));
  const problems: string[] = [];
  for (const entry of manifest.publicSymbols) {
    const expectedEntry = expectedByKey.get(symbolKey(entry));
    if (
      expectedEntry &&
      JSON.stringify(entry.evidenceApplicability) !==
        JSON.stringify(expectedEntry.evidenceApplicability)
    ) {
      problems.push(`${symbolKey(entry)} has invalid evidence applicability`);
    }
  }
  return problems;
}

function parseArguments(arguments_: string[]): {
  allowBoundaryChange: boolean;
  manifestPath: string;
  packageManifestPath: string;
  write: boolean;
} {
  let allowBoundaryChange = false;
  let manifestPath = defaultManifestPath;
  let packageManifestPath = defaultPackageManifestPath;
  let write = false;
  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    if (argument === "--write") write = true;
    else if (argument === "--allow-boundary-change") allowBoundaryChange = true;
    else if (argument === "--manifest") {
      const value = arguments_[index + 1];
      if (!value) fail("--manifest requires a path");
      manifestPath = isAbsolute(value) ? value : resolve(process.cwd(), value);
      index += 1;
    } else if (argument === "--package-manifest") {
      const value = arguments_[index + 1];
      if (!value) fail("--package-manifest requires a path");
      packageManifestPath = isAbsolute(value) ? value : resolve(process.cwd(), value);
      index += 1;
    } else fail(`unknown argument: ${argument}`);
  }
  if (allowBoundaryChange && !write) fail("--allow-boundary-change requires --write");
  return { allowBoundaryChange, manifestPath, packageManifestPath, write };
}

try {
  const { allowBoundaryChange, manifestPath, packageManifestPath, write } = parseArguments(
    process.argv.slice(2),
  );
  if (!existsSync(manifestPath)) fail(`missing parity manifest: ${manifestPath}`);
  const raw = await readFile(manifestPath, "utf8");
  const manifest = parseManifest(JSON.parse(raw) as unknown);
  verifyBaseline(manifest);
  verifyManualProvenance(manifest);
  verifyEvidencePaths(manifest);
  await verifyTypeScriptSymbols(manifest, packageManifestPath);
  const expected = inventory();
  const policyProblems = validateSymbolPolicies(manifest, expected);
  if (policyProblems.length > 0) fail(policyProblems.join("\n"));

  if (write) {
    const expectedKeys = new Set(expected.map(symbolKey));
    const removed = manifest.publicSymbols.map(symbolKey).filter((key) => !expectedKeys.has(key));
    if (removed.length > 0 && !allowBoundaryChange) {
      fail(
        `removed public symbol keys require --allow-boundary-change:\n${removed
          .map((key) => `- ${key}`)
          .join("\n")}`,
      );
    }
    const updated = renderUpdatedManifest(raw, mergeSymbols(expected, manifest.publicSymbols));
    const updatedManifest = parseManifest(JSON.parse(updated) as unknown);
    verifyManualProvenance(updatedManifest);
    await atomicWrite(manifestPath, updated);
    console.log(`Parity manifest updated: ${expected.length} public symbols`);
  } else {
    const problems = validateInventory(manifest, expected);
    if (problems.length > 0) fail(problems.join("\n"));
    console.log(
      `Parity manifest valid: ${manifest.publicSymbols.length} public symbols, ${manifest.observableBehaviors.length} behaviors, ${manifest.typescriptExtensions.length} TypeScript extensions, ${manifest.internalExclusions.length} exclusions`,
    );
  }
} catch (error) {
  console.error((error as Error).message);
  process.exitCode = 1;
}
