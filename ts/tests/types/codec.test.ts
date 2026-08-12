import { FORMAT_FIELD_TOKENS } from "../../src/_generated/format_fields.js";
import type { GuardedFetchOptions } from "../../src/_internal/codec/guard_codec.js";
import type { FormatFieldRecord } from "../../src/_internal/codec/format_registry.js";
import type { FormatFieldName } from "../../src/_generated/format_field_names.js";

import type { Equal, Expect } from "./assert.js";

declare const base: Pick<GuardedFetchOptions, "capabilities" | "connection" | "transport">;

const sessionFetch = {
  ...base,
  identityField: "session_id",
  identityValue: "$1",
  listCommand: "list-sessions",
} satisfies GuardedFetchOptions;
const windowFetch = {
  ...base,
  identityField: "window_id",
  identityValue: "@1",
  listCommand: "list-windows",
} satisfies GuardedFetchOptions;
const paneFetch = {
  ...base,
  identityField: "pane_id",
  identityValue: "%1",
  listCommand: "list-panes",
} satisfies GuardedFetchOptions;
const clientFetch = {
  ...base,
  identityField: "client_name",
  identityValue: "/dev/pts/1",
  listCommand: "list-clients",
} satisfies GuardedFetchOptions;

void sessionFetch;
void windowFetch;
void paneFetch;
void clientFetch;

// @ts-expect-error Session listing identity is session_id.
const invalidSessionFetch: GuardedFetchOptions = {
  ...base,
  identityField: "window_id",
  identityValue: "$1",
  listCommand: "list-sessions",
};
// @ts-expect-error Window listing identity is window_id.
const invalidWindowFetch: GuardedFetchOptions = {
  ...base,
  identityField: "pane_id",
  identityValue: "@1",
  listCommand: "list-windows",
};
// @ts-expect-error Pane listing identity is pane_id.
const invalidPaneFetch: GuardedFetchOptions = {
  ...base,
  identityField: "client_name",
  identityValue: "%1",
  listCommand: "list-panes",
};
// @ts-expect-error Client listing identity is client_name.
const invalidClientFetch: GuardedFetchOptions = {
  ...base,
  identityField: "session_id",
  identityValue: "/dev/pts/1",
  listCommand: "list-clients",
};

void invalidSessionFetch;
void invalidWindowFetch;
void invalidPaneFetch;
void invalidClientFetch;

const validSnapshotDestination: FormatFieldRecord["snapshotDestination"] = "raw-row";
void validSnapshotDestination;
// @ts-expect-error Snapshot destinations are a closed policy vocabulary.
const invalidSnapshotDestination: FormatFieldRecord["snapshotDestination"] = "arbitrary";
void invalidSnapshotDestination;

type _GeneratedFormatToken = Expect<Equal<(typeof FORMAT_FIELD_TOKENS)[number], FormatFieldName>>;
// @ts-expect-error The generated format inventory is readonly.
FORMAT_FIELD_TOKENS.push("session_name");
// @ts-expect-error The generated format inventory does not permit indexed assignment.
FORMAT_FIELD_TOKENS[0] = "session_name";
