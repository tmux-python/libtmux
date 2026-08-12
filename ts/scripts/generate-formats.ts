import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  GENERATED_FORMAT_FIELDS,
  type GeneratedFormatField,
} from "../src/_generated/format_fields.js";
import { renderGeneratedFormatSources } from "../src/_internal/codec/format_registry.js";

export interface GenerateFormatsOptions {
  readonly mode: "check" | "write";
  readonly neoSourcePath: string;
  readonly outputDirectory: string;
  readonly parityManifestPath: string;
  readonly selectionSourcePath?: string;
}

interface FixtureBaseline {
  readonly commit: string;
  readonly neoSourceSha256: string;
  readonly objFieldTokensSha256: string;
  readonly pythonVersion: string;
  readonly tag: string;
  readonly tree: string;
}

interface PythonFormatFixture {
  readonly baseline: FixtureBaseline;
  readonly fields: readonly GeneratedFormatField[];
}

interface TextReplacement {
  readonly end: number;
  readonly replacement: string;
  readonly start: number;
}

const usage = "usage: generate-formats.ts (--check|--write)";
const taskRoot = fileURLToPath(new URL("..", import.meta.url));
const fixturePath = join(taskRoot, "tests/fixtures/python-0.62.0-format-fields.json");
const neoSourceUrl = "https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/neo.py";
const formatsSourceUrl =
  "https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/formats.py";
const generatedRegionStart = "// <libtmux-generated-format-types>";
const generatedRegionEnd = "// </libtmux-generated-format-types>";
const generatedWhereRegionStart = "// <libtmux-generated-where-types>";
const generatedWhereRegionEnd = "// </libtmux-generated-where-types>";
const criteriaModels = ["session", "window", "pane"] as const;
const criteriaInterfaceNames = {
  pane: "PaneWhere",
  session: "SessionWhere",
  window: "WindowWhere",
} as const;
const whereRelationsV1 = {
  pane: [
    { cardinality: "one", name: "window", targetModel: "window" },
    { cardinality: "one", name: "session", targetModel: "session" },
  ],
  session: [
    { cardinality: "many", name: "windows", targetModel: "window" },
    { cardinality: "many", name: "panes", targetModel: "pane" },
    { cardinality: "one", name: "activeWindow", targetModel: "window" },
    { cardinality: "one", name: "activePane", targetModel: "pane" },
  ],
  window: [
    { cardinality: "one", name: "session", targetModel: "session" },
    { cardinality: "many", name: "linkedSessions", targetModel: "session" },
    { cardinality: "many", name: "panes", targetModel: "pane" },
    { cardinality: "one", name: "activePane", targetModel: "pane" },
  ],
} as const;
const expectedBaseline: FixtureBaseline = {
  commit: "38e368c11117fb4aeb2f082d552cd4f210eae06a",
  neoSourceSha256: "764264bf42bc305d1d97e9596806f004326c460e771f2a750429c75690afe82f",
  objFieldTokensSha256: "de09e5e1cf4d6749c3a9f77c211c0a1a94c7586559d8d08ed516f7c456f1c693",
  pythonVersion: "0.62.0",
  tag: "v0.62.0",
  tree: "eee900223a11c00a4b9b0cc6944e7d5a4d503bc8",
};
const allowedScopes = new Set([
  "buffer",
  "client",
  "context",
  "event",
  "pane",
  "session",
  "universal",
  "window",
]);

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  return JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...expected].sort());
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validateFixture(value: unknown): PythonFormatFixture {
  if (!isRecord(value) || !exactKeys(value, ["baseline", "fields"])) {
    throw new Error("format fixture must contain exactly baseline and fields");
  }
  if (!isRecord(value.baseline) || !exactKeys(value.baseline, Object.keys(expectedBaseline))) {
    throw new Error("format fixture baseline does not match the pinned schema");
  }
  if (JSON.stringify(value.baseline) !== JSON.stringify(expectedBaseline)) {
    throw new Error("format fixture baseline does not match Python 0.62.0");
  }
  if (!Array.isArray(value.fields) || value.fields.length !== 178) {
    throw new Error("format fixture must contain exactly 178 fields");
  }

  const fields = value.fields.map((candidate, index): GeneratedFormatField => {
    if (!isRecord(candidate) || !exactKeys(candidate, ["scope", "since", "token"])) {
      throw new Error(`format fixture field ${index} has an invalid shape`);
    }
    if (
      typeof candidate.scope !== "string" ||
      !allowedScopes.has(candidate.scope) ||
      typeof candidate.since !== "string" ||
      typeof candidate.token !== "string" ||
      candidate.token.length === 0
    ) {
      throw new Error(`format fixture field ${index} has invalid values`);
    }
    return Object.freeze(candidate) as unknown as GeneratedFormatField;
  });
  if (new Set(fields.map(({ token }) => token)).size !== fields.length) {
    throw new Error("format fixture field tokens must be unique");
  }
  const tokenDigest = createHash("sha256")
    .update(JSON.stringify(fields.map(({ token }) => token)))
    .digest("hex");
  if (tokenDigest !== expectedBaseline.objFieldTokensSha256) {
    throw new Error("format fixture field token digest does not match Python 0.62.0");
  }
  return Object.freeze({
    baseline: Object.freeze(value.baseline) as unknown as FixtureBaseline,
    fields: Object.freeze(fields),
  });
}

