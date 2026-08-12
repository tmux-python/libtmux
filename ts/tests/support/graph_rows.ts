import { FORMAT_FIELD_TOKENS } from "../../src/_generated/format_fields.js";
import type { CompleteFormatRow } from "../../src/_internal/codec/schemas.js";
import type { FormatFieldName } from "../../src/neo.js";

export type MutableCompleteFormatRow = {
  -readonly [Field in FormatFieldName]: string | null;
};

export function completeFormatRow(
  overrides: Readonly<Partial<Record<FormatFieldName, string | null>>> = {},
): MutableCompleteFormatRow & CompleteFormatRow {
  return Object.assign(
    Object.fromEntries(
      FORMAT_FIELD_TOKENS.map((token) => [token, null]),
    ) as MutableCompleteFormatRow,
    overrides,
  );
}
