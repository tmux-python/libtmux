import type { FormatFieldName } from "../../_generated/format_field_names.js";

/**
 * The tmux format vocabulary shared by the codec, the graph, and the handles.
 *
 * These types are internal. The public surface speaks in handles, selections,
 * and criteria; a consumer never names a list subcommand or a format scope.
 */
export type ListCommand = "list-clients" | "list-panes" | "list-sessions" | "list-windows";

export type OutputFormatField = Readonly<{ token: FormatFieldName }>;

export type TmuxVersionView = Readonly<{
  major: number;
  minor: number;
  raw: string;
  suffix: string;
}>;

/**
 * Nominal identity for a row the guard codec produced.
 *
 * Normalization refuses a row that did not come from the parser, and a plain
 * object literal cannot forge this prototype. The class carries no behaviour;
 * it exists so that check is unforgeable.
 *
 * The private constructor is load-bearing twice over. It stops a caller from
 * constructing a row outside the codec, and it makes the class nominal: without
 * a private member TypeScript compares it structurally against the merged
 * 178-property record, which inflates every relation that mentions a row.
 */
// eslint-disable-next-line typescript/no-unsafe-declaration-merging -- The merged interface exposes the frozen scalar row on the nominal class.
export class ParsedFormatRow {
  private constructor() {}
}

export interface ParsedFormatRow extends Readonly<Record<FormatFieldName, string | null>> {}
