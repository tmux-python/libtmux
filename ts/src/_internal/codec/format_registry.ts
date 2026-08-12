function camelCase(value: string): string {
  return value.replace(/_([a-z0-9])/g, (_match, character: string) => character.toUpperCase());
}

import type { FormatFieldName, FormatScope } from "../../_generated/format_field_names.js";
import type { ListCommand } from "./format_types.js";
import {
  GENERATED_FORMAT_FIELDS,
  type GeneratedFormatField,
} from "../../_generated/format_fields.js";
import {
  compareTmuxVersions,
  parseTmuxVersion,
  type TmuxVersion,
} from "../runtime/tmux_version.js";

export type SnapshotDestination =
  | "client"
  | "pane"
  | "raw-row"
  | "server"
  | "session"
  | "window"
  | "winlink";

export type CriteriaModel = "pane" | "session" | "window";

export interface FormatFieldRecord {
  readonly criteriaWireNames: Readonly<Partial<Record<CriteriaModel, string>>>;
  readonly rawRepresentation: "string";
  readonly scalarFilterDomain: "string" | null;
  readonly scope: FormatScope;
  readonly since: TmuxVersion;
  readonly snapshotDestination: SnapshotDestination;
  readonly token: FormatFieldName;
}

export interface WhereSchemaVersion {
  readonly aliases: Readonly<Record<CriteriaModel, Readonly<Record<string, string>>>>;
  readonly fields: Readonly<Record<CriteriaModel, readonly string[]>>;
  readonly version: number;
}

const criteriaModels = ["session", "window", "pane"] as const;

export interface CriteriaRelation {
  readonly cardinality: "many" | "one";
  readonly name: string;
  readonly targetModel: CriteriaModel;
}

/**
 * The relations each model can be filtered through.
 *
 * These share a namespace with the scalar criteria, so they live beside the
 * naming rule: a scalar that would collide with a relation keeps its model
 * prefix instead of silently shadowing it.
 */
export const CRITERIA_RELATIONS_V1: Readonly<Record<CriteriaModel, readonly CriteriaRelation[]>> =
  Object.freeze({
    pane: Object.freeze([
      Object.freeze({
        cardinality: "one" as const,
        name: "window",
        targetModel: "window" as const,
      }),
      Object.freeze({
        cardinality: "one" as const,
        name: "session",
        targetModel: "session" as const,
      }),
    ]),
    session: Object.freeze([
      Object.freeze({
        cardinality: "many" as const,
        name: "windows",
        targetModel: "window" as const,
      }),
      Object.freeze({ cardinality: "many" as const, name: "panes", targetModel: "pane" as const }),
      Object.freeze({
        cardinality: "one" as const,
        name: "activeWindow",
        targetModel: "window" as const,
      }),
      Object.freeze({
        cardinality: "one" as const,
        name: "activePane",
        targetModel: "pane" as const,
      }),
    ]),
    window: Object.freeze([
      Object.freeze({
        cardinality: "one" as const,
        name: "session",
        targetModel: "session" as const,
      }),
      Object.freeze({
        cardinality: "many" as const,
        name: "linkedSessions",
        targetModel: "session" as const,
      }),
      Object.freeze({ cardinality: "many" as const, name: "panes", targetModel: "pane" as const }),
      Object.freeze({
        cardinality: "one" as const,
        name: "activePane",
        targetModel: "pane" as const,
      }),
    ]),
  });
const winlinkTokens: ReadonlySet<string> = new Set([
  "window_active",
  "window_activity_flag",
  "window_bell_flag",
  "window_end_flag",
  "window_flags",
  "window_index",
  "window_last_flag",
  "window_marked_flag",
  "window_raw_flags",
  "window_silence_flag",
  "window_stack_index",
  "window_start_flag",
]);
const rawRowWindowTokens: ReadonlySet<string> = new Set([
  "window_bigger",
  "window_format",
  "window_offset_x",
  "window_offset_y",
]);
const rawRowScopes: ReadonlySet<FormatScope> = new Set(["buffer", "context", "event"]);
const ordinaryListScopes: readonly FormatScope[] = Object.freeze([
  "universal",
  "session",
  "window",
  "pane",
]);
const clientListScopes: readonly FormatScope[] = Object.freeze([...ordinaryListScopes, "client"]);

export const FORMAT_SCOPES_BY_LIST_COMMAND: Readonly<Record<ListCommand, readonly FormatScope[]>> =
  Object.freeze({
    "list-clients": clientListScopes,
    "list-panes": ordinaryListScopes,
    "list-sessions": ordinaryListScopes,
    "list-windows": ordinaryListScopes,
  });