async function readFixture(): Promise<PythonFormatFixture> {
  return validateFixture(JSON.parse(await readFile(fixturePath, "utf8")) as unknown);
}

export function renderGeneratedNeoTypeRegion(
  fields: readonly GeneratedFormatField[] = GENERATED_FORMAT_FIELDS,
): string {
  const union = fields.map(({ token }) => `  | ${JSON.stringify(token)}`);
  return [
    generatedRegionStart,
    "export type FormatFieldName =",
    ...union.map((line, index) => (index === union.length - 1 ? `${line};` : line)),
    "",
    "export interface Obj extends Readonly<Record<FormatFieldName, string | null>> {}",
    generatedRegionEnd,
  ].join("\n");
}

function occurrenceCount(source: string, needle: string): number {
  return source.split(needle).length - 1;
}

export function renderNeoWithGeneratedTypes(
  source: string,
  fields: readonly GeneratedFormatField[] = GENERATED_FORMAT_FIELDS,
): string {
  if (
    occurrenceCount(source, generatedRegionStart) !== 1 ||
    occurrenceCount(source, generatedRegionEnd) !== 1
  ) {
    throw new Error("neo.ts must contain exactly one generated format type region");
  }
  const start = source.indexOf(generatedRegionStart);
  const endMarkerStart = source.indexOf(generatedRegionEnd, start);
  if (start < 0 || endMarkerStart < start) {
    throw new Error("neo.ts must contain exactly one generated format type region");
  }
  const end = endMarkerStart + generatedRegionEnd.length;
  return `${source.slice(0, start)}${renderGeneratedNeoTypeRegion(fields)}${source.slice(end)}`;
}

function criteriaWireName(
  field: GeneratedFormatField,
  model: (typeof criteriaModels)[number],
): string | undefined {
  if (field.scope !== model && field.scope !== "universal") return undefined;
  if (model === "session" && field.token === "session_name") return "name";
  if (model === "window" && field.token === "window_name") return "name";
  return field.token;
}

function generatedWhereFieldNames(
  fields: readonly GeneratedFormatField[],
  model: (typeof criteriaModels)[number],
): readonly string[] {
  return fields
    .flatMap((field) => {
      const wireName = criteriaWireName(field, model);
      return wireName === undefined ? [] : [camelCase(wireName)];
    })
    .sort();
}

function renderGeneratedWhereRelationsSource(): string {
  const lines = [
    "export interface WhereRelation {",
    '  readonly cardinality: "many" | "one";',
    "  readonly name: string;",
    "  readonly targetModel: WhereModel;",
    "}",
    "",
    "export const WHERE_RELATIONS_V1: Readonly<{",
  ];
  for (const model of ["pane", "session", "window"] as const) {
    lines.push(`  readonly ${model}: readonly [`);
    for (const relation of whereRelationsV1[model]) {
      lines.push(
        "    {",
        `      readonly cardinality: ${JSON.stringify(relation.cardinality)};`,
        `      readonly name: ${JSON.stringify(relation.name)};`,
        `      readonly targetModel: ${JSON.stringify(relation.targetModel)};`,
        "    },",
      );
    }
    lines.push("  ];");
  }
  lines.push("}> = Object.freeze({");
  for (const model of ["pane", "session", "window"] as const) {
    lines.push(`  ${model}: Object.freeze([`);
    for (const relation of whereRelationsV1[model]) {
      lines.push(
        `    Object.freeze({ cardinality: ${JSON.stringify(relation.cardinality)}, name: ${JSON.stringify(relation.name)}, targetModel: ${JSON.stringify(relation.targetModel)} }),`,
      );
    }
    lines.push("  ] as const),");
  }
  lines.push("} as const);", "");
  return lines.join("\n");
}

