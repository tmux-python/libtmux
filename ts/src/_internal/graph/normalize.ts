import { FORMAT_FIELD_TOKENS } from "../../_generated/format_fields.js";
import type { ConnectionAlias, DaemonEpoch, PaneRef, SessionRef, WindowRef } from "../../common.js";
import { QueryValidationError } from "../../exc.js";
import { Obj, type FormatFieldName, type ListCommand } from "../../neo.js";
import type { CompleteFormatRow } from "../codec/schemas.js";
import {
  createGraphRecordRef,
  createGraphSourceId,
  createNormalizedGraph,
  type CapturedRowSet,
  type ClientRef,
  type GraphCapture,
  type GraphEntity,
  type GraphEntityRef,
  type GraphModel,
  type GraphRecord,
  type GraphRecordRef,
  type GraphSource,
  type NormalizedGraph,
  type WinlinkEntity,
} from "./model.js";
import { createLogicalRef, createWinlinkRef, type WinlinkRef } from "./refs.js";

export interface NormalizeGraphInput {
  readonly capture: GraphCapture;
  readonly sources: readonly CapturedRowSet[];
}

interface EntityAccumulator<Ref extends GraphEntityRef> {
  readonly occurrences: GraphRecordRef[];
  readonly ref: Ref;
}

interface WinlinkAccumulator {
  readonly occurrences: GraphRecordRef[];
  readonly ref: WinlinkRef;
}

const formatFieldTokenSet: ReadonlySet<string> = new Set(FORMAT_FIELD_TOKENS);

function invalidNormalization(message: string, cause?: unknown): never {
  throw new QueryValidationError(
    cause === undefined
      ? { code: "invalid-query", message }
      : { cause, code: "invalid-query", message },
  );
}

function readProperty(value: unknown, key: string, label: string): unknown {
  if (typeof value !== "object" || value === null) {
    return invalidNormalization(`${label} must be an object`);
  }
  try {
    return Reflect.get(value, key);
  } catch (error) {
    return invalidNormalization(`${label} could not be inspected`, error);
  }
}

function parseConnection(value: unknown): ConnectionAlias {
  if (typeof value !== "string" || value.length === 0) {
    return invalidNormalization("graph capture connection must be a nonempty string");
  }
  return value as ConnectionAlias;
}

function parseEpoch(value: unknown): DaemonEpoch {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    return invalidNormalization("graph capture epoch must be a nonnegative safe integer");
  }
  return value as DaemonEpoch;
}

function parseCapture(value: unknown): GraphCapture {
  const connection = parseConnection(readProperty(value, "connection", "graph capture"));
  const epoch = parseEpoch(readProperty(value, "epoch", "graph capture"));
  const capabilityFingerprint = readProperty(value, "capabilityFingerprint", "graph capture");
  if (typeof capabilityFingerprint !== "string" || capabilityFingerprint.length === 0) {
    return invalidNormalization("graph capture capability fingerprint must be a nonempty string");
  }
  return Object.freeze({ connection, epoch, capabilityFingerprint });
}

function parseListCommand(value: unknown): ListCommand {
  switch (value) {
    case "list-clients":
    case "list-panes":
    case "list-sessions":
    case "list-windows":
      return value;
    default:
      return invalidNormalization("graph source list command is invalid");
  }
}

