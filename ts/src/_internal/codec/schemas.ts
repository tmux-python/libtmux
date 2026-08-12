import { z } from "zod";

import { FORMAT_FIELD_TOKENS } from "../../_generated/format_fields.js";
import type { FormatFieldName, ListCommand } from "../../neo.js";

export type CompleteFormatRow = Readonly<Record<FormatFieldName, string | null>>;

/**
 * A complete row whose listing guarantees certain identities are populated.
 *
 * `normalizeGraph` rejects a row missing the identities its subcommand must
 * supply, so those fields cannot be null on a materialized handle. The set
 * differs per model — a session row guarantees only `session_id`, while a pane
 * row guarantees its whole ancestry — so the guarantee is expressed per model
 * rather than flattened onto every field.
 */
export type RowWithIdentities<Identities extends FormatFieldName> = {
  readonly [Key in FormatFieldName]: Key extends Identities ? string : string | null;
};

const completeFormatRowShape = Object.fromEntries(
  FORMAT_FIELD_TOKENS.map((token) => [token, z.string().nullable()]),
) as Record<FormatFieldName, z.ZodNullable<z.ZodString>>;
const completeFormatRowSchema = z.strictObject(completeFormatRowShape);
const identitySchemas: Readonly<Record<ListCommand, z.ZodType<string>>> = Object.freeze({
  "list-clients": z
    .string()
    .min(1)
    .refine((value) => !/^[%$@]/u.test(value)),
  "list-panes": z.string().regex(/^%\d+$/u),
  "list-sessions": z.string().regex(/^\$\d+$/u),
  "list-windows": z.string().regex(/^@\d+$/u),
});

function primaryIdentity(listCommand: ListCommand): FormatFieldName {
  switch (listCommand) {
    case "list-clients":
      return "client_name";
    case "list-panes":
      return "pane_id";
    case "list-sessions":
      return "session_id";
    case "list-windows":
      return "window_id";
  }
}

export function parseCompleteFormatRow(
  listCommand: ListCommand,
  row: CompleteFormatRow,
): CompleteFormatRow {
  const parsed = completeFormatRowSchema.parse(row) as CompleteFormatRow;
  parseFormatIdentity(listCommand, parsed[primaryIdentity(listCommand)]);
  return Object.freeze(parsed);
}

export function parseFormatIdentity(listCommand: ListCommand, value: unknown): string {
  return identitySchemas[listCommand].parse(value);
}