function renderGeneratedWhereFieldsSource(source: string): string {
  return `${source}\n${renderGeneratedWhereRelationsSource()}`;
}

export function renderGeneratedWhereTypeRegion(
  fields: readonly GeneratedFormatField[] = GENERATED_FORMAT_FIELDS,
): string {
  const lines = [generatedWhereRegionStart];
  for (const model of criteriaModels) {
    const interfaceName = criteriaInterfaceNames[model];
    lines.push(`export interface ${interfaceName} {`);
    lines.push(`  readonly AND?: readonly ${interfaceName}[];`);
    lines.push(`  readonly OR?: readonly ${interfaceName}[];`);
    lines.push(`  readonly NOT?: readonly ${interfaceName}[];`);
    for (const field of generatedWhereFieldNames(fields, model)) {
      lines.push(`  readonly ${field}?: ScalarCriteria;`);
    }
    for (const relation of whereRelationsV1[model]) {
      const relationType = relation.cardinality === "many" ? "ManyRelation" : "OneRelation";
      lines.push(
        `  readonly ${relation.name}?: ${relationType}<${criteriaInterfaceNames[relation.targetModel]}>;`,
      );
    }
    lines.push("}", "");
  }
  lines.push(generatedWhereRegionEnd);
  return lines.join("\n");
}

export function renderSelectionWithGeneratedWhereTypes(
  source: string,
  fields: readonly GeneratedFormatField[] = GENERATED_FORMAT_FIELDS,
): string {
  if (
    occurrenceCount(source, generatedWhereRegionStart) !== 1 ||
    occurrenceCount(source, generatedWhereRegionEnd) !== 1
  ) {
    throw new Error("selection.ts must contain exactly one generated where type marker pair");
  }
  const start = source.indexOf(generatedWhereRegionStart);
  const endMarkerStart = source.indexOf(generatedWhereRegionEnd, start);
  if (start < 0 || endMarkerStart < start) {
    throw new Error("selection.ts generated where type markers are misordered");
  }
  const end = endMarkerStart + generatedWhereRegionEnd.length;
  return `${source.slice(0, start)}${renderGeneratedWhereTypeRegion(fields)}${source.slice(end)}`;
}

function evidenceApplicability(): Record<string, string> {
  return {
    declarationTest: "required",
    realTmuxScenario: "not-applicable: symbol has no direct tmux I/O behavior",
    unitTest: "required",
  };
}

function canonicalPublicSymbol(input: {
  readonly adaptation: string | null;
  readonly declarationTest: string;
  readonly kind: "class" | "constant" | "format-field" | "function";
  readonly owner: string;
  readonly python: string;
  readonly source: string;
  readonly status: "adapted" | "implemented";
  readonly typescript: string;
  readonly typescriptSymbol: string;
  readonly unitTest: string;
}): Record<string, unknown> {
  return {
    adaptation: input.adaptation,
    declarationTest: input.declarationTest,
    kind: input.kind,
    owner: input.owner,
    python: input.python,
    realTmuxScenario: null,
    reason: null,
    source: input.source,
    status: input.status,
    typescript: input.typescript,
    unitTest: input.unitTest,
    evidenceApplicability: evidenceApplicability(),
    typescriptSymbols: [input.typescriptSymbol],
  };
}

function publicSymbolKey(value: Record<string, unknown>): string | undefined {
  return typeof value.kind === "string" && typeof value.python === "string"
    ? `${value.kind}:${value.python}`
    : undefined;
}