function parseRows(value: unknown): readonly unknown[] {
  let isArray: boolean;
  let lengthDescriptor: PropertyDescriptor | undefined;
  const elementDescriptors: Array<PropertyDescriptor | undefined> = [];
  try {
    isArray = Array.isArray(value);
    if (isArray) {
      lengthDescriptor = Object.getOwnPropertyDescriptor(value, "length");
      const length = lengthDescriptor?.value;
      if (typeof length === "number" && Number.isSafeInteger(length) && length >= 0) {
        for (let index = 0; index < length; index += 1) {
          elementDescriptors.push(Object.getOwnPropertyDescriptor(value, String(index)));
        }
      }
    }
  } catch (error) {
    return invalidNormalization("graph source rows could not be inspected", error);
  }

  if (!isArray) {
    return invalidNormalization("graph source rows must be an array");
  }
  if (
    lengthDescriptor === undefined ||
    !("value" in lengthDescriptor) ||
    lengthDescriptor.enumerable ||
    typeof lengthDescriptor.value !== "number" ||
    !Number.isSafeInteger(lengthDescriptor.value) ||
    lengthDescriptor.value < 0 ||
    elementDescriptors.length !== lengthDescriptor.value
  ) {
    return invalidNormalization("graph source rows must have a valid array length");
  }

  const rows: unknown[] = [];
  for (const descriptor of elementDescriptors) {
    if (descriptor === undefined || !("value" in descriptor) || !descriptor.enumerable) {
      return invalidNormalization("graph source rows must contain own enumerable data elements");
    }
    rows.push(descriptor.value);
  }
  return rows;
}

function copyCompleteFormatRow(value: unknown): CompleteFormatRow {
  if (typeof value !== "object" || value === null) {
    return invalidNormalization("captured format row must be an object");
  }

  let isArray: boolean;
  let prototype: object | null;
  let ownKeys: readonly PropertyKey[];
  let descriptors: readonly (PropertyDescriptor | undefined)[];
  let finalPrototype: object | null;
  let finalOwnKeys: readonly PropertyKey[];
  try {
    isArray = Array.isArray(value);
    prototype = Object.getPrototypeOf(value);
    ownKeys = Reflect.ownKeys(value);
    descriptors = FORMAT_FIELD_TOKENS.map((token) => Object.getOwnPropertyDescriptor(value, token));
    finalPrototype = Object.getPrototypeOf(value);
    finalOwnKeys = Reflect.ownKeys(value);
  } catch (error) {
    return invalidNormalization("captured format row could not be inspected", error);
  }

  if (
    isArray ||
    prototype !== finalPrototype ||
    (prototype !== Object.prototype && prototype !== null && prototype !== Obj.prototype) ||
    (finalPrototype !== Object.prototype &&
      finalPrototype !== null &&
      finalPrototype !== Obj.prototype)
  ) {
    return invalidNormalization("captured format row must use a supported data prototype");
  }
  if (
    ownKeys.length !== FORMAT_FIELD_TOKENS.length ||
    ownKeys.some((key) => typeof key !== "string" || !formatFieldTokenSet.has(key)) ||
    ownKeys.length !== finalOwnKeys.length ||
    ownKeys.some((key) => !finalOwnKeys.includes(key))
  ) {
    return invalidNormalization("captured format row must contain exactly the generated fields");
  }

  const entries: Array<readonly [FormatFieldName, string | null]> = [];
  for (const [index, token] of FORMAT_FIELD_TOKENS.entries()) {
    const descriptor = descriptors[index];
    if (descriptor === undefined || !("value" in descriptor) || !descriptor.enumerable) {
      return invalidNormalization("captured format row fields must be enumerable data properties");
    }
    if (typeof descriptor.value !== "string" && descriptor.value !== null) {
      return invalidNormalization("captured format row fields must be strings or null");
    }
    entries.push([token, descriptor.value]);
  }

  return Object.freeze(Object.fromEntries(entries)) as CompleteFormatRow;
}

function parseSessionId(value: string | null, required: boolean): string | null {
  if (value === null || value.length === 0) {
    if (required) return invalidNormalization("session topology requires a session ID");
    return null;
  }
  if (!/^\$\d+$/u.test(value)) {
    return invalidNormalization("session ID must use the session sigil");
  }
  return value;
}

function parseWindowId(value: string | null, required: boolean): string | null {
  if (value === null || value.length === 0) {
    if (required) return invalidNormalization("window topology requires a window ID");
    return null;
  }
  if (!/^@\d+$/u.test(value)) {
    return invalidNormalization("window ID must use the window sigil");
  }
  return value;
}

function parsePaneId(value: string | null, required: boolean): string | null {
  if (value === null || value.length === 0) {
    if (required) return invalidNormalization("pane topology requires a pane ID");
    return null;
  }
  if (!/^%\d+$/u.test(value)) {
    return invalidNormalization("pane ID must use the pane sigil");
  }
  return value;
}

