function camelCase(value: string): string {
  return value.replace(/_([a-z0-9])/g, (_match, character: string) => character.toUpperCase());
}

import type { FormatFieldName, FormatScope, ListCommand } from "../../neo.js";
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

function criteriaWireName(field: GeneratedFormatField, model: CriteriaModel): string | undefined {
  if (field.scope !== model && field.scope !== "universal") return undefined;
  if (model === "session" && field.token === "session_name") return "name";
  if (model === "window" && field.token === "window_name") return "name";
  return field.token;
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

function renderFormatFieldsSource(fields: readonly GeneratedFormatField[]): string {
  const records = fields.map(
    ({ scope, since, token }) =>
      `  Object.freeze({ scope: ${JSON.stringify(scope)}, since: ${JSON.stringify(since)}, token: ${JSON.stringify(token)} }),`,
  );
  return [
    'import type { FormatFieldName, FormatScope } from "../neo.js";',
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

interface GeneratedWhereField {
  readonly domain: "string";
  readonly token: FormatFieldName;
  readonly wireName: string;
}

function generatedWhereFields(
  registry: readonly FormatFieldRecord[],
  model: CriteriaModel,
): readonly GeneratedWhereField[] {
  return registry
    .flatMap((field) => {
      const wireName = field.criteriaWireNames[model];
      return wireName === undefined
        ? []
        : [{ domain: "string" as const, token: field.token, wireName }];
    })
    .sort(
      (left, right) =>
        compareStrings(left.wireName, right.wireName) || compareStrings(left.token, right.token),
    );
}

function renderWhereFieldsSource(registry: readonly FormatFieldRecord[]): string {
  const lines = [
    'import type { FormatFieldName } from "../neo.js";',
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
      const criteriaName = camelCase(field.wireName);
      const oneLine = `  Object.freeze({ criteriaName: ${JSON.stringify(criteriaName)}, domain: "string", token: ${JSON.stringify(field.token)}, wireName: ${JSON.stringify(field.wireName)} }),`;
      if (oneLine.length <= 100) lines.push(oneLine);
      else {
        lines.push(
          "  Object.freeze({",
          `    criteriaName: ${JSON.stringify(criteriaName)},`,
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
): Readonly<Record<"format_fields.ts" | "where_fields.ts", string>> {
  const registry = createFormatRegistry(fields);
  return Object.freeze({
    "format_fields.ts": renderFormatFieldsSource(fields),
    "where_fields.ts": renderWhereFieldsSource(registry),
  });
}