function task5PublicSymbols(
  fields: readonly GeneratedFormatField[],
): ReadonlyMap<string, Record<string, unknown>> {
  const rows: Record<string, unknown>[] = [];
  rows.push(
    canonicalPublicSymbol({
      adaptation:
        "TypeScript Obj is a frozen complete raw row with 178 string-or-null fields and no live Server reference",
      declarationTest: "tests/types/neo.test.ts",
      kind: "class",
      owner: "libtmux.neo",
      python: "libtmux.neo.Obj",
      source: neoSourceUrl,
      status: "adapted",
      typescript: "Obj",
      typescriptSymbol: "./neo#value:Obj",
      unitTest: "tests/unit/neo.test.ts",
    }),
  );
  for (const symbol of [
    "CLIENT_FORMATS",
    "FORMAT_SEPARATOR",
    "PANE_FORMATS",
    "SESSION_FORMATS",
    "WINDOW_FORMATS",
  ]) {
    rows.push(
      canonicalPublicSymbol({
        adaptation: null,
        declarationTest: "tests/types/formats.test.ts",
        kind: "constant",
        owner: "libtmux.formats",
        python: `libtmux.formats.${symbol}`,
        source: formatsSourceUrl,
        status: "implemented",
        typescript: symbol,
        typescriptSymbol: `./formats#value:${symbol}`,
        unitTest: "tests/unit/formats.test.ts",
      }),
    );
  }
  for (const symbol of ["FIELD_VERSION", "SCOPES_BY_LIST_CMD"]) {
    rows.push(
      canonicalPublicSymbol({
        adaptation: null,
        declarationTest: "tests/types/neo.test.ts",
        kind: "constant",
        owner: "libtmux.neo",
        python: `libtmux.neo.${symbol}`,
        source: neoSourceUrl,
        status: "implemented",
        typescript: symbol,
        typescriptSymbol: `./neo#value:${symbol}`,
        unitTest: "tests/unit/neo.test.ts",
      }),
    );
  }
  for (const { token } of fields) {
    rows.push(
      canonicalPublicSymbol({
        adaptation:
          "TypeScript complete rows preserve empty strings and use null only for unsupported fields",
        declarationTest: "tests/types/neo.test.ts",
        kind: "format-field",
        owner: "libtmux.neo.Obj",
        python: `libtmux.neo.Obj.${token}`,
        source: neoSourceUrl,
        status: "adapted",
        typescript: `Obj.${token}`,
        typescriptSymbol: `./neo#instance:Obj.${token}`,
        unitTest: "tests/unit/neo.test.ts",
      }),
    );
  }
  rows.push(
    canonicalPublicSymbol({
      adaptation:
        "getOutputFormat returns an immutable privately branded guarded parse plan selected from a raw daemon version",
      declarationTest: "tests/types/neo.test.ts",
      kind: "function",
      owner: "libtmux.neo",
      python: "libtmux.neo.get_output_format",
      source: neoSourceUrl,
      status: "adapted",
      typescript: "getOutputFormat",
      typescriptSymbol: "./neo#value:getOutputFormat",
      unitTest: "tests/unit/neo.test.ts",
    }),
    canonicalPublicSymbol({
      adaptation:
        "parseOutput consumes bytes with the exact request-bound guarded plan and returns frozen complete Obj rows",
      declarationTest: "tests/types/neo.test.ts",
      kind: "function",
      owner: "libtmux.neo",
      python: "libtmux.neo.parse_output",
      source: neoSourceUrl,
      status: "adapted",
      typescript: "parseOutput",
      typescriptSymbol: "./neo#value:parseOutput",
      unitTest: "tests/unit/neo.test.ts",
    }),
  );
  const keyed = rows.map((row): readonly [string, Record<string, unknown>] => {
    const key = publicSymbolKey(row);
    if (key === undefined) throw new Error("generated Task 5 parity row has no key");
    return [key, row];
  });
  if (keyed.length !== 188 || new Set(keyed.map(([key]) => key)).size !== keyed.length) {
    throw new Error("generated Task 5 parity inventory must contain exactly 188 unique rows");
  }
  return new Map(keyed);
}

function arrayBounds(
  source: string,
  property: string,
): { readonly end: number; readonly start: number } {
  const markerIndex = source.indexOf(`"${property}":`);
  const start = source.indexOf("[", markerIndex);
  if (markerIndex < 0 || start < 0) throw new Error(`parity manifest ${property} array is missing`);
  let depth = 0;
  let escaped = false;
  let quoted = false;
  for (let index = start; index < source.length; index += 1) {
    const character = source[index]!;
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
  throw new Error(`parity manifest ${property} array is unterminated`);
}

function objectBounds(
  source: string,
  bounds: { readonly end: number; readonly start: number },
): Array<{
  readonly end: number;
  readonly start: number;
}> {
  const objects: Array<{ readonly end: number; readonly start: number }> = [];
  let depth = 0;
  let escaped = false;
  let objectStart = -1;
  let quoted = false;
  for (let index = bounds.start + 1; index < bounds.end - 1; index += 1) {
    const character = source[index]!;
    if (quoted) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') quoted = false;
      continue;
    }
    if (character === '"') quoted = true;
    else if (character === "{") {
      if (depth === 0) objectStart = index;
      depth += 1;
    } else if (character === "}") {
      depth -= 1;
      if (depth === 0 && objectStart >= 0) {
        objects.push({ end: index + 1, start: objectStart });
        objectStart = -1;
      }
    }
  }
  if (depth !== 0) throw new Error("parity manifest publicSymbols object is unterminated");
  return objects;
}