function parseClientId(value: string | null, required: boolean): string | null {
  if (value === null || value.length === 0) {
    if (required) return invalidNormalization("client topology requires a client name");
    return null;
  }
  if (/^[%$@]/u.test(value)) {
    return invalidNormalization("client name must not use a tmux object sigil");
  }
  return value;
}

function parseWindowIndex(value: string | null, required: boolean): string | null {
  if (value === null || value.length === 0) {
    if (required) return invalidNormalization("window topology requires a window index");
    return null;
  }
  if (!/^(?:0|[1-9]\d*)$/u.test(value) || !Number.isSafeInteger(Number(value))) {
    return invalidNormalization("window index must be canonical safe unsigned decimal text");
  }
  return value;
}

function validatePopulatedIdentities(row: CompleteFormatRow): void {
  parseSessionId(row.session_id, false);
  parseWindowId(row.window_id, false);
  parsePaneId(row.pane_id, false);
  parseClientId(row.client_name, false);
  parseWindowIndex(row.window_index, false);
}

function freezeEntity<Ref extends GraphEntityRef>(
  accumulator: EntityAccumulator<Ref>,
): GraphEntity<Ref> {
  return Object.freeze({
    ref: accumulator.ref,
    occurrences: Object.freeze([...accumulator.occurrences]),
  });
}

function freezeWinlink(accumulator: WinlinkAccumulator): WinlinkEntity {
  return Object.freeze({
    ref: accumulator.ref,
    occurrences: Object.freeze([...accumulator.occurrences]),
  });
}

