import {
  FIELD_VERSION,
  Obj,
  SCOPES_BY_LIST_CMD,
  getOutputFormat,
  parseOutput,
  type FormatFieldName,
  type FormatScope,
  type ListCommand,
  type OutputFormatField,
  type OutputFormatPlan,
  type TmuxVersionView,
} from "../../src/neo.js";
// @ts-expect-error Server is not part of the pure neo module.
import type { Server as LeakedServer } from "../../src/neo.js";
// @ts-expect-error Transport types are internal.
import type { CommandTransport as LeakedCommandTransport } from "../../src/neo.js";
// @ts-expect-error Capability snapshots are internal.
import type { TmuxCapabilities as LeakedTmuxCapabilities } from "../../src/neo.js";
// @ts-expect-error Guard factories are internal.
import type { GuardFactory as LeakedGuardFactory } from "../../src/neo.js";
// @ts-expect-error GuardCodec is internal.
import type { GuardCodec as LeakedGuardCodec } from "../../src/neo.js";
// @ts-expect-error FormatProtocolError is internal.
import type { FormatProtocolError as LeakedFormatProtocolError } from "../../src/neo.js";

import type { Equal, Expect } from "./assert.js";

type _ForbiddenNeoExports = [
  LeakedServer,
  LeakedCommandTransport,
  LeakedTmuxCapabilities,
  LeakedGuardFactory,
  LeakedGuardCodec,
  LeakedFormatProtocolError,
];

type StringKeys<T> = Extract<keyof T, string>;
type WritableKeys<T> = {
  [Key in keyof T]-?: Equal<Pick<T, Key>, Readonly<Pick<T, Key>>> extends true ? never : Key;
}[keyof T];

const plan = getOutputFormat("list-sessions", "3.7b");
const rows = parseOutput(plan, new Uint8Array());
declare const row: Obj;
declare const structuralPlan: Pick<OutputFormatPlan, StringKeys<OutputFormatPlan>>;

void FIELD_VERSION.pane_x;
void SCOPES_BY_LIST_CMD["list-sessions"];
void plan.fields;
void plan.format;
void plan.guards;
void plan.listCommand;
void plan.tmuxVersion;
void row.session_name;
void row.window_name;
void row.pane_id;

// @ts-expect-error Obj rows are readonly data.
row.session_name = "changed";
// @ts-expect-error Obj rows can only be created by the guarded parser.
new Obj();
// @ts-expect-error Parsed collections are readonly.
rows.push(row);
// @ts-expect-error The list command vocabulary is closed.
getOutputFormat("list-buffers", "3.7b");
// @ts-expect-error Public format preparation accepts exactly command and raw version.
getOutputFormat("list-sessions", "3.7b", {});
// @ts-expect-error Parsing accepts bytes, never a decoded string.
parseOutput(plan, "guarded frame");
// @ts-expect-error A structural public-shape copy cannot forge the nominal plan.
const forgedPlan: OutputFormatPlan = structuralPlan;
void forgedPlan;
// @ts-expect-error Executor-bound fetch orchestration is intentionally not public in Task 5.
void import("../../src/neo.js").then(({ fetch_obj }) => fetch_obj);
// @ts-expect-error Executor-bound fetch orchestration is intentionally not public in Task 5.
void import("../../src/neo.js").then(({ fetch_objs }) => fetch_objs);

type _ListCommand = Expect<
  Equal<ListCommand, "list-clients" | "list-panes" | "list-sessions" | "list-windows">
>;
type _FormatScope = Expect<
  Equal<
    FormatScope,
    "buffer" | "client" | "context" | "event" | "pane" | "session" | "universal" | "window"
  >
>;
type _ObjKeys = Expect<Equal<keyof Obj, FormatFieldName>>;
type _ObjValues = Expect<Equal<Obj[keyof Obj], string | null>>;
type _ObjWritableKeys = Expect<Equal<WritableKeys<Obj>, never>>;
type _FieldVersion = Expect<
  Equal<typeof FIELD_VERSION, Readonly<Partial<Record<FormatFieldName, string>>>>
>;
type _ScopesByListCommand = Expect<
  Equal<typeof SCOPES_BY_LIST_CMD, Readonly<Record<ListCommand, readonly FormatScope[]>>>
>;
type _Plan = Expect<Equal<typeof plan, OutputFormatPlan>>;
type _PlanKeys = Expect<
  Equal<
    Extract<keyof OutputFormatPlan, string>,
    "fields" | "format" | "guards" | "listCommand" | "tmuxVersion"
  >
>;
type _FormatField = Expect<Equal<OutputFormatField, Readonly<{ token: FormatFieldName }>>>;
type _PlanFields = Expect<Equal<OutputFormatPlan["fields"], readonly OutputFormatField[]>>;
type _PlanGuards = Expect<
  Equal<
    OutputFormatPlan["guards"],
    Readonly<{ field: string; recordEnd: string; recordStart: string }>
  >
>;
type _PlanVersion = Expect<Equal<OutputFormatPlan["tmuxVersion"], TmuxVersionView>>;
type _TmuxVersionView = Expect<
  Equal<TmuxVersionView, Readonly<{ major: number; minor: number; raw: string; suffix: string }>>
>;
type _Rows = Expect<Equal<typeof rows, readonly Obj[]>>;
type _SessionName = Expect<Equal<Obj["session_name"], string | null>>;
type _WindowName = Expect<Equal<Obj["window_name"], string | null>>;
type _PaneId = Expect<Equal<Obj["pane_id"], string | null>>;

declare const formatField: FormatFieldName;
void formatField;
const knownFormatField: FormatFieldName = "session_name";
void knownFormatField;
// @ts-expect-error Unknown format fields fail at the generated public boundary.
const unknownFormatField: FormatFieldName = "libtmux_nonexistent_format_token";
void unknownFormatField;