function renderPublicSymbol(row: Record<string, unknown>, indentation: string): string {
  const rendered = JSON.stringify(row, null, 2).replace(
    /"typescriptSymbols": \[\n    ("(?:[^"\\]|\\.)*")\n  \]/u,
    '"typescriptSymbols": [$1]',
  );
  return rendered.replaceAll("\n", `\n${indentation}`);
}

export function renderTask5ParityManifest(
  source: string,
  fields: readonly GeneratedFormatField[] = GENERATED_FORMAT_FIELDS,
): string {
  const expected = task5PublicSymbols(fields);
  const bounds = arrayBounds(source, "publicSymbols");
  const replacements: TextReplacement[] = [];
  const seen = new Set<string>();
  for (const object of objectBounds(source, bounds)) {
    const parsed = JSON.parse(source.slice(object.start, object.end)) as unknown;
    if (!isRecord(parsed)) continue;
    const key = publicSymbolKey(parsed);
    if (key === undefined || !expected.has(key)) continue;
    if (seen.has(key)) throw new Error(`parity manifest contains duplicate Task 5 row: ${key}`);
    seen.add(key);
    const lineStart = source.lastIndexOf("\n", object.start - 1) + 1;
    const indentation = source.slice(lineStart, object.start);
    replacements.push({
      end: object.end,
      replacement: renderPublicSymbol(expected.get(key)!, indentation),
      start: object.start,
    });
  }
  if (seen.size !== expected.size) {
    const missing = [...expected.keys()].filter((key) => !seen.has(key));
    throw new Error(`parity manifest is missing Task 5 rows: ${missing.join(", ")}`);
  }
  let rendered = source;
  for (const replacement of replacements.reverse()) {
    rendered = `${rendered.slice(0, replacement.start)}${replacement.replacement}${rendered.slice(replacement.end)}`;
  }
  return rendered;
}