export function normalizeGraph(input: NormalizeGraphInput): NormalizedGraph {
  const capture = parseCapture(readProperty(input, "capture", "normalization input"));
  const sourceInputs = parseRows(readProperty(input, "sources", "normalization input"));
  const seenSourceIds = new Set<string>();
  const sources: GraphSource[] = [];
  const records: GraphRecord[] = [];
  const sessions = new Map<string, EntityAccumulator<SessionRef>>();
  const windows = new Map<string, EntityAccumulator<WindowRef>>();
  const panes = new Map<string, EntityAccumulator<PaneRef>>();
  const clients = new Map<string, EntityAccumulator<ClientRef>>();
  const winlinks = new Map<string, WinlinkAccumulator>();

  const addSession = (id: string, occurrence: GraphRecordRef): SessionRef => {
    const existing = sessions.get(id);
    if (existing !== undefined) {
      existing.occurrences.push(occurrence);
      return existing.ref;
    }
    const ref = createLogicalRef({
      connection: capture.connection,
      epoch: capture.epoch,
      kind: "session",
      id,
    });
    sessions.set(id, { ref, occurrences: [occurrence] });
    return ref;
  };

  const addWindow = (id: string, occurrence: GraphRecordRef): WindowRef => {
    const existing = windows.get(id);
    if (existing !== undefined) {
      existing.occurrences.push(occurrence);
      return existing.ref;
    }
    const ref = createLogicalRef({
      connection: capture.connection,
      epoch: capture.epoch,
      kind: "window",
      id,
    });
    windows.set(id, { ref, occurrences: [occurrence] });
    return ref;
  };

  const addPane = (id: string, occurrence: GraphRecordRef): PaneRef => {
    const existing = panes.get(id);
    if (existing !== undefined) {
      existing.occurrences.push(occurrence);
      return existing.ref;
    }
    const ref = createLogicalRef({
      connection: capture.connection,
      epoch: capture.epoch,
      kind: "pane",
      id,
    });
    panes.set(id, { ref, occurrences: [occurrence] });
    return ref;
  };

  const addClient = (id: string, occurrence: GraphRecordRef): ClientRef => {
    const existing = clients.get(id);
    if (existing !== undefined) {
      existing.occurrences.push(occurrence);
      return existing.ref;
    }
    const ref = Object.freeze({
      connection: capture.connection,
      epoch: capture.epoch,
      kind: "client" as const,
      id,
    });
    clients.set(id, { ref, occurrences: [occurrence] });
    return ref;
  };

  const addWinlink = (
    sessionId: string,
    windowId: string,
    windowIndex: string,
    occurrence: GraphRecordRef,
  ): WinlinkRef => {
    const key = `${sessionId}\u0000${windowIndex}`;
    const existing = winlinks.get(key);
    if (existing !== undefined) {
      if (existing.ref.windowId !== windowId) {
        return invalidNormalization("conflicting winlink ownership for one session index");
      }
      existing.occurrences.push(occurrence);
      return existing.ref;
    }
    const ref = createWinlinkRef({
      connection: capture.connection,
      epoch: capture.epoch,
      sessionId,
      windowId,
      windowIndex,
    });
    winlinks.set(key, { ref, occurrences: [occurrence] });
    return ref;
  };

  for (const sourceInput of sourceInputs) {
    const source = createGraphSourceId(
      readProperty(sourceInput, "source", "graph source") as string,
    );
    if (seenSourceIds.has(source)) {
      return invalidNormalization(`duplicate graph source ${source}`);
    }
    seenSourceIds.add(source);
    const listCommand = parseListCommand(readProperty(sourceInput, "listCommand", "graph source"));
    const rows = parseRows(readProperty(sourceInput, "rows", "graph source"));
    const sourceRecords: GraphRecordRef[] = [];

    for (const [ordinal, rowInput] of rows.entries()) {
      const scalars = copyCompleteFormatRow(rowInput);
      validatePopulatedIdentities(scalars);
      const ref = createGraphRecordRef(source, ordinal);
      let model: GraphModel;
      let entity: GraphEntityRef;
      let winlink: WinlinkRef | null = null;

      switch (listCommand) {
        case "list-clients": {
          const clientId = parseClientId(scalars.client_name, true);
          if (clientId === null) return invalidNormalization("client topology is incomplete");
          model = "client";
          entity = addClient(clientId, ref);
          break;
        }
        case "list-panes": {
          const sessionId = parseSessionId(scalars.session_id, true);
          const windowId = parseWindowId(scalars.window_id, true);
          const windowIndex = parseWindowIndex(scalars.window_index, true);
          const paneId = parsePaneId(scalars.pane_id, true);
          if (sessionId === null || windowId === null || windowIndex === null || paneId === null) {
            return invalidNormalization("pane topology is incomplete");
          }
          addSession(sessionId, ref);
          addWindow(windowId, ref);
          model = "pane";
          entity = addPane(paneId, ref);
          winlink = addWinlink(sessionId, windowId, windowIndex, ref);
          break;
        }
        case "list-sessions": {
          const sessionId = parseSessionId(scalars.session_id, true);
          if (sessionId === null) return invalidNormalization("session topology is incomplete");
          model = "session";
          entity = addSession(sessionId, ref);
          break;
        }
        case "list-windows": {
          const sessionId = parseSessionId(scalars.session_id, true);
          const windowId = parseWindowId(scalars.window_id, true);
          const windowIndex = parseWindowIndex(scalars.window_index, true);
          if (sessionId === null || windowId === null || windowIndex === null) {
            return invalidNormalization("window topology is incomplete");
          }
          addSession(sessionId, ref);
          model = "window";
          entity = addWindow(windowId, ref);
          winlink = addWinlink(sessionId, windowId, windowIndex, ref);
          break;
        }
      }

      const record = Object.freeze({ ref, model, entity, winlink, scalars });
      sourceRecords.push(ref);
      records.push(record);
    }

    sources.push(Object.freeze({ id: source, listCommand, records: Object.freeze(sourceRecords) }));
  }

  return createNormalizedGraph({
    capture,
    sources: Object.freeze(sources),
    sessions: Object.freeze([...sessions.values()].map(freezeEntity)),
    windows: Object.freeze([...windows.values()].map(freezeEntity)),
    panes: Object.freeze([...panes.values()].map(freezeEntity)),
    clients: Object.freeze([...clients.values()].map(freezeEntity)),
    winlinks: Object.freeze([...winlinks.values()].map(freezeWinlink)),
    records: Object.freeze(records),
  });
}
