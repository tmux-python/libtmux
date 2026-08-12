import { randomUUID } from "node:crypto";

import { FORMAT_FIELD_TOKENS } from "../../_generated/format_fields.js";
import { LibTmuxException, TmuxObjectDoesNotExist } from "../../exc.js";
import { Obj, type FormatFieldName, type ListCommand, type OutputFormatField } from "../../neo.js";
import { prepareCommandRequest } from "../operations/request.js";
import type { TmuxConnection } from "../runtime/connection.js";
import type { CapabilityBinding, TmuxCapabilities } from "../runtime/capabilities.js";
import type { TmuxVersion } from "../runtime/tmux_version.js";
import {
  TransportError,
  type CommandTransport,
  type RawCommandResult,
} from "../transport/types.js";
import { decodeBackslashReplace } from "./backslash_replace.js";
import { formatFieldsForListCommand } from "./format_registry.js";
import { parseCompleteFormatRow, parseFormatIdentity, type CompleteFormatRow } from "./schemas.js";

export interface FormatGuards {
  readonly field: string;
  readonly recordEnd: string;
  readonly recordStart: string;
}

export type GuardFactory = () => FormatGuards;

export interface GuardedFormatRequest {
  readonly capabilityFingerprint: string;
  readonly fields: readonly OutputFormatField[];
  readonly format: string;
  readonly guards: FormatGuards;
  readonly listCommand: ListCommand;
  readonly tmuxVersion: TmuxVersion;
}

export interface GuardCodecOptions {
  readonly capabilities: TmuxCapabilities;
  readonly guardFactory?: GuardFactory;
  readonly listCommand: ListCommand;
}

export class FormatProtocolError extends LibTmuxException {}

function defaultGuardFactory(): FormatGuards {
  return Object.freeze({
    field: `__LIBTMUX_FIELD_${randomUUID()}__`,
    recordEnd: `__LIBTMUX_END_${randomUUID()}__`,
    recordStart: `__LIBTMUX_START_${randomUUID()}__`,
  });
}

function snapshotGuards(guards: FormatGuards): FormatGuards {
  const snapshot = Object.freeze({
    field: guards.field,
    recordEnd: guards.recordEnd,
    recordStart: guards.recordStart,
  });
  const values = [snapshot.field, snapshot.recordEnd, snapshot.recordStart];
  if (
    values.some((value) => typeof value !== "string" || !/^[\x20-\x7e]+$/u.test(value)) ||
    new Set(values).size !== values.length ||
    values.some((value, index) =>
      values.some((other, otherIndex) => index !== otherIndex && other.includes(value)),
    )
  ) {
    throw new FormatProtocolError("guard values must be distinct nonempty printable ASCII");
  }
  return snapshot;
}

function snapshotVersion(version: TmuxVersion): TmuxVersion {
  return Object.freeze({
    major: version.major,
    minor: version.minor,
    raw: version.raw,
    suffix: version.suffix,
  });
}