function compareStrings(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

/**
 * The stable serialized name for a field, or undefined when the model cannot
 * be filtered by it.
 *
 * Universal-scope fields carry the same value on every row of a server —
 * `version`, `pid`, `socket_path` and friends — so filtering by one matches
 * all rows or none. They stay readable through the snapshot; they are not
 * criteria.
 */
function criteriaWireName(field: GeneratedFormatField, model: CriteriaModel): string | undefined {
  if (field.scope !== model) return undefined;
  if (model === "session" && field.token === "session_name") return "name";
  if (model === "window" && field.token === "window_name") return "name";
  return field.token;
}

/**
 * The camelCase key a caller writes, which matches the handle accessor.
 *
 * A pane reads `pane.currentCommand`, so it filters on `currentCommand`. The
 * model is already named by the selection being filtered, so repeating it in
 * every key buys nothing. Only the wire name is fixed by the schema.
 */
function criteriaName(token: string, model: CriteriaModel, taken: ReadonlySet<string>): string {
  const prefix = `${model}_`;
  if (!token.startsWith(prefix)) return camelCase(token);
  const stripped = camelCase(token.slice(prefix.length));
  // `session_windows` is a window count, not the windows relation. When the
  // short name is already spoken for, the unambiguous one wins.
  return taken.has(stripped) ? camelCase(token) : stripped;
}

function snapshotDestination(field: GeneratedFormatField): SnapshotDestination {
  if (winlinkTokens.has(field.token)) return "winlink";
  if (
    rawRowWindowTokens.has(field.token) ||
    field.token === "line" ||
    rawRowScopes.has(field.scope)
  ) {
    return "raw-row";
  }
  if (field.scope === "universal") return "server";
  if (
    field.scope === "client" ||
    field.scope === "pane" ||
    field.scope === "session" ||
    field.scope === "window"
  ) {
    return field.scope;
  }
  return "raw-row";
}

function createFormatRegistry(
  fields: readonly GeneratedFormatField[],
): readonly FormatFieldRecord[] {
  const records = fields.map((field): FormatFieldRecord => {
    const criteriaEntries = criteriaModels.flatMap((model) => {
      const wireName = criteriaWireName(field, model);
      return wireName === undefined ? [] : ([[model, wireName]] as const);
    });
    const criteriaWireNames = Object.freeze(Object.fromEntries(criteriaEntries)) as Readonly<
      Partial<Record<CriteriaModel, string>>
    >;
    return Object.freeze({
      criteriaWireNames,
      rawRepresentation: "string",
      scalarFilterDomain: criteriaEntries.length === 0 ? null : "string",
      scope: field.scope,
      since: parseTmuxVersion(field.since),
      snapshotDestination: snapshotDestination(field),
      token: field.token,
    });
  });
  return Object.freeze(records);
}

export const FORMAT_REGISTRY: readonly FormatFieldRecord[] =
  createFormatRegistry(GENERATED_FORMAT_FIELDS);

const formatFieldsByToken: ReadonlyMap<string, FormatFieldRecord> = new Map(
  FORMAT_REGISTRY.map((field) => [field.token, field]),
);

export function lookupFormatField(token: string): FormatFieldRecord | undefined {
  return formatFieldsByToken.get(token);
}

export function formatFieldsForListCommand(
  listCommand: ListCommand,
  rawVersion: string,
): readonly FormatFieldRecord[] {
  const version = parseTmuxVersion(rawVersion);
  const scopes: ReadonlySet<FormatScope> = new Set(FORMAT_SCOPES_BY_LIST_COMMAND[listCommand]);
  return Object.freeze(
    FORMAT_REGISTRY.filter(
      (field) => scopes.has(field.scope) && compareTmuxVersions(version, field.since) >= 0,
    ),
  );
}

export function validateWhereSchemaHistory(history: readonly WhereSchemaVersion[]): void {
  const previouslyShipped: Record<CriteriaModel, Set<string>> = {
    pane: new Set(),
    session: new Set(),
    window: new Set(),
  };

  for (const schema of history) {
    for (const model of criteriaModels) {
      const aliases = schema.aliases[model];
      if (schema.version === 1 && Object.keys(aliases).length > 0) {
        throw new Error("schema version 1 cannot contain aliases");
      }
      for (const [alias, canonical] of Object.entries(aliases)) {
        if (!previouslyShipped[model].has(alias)) {
          throw new Error("alias must name a field from an earlier schema");
        }
        if (!schema.fields[model].includes(canonical)) {
          throw new Error("alias target must name a field in the current schema");
        }
      }
    }
    for (const model of criteriaModels) {
      for (const field of schema.fields[model]) previouslyShipped[model].add(field);
    }
  }
}

/**
 * The format vocabulary is emitted without values so the modules that only
 * need the token names never import the field table, and so nothing has to
 * import back into the registry to name a scope.
 */
function renderFormatFieldNamesSource(fields: readonly GeneratedFormatField[]): string {
  const union = fields.map(({ token }) => `  | ${JSON.stringify(token)}`);
  return [
    "export type FormatScope =",
    '  | "buffer"',
    '  | "client"',
    '  | "context"',
    '  | "event"',
    '  | "pane"',
    '  | "session"',
    '  | "universal"',
    '  | "window";',
    "",
    "export type FormatFieldName =",
    ...union.map((line, index) => (index === union.length - 1 ? `${line};` : line)),
    "",
  ].join("\n");
}

function renderFormatFieldsSource(fields: readonly GeneratedFormatField[]): string {
  const records = fields.map(
    ({ scope, since, token }) =>
      `  Object.freeze({ scope: ${JSON.stringify(scope)}, since: ${JSON.stringify(since)}, token: ${JSON.stringify(token)} }),`,
  );
  return [
    'import type { FormatFieldName, FormatScope } from "./format_field_names.js";',
    "",
    "export interface GeneratedFormatField {",
    "  readonly scope: FormatScope;",
    "  readonly since: string;",
    "  readonly token: FormatFieldName;",
    "}",
    "",
    "const generatedFormatFields: readonly GeneratedFormatField[] = Object.freeze([",
    ...records,
    "]);",
    "",
    "export const GENERATED_FORMAT_FIELDS: readonly GeneratedFormatField[] = generatedFormatFields;",
    "",
    "export const FORMAT_FIELD_TOKENS: readonly FormatFieldName[] = Object.freeze(",
    "  generatedFormatFields.map(({ token }) => token),",
    ");",
    "",
  ].join("\n");
}

export interface GeneratedWhereField {
  readonly criteriaName: string;
  readonly domain: "string";
  readonly token: FormatFieldName;
  readonly wireName: string;
}

/**
 * The criteria a model accepts, in serialized order.
 *
 * This is the only place the criteria rule lives. The generator renders both
 * the metadata table and the `Where` interfaces from it, so the key a caller
 * writes and the key the type offers cannot drift apart.
 */
export function criteriaFieldsForModel(
  fields: readonly GeneratedFormatField[],
  model: CriteriaModel,
): readonly GeneratedWhereField[] {
  return generatedWhereFields(createFormatRegistry(fields), model);
}

function generatedWhereFields(
  registry: readonly FormatFieldRecord[],
  model: CriteriaModel,
): readonly GeneratedWhereField[] {
  const taken = new Set<string>(CRITERIA_RELATIONS_V1[model].map(({ name }) => name));
  for (const field of registry) {
    const wireName = field.criteriaWireNames[model];
    if (wireName !== undefined && !field.token.startsWith(`${model}_`)) {
      taken.add(camelCase(field.token));
    }
  }
  return registry
    .flatMap((field) => {
      const wireName = field.criteriaWireNames[model];
      return wireName === undefined
        ? []
        : [
            {
              criteriaName: criteriaName(field.token, model, taken),
              domain: "string" as const,
              token: field.token,
              wireName,
            },
          ];
    })
    .sort(
      (left, right) =>
        compareStrings(left.wireName, right.wireName) || compareStrings(left.token, right.token),
    );
}

function renderWhereFieldsSource(registry: readonly FormatFieldRecord[]): string {
  const lines = [
    'import type { FormatFieldName } from "./format_field_names.js";',
    "",
    'export type WhereModel = "pane" | "session" | "window";',
    "",
    "export interface WhereField {",
    "  /** The camelCase key a caller writes in criteria. */",
    "  readonly criteriaName: string;",
    '  readonly domain: "string";',
    "  readonly token: FormatFieldName;",
    "  /** The stable serialized name, unchanged across releases. */",
    "  readonly wireName: string;",
    "}",
    "",
  ];
  for (const model of criteriaModels) {
    lines.push(`const ${model}Fields: readonly WhereField[] = Object.freeze([`);
    for (const field of generatedWhereFields(registry, model)) {
      const oneLine = `  Object.freeze({ criteriaName: ${JSON.stringify(field.criteriaName)}, domain: "string", token: ${JSON.stringify(field.token)}, wireName: ${JSON.stringify(field.wireName)} }),`;
      if (oneLine.length <= 100) lines.push(oneLine);
      else {
        lines.push(
          "  Object.freeze({",
          `    criteriaName: ${JSON.stringify(field.criteriaName)},`,
          '    domain: "string",',
          `    token: ${JSON.stringify(field.token)},`,
          `    wireName: ${JSON.stringify(field.wireName)},`,
          "  }),",
        );
      }
    }
    lines.push("]);", "");
  }
  lines.push(
    "const emptyAliases: Readonly<Record<string, string>> = Object.freeze({});",
    "",
    "export const WHERE_FIELDS_V1: Readonly<Record<WhereModel, readonly WhereField[]>> = Object.freeze({",
    "  session: sessionFields,",
    "  window: windowFields,",
    "  pane: paneFields,",
    "});",
    "",
    "export const WHERE_ALIASES_V1: Readonly<Record<WhereModel, Readonly<Record<string, string>>>> =",
    "  Object.freeze({",
    "    session: emptyAliases,",
    "    window: emptyAliases,",
    "    pane: emptyAliases,",
    "  });",
    "",
  );
  return lines.join("\n");
}

export function renderGeneratedFormatSources(
  fields: readonly GeneratedFormatField[] = GENERATED_FORMAT_FIELDS,
): Readonly<Record<"format_field_names.ts" | "format_fields.ts" | "where_fields.ts", string>> {
  const registry = createFormatRegistry(fields);
  return Object.freeze({
    "format_field_names.ts": renderFormatFieldNamesSource(fields),
    "format_fields.ts": renderFormatFieldsSource(fields),
    "where_fields.ts": renderWhereFieldsSource(registry),
  });
}