async function readIfPresent(path: string): Promise<string | undefined> {
  try {
    return await readFile(path, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw error;
  }
}

const ALIAS_MODELS = ["session", "window", "pane", "client"] as const;
type AliasModel = (typeof ALIAS_MODELS)[number];

function camelCase(value: string): string {
  return value.replace(/_([a-z0-9])/g, (_match, character: string) => character.toUpperCase());
}

/**
 * The property name a model exposes for a tmux format token.
 *
 * A model drops its own prefix, so a session reads `session_name` as `name`
 * while a pane keeps `sessionName` for the same token. tmux's own spelling
 * stays reachable through the raw row.
 */
function aliasFor(token: string, model: AliasModel): string {
  const stripped = token.startsWith(`${model}_`) ? token.slice(model.length + 1) : token;
  return camelCase(stripped);
}

/**
 * Assign each token a property name, dropping the model's prefix where it is
 * unambiguous.
 *
 * Dropping is refused when the shortened name is already some other token's own
 * name: tmux exposes both `pid` and `pane_pid`, so a pane keeps `panePid` and
 * leaves `pid` meaning what tmux means by it.
 */
/**
 * Member names the handle classes already own.
 *
 * A de-stuttered scalar must never shadow a relation or operation: tmux's
 * `client_session` shortens to `session`, which is the client's session
 * relation, so that token keeps its longer name instead.
 */
const RESERVED_MEMBERS: ReadonlySet<string> = new Set([
  "breakOut",
  "capture",
  "chooseBuffer",
  "chooseTree",
  "clearHistory",
  "clients",
  "customizeMode",
  "detach",
  "displayMenu",
  "displayMessage",
  "displayPopup",
  "enterCopyMode",
  "equals",
  "exitCopyMode",
  "findWindow",
  "format",
  "joinTo",
  "kill",
  "link",
  "linkedSessions",
  "move",
  "newSession",
  "newWindow",
  "pane",
  "panes",
  "refresh",
  "rename",
  "resize",
  "respawn",
  "select",
  "selectLayout",
  "selectWindow",
  "sendKeys",
  "sendPrefix",
  "server",
  "session",
  "sessions",
  "setHook",
  "setOption",
  "showHooks",
  "showOptions",
  "snapshot",
  "split",
  "swapWith",
  "switchTo",
  "unlink",
  "unsetHook",
  "unsetOption",
  "window",
  "windows",
]);

function aliasesForModel(
  tokens: readonly string[],
  model: AliasModel,
): ReadonlyMap<string, string> {
  const reserved = new Set(tokens.map((token) => camelCase(token)));
  const aliases = new Map<string, string>();
  for (const token of tokens) {
    const full = camelCase(token);
    const stripped = aliasFor(token, model);
    const shortened =
      stripped !== full &&
      !reserved.has(stripped) &&
      !RESERVED_MEMBERS.has(stripped) &&
      !aliases.has(stripped);
    const alias = shortened ? stripped : full;
    const clash = aliases.get(alias);
    if (clash !== undefined) {
      throw new Error(`alias collision for ${model}: ${clash} and ${token} both map to ${alias}`);
    }
    aliases.set(alias, token);
  }
  return aliases;
}

function renderFieldAliasesSource(tokens: readonly string[]): string {
  const lines = ["// Generated by scripts/generate-formats.ts. Do not edit.", ""];
  for (const model of ALIAS_MODELS) {
    const seen = aliasesForModel(tokens, model);
    const constant = `${model.toUpperCase()}_ALIASES`;
    const local = `${model}Aliases`;
    const typeName = `${model[0]!.toUpperCase()}${model.slice(1)}AliasMap`;
    lines.push(
      `const ${local} = {`,
      ...[...seen].map(([alias, token]) => `  ${alias}: "${token}",`),
      "} as const;",
      "",
      `export type ${typeName} = typeof ${local};`,
      "",
      `export const ${constant}: ${typeName} = Object.freeze(${local});`,
      "",
    );
  }
  return lines.join("\n");
}

export async function generateFormats(options: GenerateFormatsOptions): Promise<void> {
  const fixture = await readFixture();
  const generated = renderGeneratedFormatSources(fixture.fields);
  const currentNeo = await readFile(options.neoSourcePath, "utf8");
  const currentParity = await readFile(options.parityManifestPath, "utf8");
  const expected = new Map<string, string>([
    [join(options.outputDirectory, "format_fields.ts"), generated["format_fields.ts"]],
    [
      join(options.outputDirectory, "field_aliases.ts"),
      renderFieldAliasesSource(fixture.fields.map(({ token }) => token)),
    ],
    [
      join(options.outputDirectory, "where_fields.ts"),
      renderGeneratedWhereFieldsSource(generated["where_fields.ts"]),
    ],
    [options.neoSourcePath, renderNeoWithGeneratedTypes(currentNeo, fixture.fields)],
    [options.parityManifestPath, renderTask5ParityManifest(currentParity, fixture.fields)],
  ]);
  if (options.selectionSourcePath !== undefined) {
    const currentSelection = await readFile(options.selectionSourcePath, "utf8");
    expected.set(
      options.selectionSourcePath,
      renderSelectionWithGeneratedWhereTypes(currentSelection, fixture.fields),
    );
  }
  const expectedEntries = [...expected];
  const actual = await Promise.all(expectedEntries.map(([path]) => readIfPresent(path)));
  const stale = expectedEntries.filter(([, contents], index) => actual[index] !== contents);
  if (options.mode === "check") {
    if (stale.length > 0) throw new Error("generated format outputs are out of date");
    return;
  }
  await Promise.all(stale.map(([path]) => mkdir(dirname(path), { recursive: true })));
  await Promise.all(stale.map(([path, contents]) => writeFile(path, contents)));
}

if (import.meta.main) {
  const arguments_ = process.argv.slice(2);
  if (arguments_.length !== 1 || (arguments_[0] !== "--check" && arguments_[0] !== "--write")) {
    console.error(usage);
    process.exitCode = 2;
  } else {
    try {
      await generateFormats({
        mode: arguments_[0] === "--check" ? "check" : "write",
        neoSourcePath: join(taskRoot, "src/neo.ts"),
        outputDirectory: join(taskRoot, "src/_generated"),
        parityManifestPath: join(taskRoot, "parity/python-0.62.0.json"),
        selectionSourcePath: join(taskRoot, "src/selection.ts"),
      });
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    }
  }
}