function bytesFor(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function indexOfBytes(source: Uint8Array, needle: Uint8Array, fromIndex: number): number {
  const lastStart = source.length - needle.length;
  for (let index = fromIndex; index <= lastStart; index += 1) {
    let matches = true;
    for (let offset = 0; offset < needle.length; offset += 1) {
      if (source[index + offset] !== needle[offset]) {
        matches = false;
        break;
      }
    }
    if (matches) return index;
  }
  return -1;
}

function bytesAt(source: Uint8Array, needle: Uint8Array, index: number): boolean {
  return indexOfBytes(source, needle, index) === index;
}

function splitBytes(source: Uint8Array, separator: Uint8Array): readonly Uint8Array[] {
  const fields: Uint8Array[] = [];
  let start = 0;
  while (start <= source.length) {
    const separatorIndex = indexOfBytes(source, separator, start);
    if (separatorIndex < 0) {
      fields.push(source.slice(start));
      break;
    }
    fields.push(source.slice(start, separatorIndex));
    start = separatorIndex + separator.length;
  }
  return fields;
}

function frameBytes(
  request: GuardedFormatRequest,
  bytes: Uint8Array,
): readonly (readonly Uint8Array[])[] {
  const fieldGuard = bytesFor(request.guards.field);
  const recordEndGuard = bytesFor(request.guards.recordEnd);
  const recordStartGuard = bytesFor(request.guards.recordStart);
  const frames: Array<readonly Uint8Array[]> = [];
  let offset = 0;
  while (offset < bytes.length) {
    if (!bytesAt(bytes, recordStartGuard, offset)) {
      throw new FormatProtocolError("guarded output has trailing or unframed bytes");
    }
    const payloadStart = offset + recordStartGuard.length;
    const recordEnd = indexOfBytes(bytes, recordEndGuard, payloadStart);
    if (recordEnd < 0) throw new FormatProtocolError("guarded frame is incomplete");
    const nestedStart = indexOfBytes(bytes, recordStartGuard, payloadStart);
    if (nestedStart >= 0 && nestedStart < recordEnd) {
      throw new FormatProtocolError("guarded frame contains a record-start collision");
    }

    const fields = splitBytes(bytes.slice(payloadStart, recordEnd), fieldGuard);
    if (fields.length !== request.fields.length) {
      throw new FormatProtocolError("guarded frame has the wrong field count");
    }
    frames.push(fields);

    offset = recordEnd + recordEndGuard.length;
    if (offset === bytes.length) break;
    if (bytes[offset] !== 0x0a) {
      throw new FormatProtocolError("guarded frame has trailing bytes after its record end");
    }
    offset += 1;
    if (offset === bytes.length) break;
  }
  return frames;
}

function completeRowData(
  fields: readonly OutputFormatField[],
  values: readonly string[],
): CompleteFormatRow {
  const row = {} as Record<FormatFieldName, string | null>;
  for (const token of FORMAT_FIELD_TOKENS) row[token] = null;
  for (const [index, { token }] of fields.entries()) row[token] = values[index]!;
  return row;
}

function completeObj(row: CompleteFormatRow): Obj {
  const instance = Object.create(Obj.prototype) as Record<FormatFieldName, string | null>;
  for (const token of FORMAT_FIELD_TOKENS) instance[token] = row[token];
  return Object.freeze(instance) as Obj;
}

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

function decodedStderr(bytes: Uint8Array): string {
  return decodeBackslashReplace(bytes).trimEnd();
}

const tmuxStderrByFailure = new WeakMap<LibTmuxException, string>();

function withTmuxStderr(error: LibTmuxException, stderr: string): LibTmuxException {
  tmuxStderrByFailure.set(error, stderr);
  return error;
}

function commandFailure(
  listCommand: ListCommand,
  result: RawCommandResult,
): LibTmuxException | undefined {
  const stderr = decodedStderr(result.stderr);
  if (result.returncode === 0 && result.signal === null && stderr === "") return undefined;
  const message =
    stderr !== ""
      ? stderr
      : result.signal === null
        ? `tmux command failed with status ${result.returncode}`
        : `tmux command failed with signal ${result.signal}`;
  return withTmuxStderr(new LibTmuxException(message, { subcommand: listCommand }), stderr);
}

function transportFailure(listCommand: ListCommand, error: TransportError): LibTmuxException {
  const stderr = decodedStderr(error.stderr);
  return withTmuxStderr(
    new LibTmuxException(stderr === "" ? error.message : stderr, {
      cause: error,
      subcommand: listCommand,
    }),
    stderr,
  );
}

export class GuardCodec {
  readonly #capabilities: TmuxCapabilities;
  readonly #guardFactory: GuardFactory;
  readonly #listCommand: ListCommand;
  readonly #requests = new WeakSet<GuardedFormatRequest>();

  constructor(options: GuardCodecOptions) {
    this.#capabilities = options.capabilities;
    this.#guardFactory = options.guardFactory ?? defaultGuardFactory;
    this.#listCommand = options.listCommand;
  }

  prepare(): GuardedFormatRequest {
    const guards = snapshotGuards(this.#guardFactory());
    const fields: readonly OutputFormatField[] = Object.freeze(
      formatFieldsForListCommand(this.#listCommand, this.#capabilities.rawVersion).map(
        ({ token }) => Object.freeze({ token }),
      ),
    );
    const request: GuardedFormatRequest = Object.freeze({
      capabilityFingerprint: this.#capabilities.fingerprint,
      fields,
      format: `${guards.recordStart}${fields.map(({ token }) => `#{${token}}`).join(guards.field)}${guards.recordEnd}`,
      guards,
      listCommand: this.#listCommand,
      tmuxVersion: snapshotVersion(this.#capabilities.tmuxVersion),
    });
    this.#requests.add(request);
    return request;
  }

  decode(request: GuardedFormatRequest, bytes: Uint8Array): readonly Obj[] {
    if (!this.#requests.has(request)) {
      throw new FormatProtocolError("foreign GuardedFormatRequest");
    }
    if (bytes.length === 0) return Object.freeze([]);

    const encodedFrames = frameBytes(request, bytes);
    const rows: Obj[] = [];
    for (const encodedFields of encodedFrames) {
      const decodedFields = encodedFields.map((field) => decodeBackslashReplace(field));
      if (decodedFields.some((value) => /^#\{[^}]+\}$/u.test(value))) {
        throw new FormatProtocolError("tmux returned a literal unknown format token");
      }

      let row: CompleteFormatRow;
      try {
        row = parseCompleteFormatRow(
          request.listCommand,
          completeRowData(request.fields, decodedFields),
        );
      } catch (error) {
        throw new FormatProtocolError("guarded row schema validation failed", { cause: error });
      }
      rows.push(completeObj(row));
    }
    return Object.freeze(rows);
  }
}

interface GuardedExecutionOptions {
  readonly capabilities: CapabilityBinding;
  readonly connection: TmuxConnection;
  readonly listExtraArgs?: readonly string[];
  readonly transport: CommandTransport;
}

export type GuardedListOptions = GuardedExecutionOptions & {
  readonly listCommand: ListCommand;
};

export type GuardedFetchOptions = GuardedExecutionOptions &
  (
    | {
        readonly identityField: "client_name";
        readonly identityValue: string;
        readonly listCommand: "list-clients";
      }
    | {
        readonly identityField: "pane_id";
        readonly identityValue: string;
        readonly listCommand: "list-panes";
      }
    | {
        readonly identityField: "session_id";
        readonly identityValue: string;
        readonly listCommand: "list-sessions";
      }
    | {
        readonly identityField: "window_id";
        readonly identityValue: string;
        readonly listCommand: "list-windows";
      }
  );

export async function executeGuardedList(options: GuardedListOptions): Promise<readonly Obj[]> {
  const listExtraArgs: readonly string[] = Object.freeze([...(options.listExtraArgs ?? [])]);
  const capabilities = await options.capabilities.bind();
  const codec = new GuardCodec({ capabilities, listCommand: options.listCommand });
  const guardedRequest = codec.prepare();
  const commandRequest = prepareCommandRequest(options.connection, [
    options.listCommand,
    ...listExtraArgs,
    `-F${guardedRequest.format}`,
  ]);
  const currentCapabilities = await options.capabilities.bind();
  if (currentCapabilities.fingerprint !== guardedRequest.capabilityFingerprint) {
    throw new FormatProtocolError("capability fingerprint changed before execution");
  }

  let result: RawCommandResult;
  try {
    result = await options.transport.execute(commandRequest);
  } catch (error) {
    if (!(error instanceof TransportError)) throw error;
    throw transportFailure(options.listCommand, error);
  }
  const failure = commandFailure(options.listCommand, result);
  if (failure !== undefined) throw failure;
  return codec.decode(guardedRequest, result.stdout);
}

export async function executeGuardedFetch(options: GuardedFetchOptions): Promise<Obj> {
  if (options.identityField !== primaryIdentity(options.listCommand)) {
    throw new FormatProtocolError("point identity field does not match its list command");
  }
  try {
    parseFormatIdentity(options.listCommand, options.identityValue);
  } catch (error) {
    throw new FormatProtocolError("point identity value does not match its list command", {
      cause: error,
    });
  }

  let rows: readonly Obj[];
  try {
    rows = await executeGuardedList(options);
  } catch (error) {
    if (
      !(error instanceof LibTmuxException) ||
      !isTargetNotFoundError(tmuxStderrByFailure.get(error) ?? "")
    ) {
      throw error;
    }
    throw new TmuxObjectDoesNotExist({
      list_cmd: options.listCommand,
      ...(options.listExtraArgs === undefined ? {} : { list_extra_args: options.listExtraArgs }),
      obj_id: options.identityValue,
      obj_key: options.identityField,
    });
  }
  const matches = rows.filter((row) => row[options.identityField] === options.identityValue);
  if (matches.length === 0) {
    throw new TmuxObjectDoesNotExist({
      list_cmd: options.listCommand,
      ...(options.listExtraArgs === undefined ? {} : { list_extra_args: options.listExtraArgs }),
      obj_id: options.identityValue,
      obj_key: options.identityField,
    });
  }
  return selectBestWinlink(matches);
}

export function isTargetNotFoundError(message: string): boolean {
  return message.includes("can't find ");
}

export function selectBestWinlink<
  Row extends Readonly<{
    window_active?: string | null;
    window_id?: string | null;
    window_index?: string | null;
  }>,
>(rows: readonly Row[]): Row {
  if (rows.length === 0) throw new FormatProtocolError("cannot select from an empty winlink set");
  if (rows.length === 1) return rows[0]!;
  for (const row of rows) {
    if (row.window_active === "1") return row;
  }

  const windowIndex = (row: Row): number => {
    if (
      row.window_index === undefined ||
      row.window_index === null ||
      !/^\d+$/u.test(row.window_index)
    ) {
      throw new FormatProtocolError("winlink row has an invalid window_index");
    }
    const index = Number.parseInt(row.window_index, 10);
    if (!Number.isSafeInteger(index)) {
      throw new FormatProtocolError("winlink row has an invalid window_index");
    }
    return index;
  };
  let selected = rows[0]!;
  let selectedIndex = windowIndex(selected);
  for (const row of rows.slice(1)) {
    const index = windowIndex(row);
    if (index < selectedIndex) {
      selected = row;
      selectedIndex = index;
    }
  }
  return selected;
}
